"""Loads the illustrative seed. Deterministic: no randomness, dates relative to the load day."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.decisions.audit import SYSTEM, audit
from app.integrations import media
from app.ledger import service as ledger
from app.models import (Alert, AppMeta, Assignment, Base, Driver, EomService, ProviderTransaction, Vehicle)
from app.reconciliation.service import create_alert, transaction_hash
from app.rules.catalog import CATALOG_BY_CODE, CNG_M3_PER_GALLON, EFFICIENCY_UNITS, GROUP_MEDIANS
from app.rules.engine import quantile, typical_load
from app.rules.repository import rules_version_label, seed_rules
from app.seed import data as seed
from app.seed.photos import ensure_photos
from app.timeutil import at, fmt_int, fmt_num, fmt_unit, hhmm, now, today

log = logging.getLogger(__name__)

HOURS = ["06:10", "07:25", "09:40", "12:15", "15:30", "17:45", "05:35", "08:50"]
FUEL_TYPES = {"gasoline": "gasoline", "dual_fuel": "dual_fuel", "light_diesel": "diesel", "heavy_diesel": "diesel",
              "cng": "cng"}
PRODUCTS = {"gasoline": ("Gasolina Corriente", "gal"), "dual_fuel": ("Gasolina Corriente", "gal"),
            "light_diesel": ("Diesel", "gal"), "heavy_diesel": ("Diesel", "gal"), "cng": ("GNV", "m3")}
REVIEWER = "Andrés Molina"


def ensure_seed(db: Session) -> str:
    """Loads the seed if the database is empty, or reloads it if it was loaded on another day
    (the EOM services "of today" must exist for the demo)."""
    meta = db.get(AppMeta, "seed_date")
    if meta is None:
        reset_and_load(db)
        return "cargada"
    if meta.value != today().isoformat():
        reset_and_load(db)
        return f"recargada (la anterior era del {meta.value})"
    return "vigente"


def seed_date(db: Session) -> str | None:
    meta = db.get(AppMeta, "seed_date")
    return meta.value if meta else None


def reset_and_load(db: Session) -> dict:
    """Demo reset: empties every table and loads the seed again (demo databases only)."""
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    db.commit()
    summary = load(db)
    db.commit()
    return summary


# --------------------------------------------------------------------------- builders

def _events_for(spec: dict, day0: date) -> list[dict]:
    events: list[dict] = []
    for stream in spec.get("streams", []):
        n, start, end = stream["n"], stream["start"], stream["end"]
        shift = stream.get("hour_shift", 0)
        for i in range(n):
            days_ago = start - round(i * (start - end) / (n - 1)) if n > 1 else end
            station = stream["stations"][i % len(stream["stations"])]
            price = seed.STATION_PRICES[station][stream["product"]]
            if "amounts" in stream:
                amount = stream["amounts"][i % len(stream["amounts"])]
                quantity = round(amount / price, 3)
            else:
                quantity = stream["quantities"][i % len(stream["quantities"])]
                amount = int(round(quantity * price))
            events.append({"timestamp": at(day0 - timedelta(days=days_ago), HOURS[(i + shift) % len(HOURS)]),
                           "provider": stream["provider"], "product": stream["product"], "station": station,
                           "price": price, "quantity": quantity, "amount": amount, "sale_type": "En línea"})
    events.sort(key=lambda e: e["timestamp"])
    for i in range(1, len(events)):  # never two refuels at the same minute
        if events[i]["timestamp"] <= events[i - 1]["timestamp"]:
            events[i]["timestamp"] = events[i - 1]["timestamp"] + timedelta(minutes=95)
    return events


def _km_per_unit(spec: dict, product: str) -> float:
    efficiency = spec.get("efficiency") or GROUP_MEDIANS[spec["group"]]
    if spec["group"] == "dual_fuel" and ledger.tank_of(product) == "cng":
        return efficiency / CNG_M3_PER_GALLON
    return efficiency


def _build_transactions(spec: dict, day0: date) -> list[dict]:
    events = _events_for(spec, day0)
    for index, changes in (spec.get("overrides") or {}).items():
        event = events[index]
        if "hour" in changes:
            event["timestamp"] = at(event["timestamp"].date(), changes["hour"])
        if "quantity" in changes:
            event["quantity"] = changes["quantity"]
            event["amount"] = int(round(changes["quantity"] * event["price"]))
        for key in ("km_from_prev", "sale_type"):
            if key in changes:
                event[key] = changes[key]
        if "odometer" in changes:
            event["no_odometer"] = True
    last = spec.get("last")
    if last:
        price = seed.STATION_PRICES[last["station"]][last["product"]]
        quantity = last.get("quantity") or round(last["amount"] / price, 3)
        events.append({"timestamp": at(day0 - timedelta(days=1), last["hour"]), "provider": spec["provider"],
                       "product": last["product"], "station": last["station"], "price": price, "quantity": quantity,
                       "amount": last.get("amount") or int(round(quantity * price)), "sale_type": "En línea",
                       "km_from_prev": last.get("gap_km")})

    # Odometer backwards from the last known reading: each interval is what the previous load yields.
    total_km = spec.get("total_km")
    intervals = len(events) - 1
    odometer = spec["last_odo"]
    for i in range(len(events) - 1, -1, -1):
        events[i]["odometer"] = odometer
        if i == 0:
            break
        if events[i].get("km_from_prev") is not None:
            km = events[i]["km_from_prev"]
        elif total_km:
            km = total_km // intervals + (total_km % intervals if i == intervals else 0)
        else:
            km = round(events[i - 1]["quantity"] * _km_per_unit(spec, events[i - 1]["product"]))
        odometer -= km
    if spec.get("frozen"):  # the station repeats the same value in most refuels
        frozen_value = events[0]["odometer"]
        for i, event in enumerate(events):
            if i % 8 < 5:
                event["odometer"] = frozen_value
    every = spec.get("missing_odometer_every")
    for i, event in enumerate(events):
        if event.get("no_odometer") or (every and i % every == 3):
            event["odometer"] = None
    return events


def _veh160_transactions(day0: date) -> list[dict]:
    """GoPass sees 4,803 km and 6.135 gal between its two refuels; Terpel sold 34 gas loads in between."""
    events: list[dict] = []
    gas_price, liquid_price = seed.STATION_PRICES[seed.G1]["GNV"], seed.STATION_PRICES[seed.P1]["Gasolina Corriente"]

    def add(days_ago: int, hour: str, provider: str, product: str, station: str, price: float, quantity: float,
            odometer: int) -> None:
        events.append({"timestamp": at(day0 - timedelta(days=days_ago), hour), "provider": provider, "product": product,
                       "station": station, "price": price, "quantity": quantity, "amount": int(round(quantity * price)),
                       "sale_type": "En línea", "odometer": odometer})

    for i, days_ago in enumerate((88, 85, 82)):
        add(days_ago, HOURS[i], "terpel", "GNV", seed.G1, gas_price, 9.2, 28500 + i * 140)
    first_odo, last_odo = 28930, 33733
    add(80, "07:10", "gopass", "Gasolina Corriente", seed.P1, liquid_price, 6.0, first_odo)
    for i in range(34):  # 33 x 9.2 + 10.0 = 313.6 m3
        days_ago = 78 - round(i * 70 / 33)
        quantity = 10.0 if i == 33 else 9.2
        add(days_ago, HOURS[i % len(HOURS)], "terpel", "GNV", seed.G1 if i % 2 else seed.G2, gas_price, quantity,
            first_odo + round((i + 1) * (last_odo - first_odo) / 35))
    add(6, "10:33", "gopass", "Gasolina Corriente", seed.P1, liquid_price, 6.135, last_odo)
    add(4, "08:20", "terpel", "GNV", seed.G1, gas_price, 9.2, last_odo + 120)
    add(2, "17:05", "terpel", "GNV", seed.G2, gas_price, 9.2, last_odo + 265)
    events.sort(key=lambda e: e["timestamp"])
    return events


def _services(spec: dict, vehicle: Vehicle, day0: date, counter: list[int]) -> list[EomService]:
    eom = spec.get("eom")
    if eom is None:
        return []
    plan: list[tuple[date, list[str]]] = []
    if "old_days" in eom:
        first, last = eom["old_days"]
        plan = [(day0 - timedelta(days=d), seed.FULL_DAY[:4]) for d in range(first, last - 1, -1)]
    else:
        for offset in range(-7, 2):
            hours = eom.get("today", seed.FULL_DAY[:8]) if offset == 0 else seed.FULL_DAY[:8]
            plan.append((day0 + timedelta(days=offset), hours))
    rows = []
    for day, hours in plan:
        for i, hour in enumerate(hours):
            start = at(day, hour)
            origin, destination = seed.ROUTES[(i + vehicle.id) % len(seed.ROUTES)]
            counter[0] += 1
            rows.append(EomService(external_id=f"EOM-{counter[0]:06d}", vehicle_id=vehicle.id, start=start,
                                   end=start + timedelta(minutes=55), km=ledger.km_per_service(seed.ZONE),
                                   zone=seed.ZONE, department=seed.DEPARTMENT, origin=origin, destination=destination))
    return rows


def _alert_text(template: str, tx: ProviderTransaction, previous: ProviderTransaction | None,
                same_tank: list[ProviderTransaction]) -> str:
    others = [t.quantity for t in same_tank if t.id != tx.id]
    km = tx.odometer - previous.odometer if previous and tx.odometer is not None and previous.odometer is not None else None
    days = (tx.timestamp - previous.timestamp).total_seconds() / 86400 if previous else None
    return template.format(
        qty=fmt_num(tx.quantity, 1), unit=fmt_unit(tx.unit), km=fmt_int(km), days=fmt_num(days, 1),
        time=hhmm(tx.timestamp), typical=fmt_num(typical_load(others), 1), largest=fmt_num(quantile(others, 0.95), 1),
        sale_type=tx.sale_type)


# --------------------------------------------------------------------------- load

def load(db: Session) -> dict:
    day0 = today()
    ensure_photos()
    media.reset_cache()
    seed_rules(db)
    db.flush()
    version = rules_version_label(db)

    service_counter = [0]
    ledgers: dict[str, list[ProviderTransaction]] = {}
    vehicles: dict[str, Vehicle] = {}
    for number, spec in enumerate(seed.VEHICLES, start=1):
        group = spec["group"]
        product, unit = PRODUCTS[group]
        vehicle = Vehicle(code=spec["code"], plate=spec["plate"], fuel_type=FUEL_TYPES[group], group=group,
                          product=product, unit=unit, tank_capacity=seed.CAPACITY[group],
                          reference_efficiency=spec.get("efficiency"), efficiency_unit=EFFICIENCY_UNITS[group],
                          zone=seed.ZONE, department=seed.DEPARTMENT, provider=spec["provider"],
                          flags=list(spec.get("flags", [])), stats={})
        driver = Driver(name=spec["driver"], phone=spec["phone"])
        db.add_all([vehicle, driver])
        db.flush()
        vehicles[vehicle.code] = vehicle
        db.add(Assignment(vehicle_id=vehicle.id, driver_id=driver.id, valid_from=at(day0 - timedelta(days=120), "00:00")))

        events = _veh160_transactions(day0) if spec.get("custom") == "veh160" else _build_transactions(spec, day0)
        rows = []
        for k, event in enumerate(events, start=1):
            tank = ledger.tank_of(event["product"])
            external_id = f"{event['provider'][:3].upper()}-{number:02d}{k:04d}"
            rows.append(ProviderTransaction(
                provider=event["provider"], external_id=external_id, vehicle_id=vehicle.id,
                tx_hash=transaction_hash(event["provider"], external_id, vehicle.code, event["timestamp"],
                                         event["product"], event["quantity"], event["amount"]),
                timestamp=event["timestamp"], station=event["station"], region=seed.REGION, product=event["product"],
                tank=tank, quantity=event["quantity"], unit="m3" if tank == "cng" else "gal",
                unit_price=event["price"], amount=event["amount"], odometer=event["odometer"],
                sale_type=event["sale_type"], source="seed"))
        db.add_all(rows)
        services = _services(spec, vehicle, day0, service_counter)
        db.add_all(services)
        db.flush()
        ledgers[vehicle.code] = rows

        stats = {"refuels_90d": len(rows), "amount_90d": sum(r.amount for r in rows),
                 "services_90d": 0 if spec.get("eom") is None else len(services) * 10,
                 "providers": sorted({r.provider for r in rows})}
        stats.update(spec.get("stats", {}))
        vehicle.stats = stats

    rules_now = {code: rule for code, rule in CATALOG_BY_CODE.items()}
    created_default_hour = "07:00"

    # Refuel alerts: the historical test of the rules.
    for item in seed.REFUEL_ALERTS:
        vehicle = vehicles[item["vehicle"]]
        rows = ledgers[vehicle.code]
        tx = rows[item["index"]]
        previous = rows[item["index"] - 1] if item["index"] > 0 else None
        same_tank = [r for r in rows if r.tank == tx.tank]
        reasons = [{"code": code, "name": rules_now[code].name, "points": rules_now[code].points,
                    "explanation": _alert_text(template, tx, previous, same_tank)} for code, template in item["rules"]]
        created = (at(day0 - timedelta(days=item["created_days_ago"]), created_default_hour)
                   if "created_days_ago" in item else at((tx.timestamp + timedelta(days=1)).date(), created_default_hour))
        alert = create_alert(db, kind="refuel", entity="provider_transaction", entity_id=tx.id, vehicle=vehicle,
                             reasons=reasons, version=version, created_at=created,
                             evidence={"transaction": ledger.transaction_payload(tx),
                                       "previous_transaction": ledger.transaction_payload(previous) if previous else None,
                                       "source": "Prueba con datos históricos"})
        _apply_review(alert, item.get("review"))

    # Vehicle alerts: rules V01..V08 from the 90-day analysis.
    for vehicle in vehicles.values():
        flags = ledger.vehicle_flags(vehicle)
        if not flags:
            continue
        days_ago = seed.VEHICLE_ALERT_CREATED_DAYS_AGO.get(vehicle.code, 1)
        review = seed.VEHICLE_ALERT_REVIEWS.get(vehicle.code)
        created = at(day0 - timedelta(days=8 if review else days_ago), created_default_hour)
        alert = create_alert(db, kind="vehicle", entity="vehicle", entity_id=vehicle.id, vehicle=vehicle,
                             reasons=[{"code": f["code"], "name": f["name"], "points": f["points"],
                                       "explanation": f["explanation"]} for f in flags],
                             version=version, created_at=created,
                             evidence={"efficiency": ledger.efficiency_summary(vehicle), "stats": vehicle.stats,
                                       "ledger_url": f"/api/vehicles/{vehicle.code}/ledger",
                                       "source": "Análisis de 90 días"})
        _apply_review(alert, review)

    db.merge(AppMeta(key="seed_date", value=day0.isoformat()))
    db.merge(AppMeta(key="seed_loaded_at", value=now().isoformat(timespec="seconds")))
    counts = {
        "seed_date": day0.isoformat(),
        "vehicles": len(vehicles),
        "drivers": len(vehicles),
        "transactions": sum(len(r) for r in ledgers.values()),
        "eom_services": service_counter[0],
        "alerts": len(db.scalars(select(Alert.id)).all()),
        "rules": len(CATALOG_BY_CODE),
    }
    audit(db, SYSTEM, "seed.loaded", "seed", day0.isoformat(),
          summary=(f"Semilla ilustrativa cargada: {counts['vehicles']} vehículos, {counts['transactions']} tanqueos, "
                   f"{counts['eom_services']} servicios de EOM y {counts['alerts']} alertas"), after=counts)
    db.flush()
    log.info("Semilla cargada: %s", counts)
    return counts


def _apply_review(alert: Alert, review: tuple | None) -> None:
    if not review:
        return
    result, comment, hours_later = review
    alert.status = "reviewed"
    alert.review_result = result
    alert.review_comment = comment
    alert.reviewed_by = REVIEWER
    alert.reviewed_at = min(alert.created_at + timedelta(hours=hours_later), now())


def loaded_at(db: Session) -> datetime | None:
    meta = db.get(AppMeta, "seed_loaded_at")
    return datetime.fromisoformat(meta.value) if meta else None
