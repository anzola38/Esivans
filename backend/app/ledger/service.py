"""Single refuel ledger: every transaction of every provider, per vehicle, plus EOM services.

Each request is cross-checked against this ledger: last refuel of ANY provider, km traveled,
efficiency against its group and the services of the day.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import EomService, ProviderTransaction, Vehicle
from app.rules.catalog import (CATALOG_BY_CODE, CNG_M3_PER_GALLON, EFFICIENCY_UNITS, GROUP_LABELS,
                               GROUP_MEDIANS)
from app.rules.engine import ActiveRule, quantile, typical_load
from app.timeutil import fmt_cop, fmt_int, fmt_num, fmt_pct, iso, to_local

# Illustrative reference values (the case data does not include them; see DECISIONES.md).
REFERENCE_PRICES = {"Gasolina Corriente": 16000, "Gasolina Extra": 21250, "Diesel": 11100, "GNV": 3200}
ZONE_KM_PER_SERVICE = {"CARIBE COR": 18.0}
DEFAULT_KM_PER_SERVICE = 18.0
PROVIDER_LABELS = {"terpel": "Terpel", "gopass": "GoPass"}
PROVIDER_METHODS = {"terpel": "chip", "gopass": "tarjeta"}
FUEL_TYPE_LABELS = {"gasoline": "Gasolina", "dual_fuel": "Bicombustible", "diesel": "Diésel", "cng": "Gas"}


def tank_of(product: str) -> str:
    return "cng" if (product or "").strip().upper() in ("GNV", "GAS") else "liquid"


def reference_price(product: str) -> float:
    return REFERENCE_PRICES.get(product, REFERENCE_PRICES["Gasolina Corriente"])


def km_per_service(zone: str) -> float:
    return ZONE_KM_PER_SERVICE.get(zone, DEFAULT_KM_PER_SERVICE)


def vehicle_by_ref(db: Session, ref: str) -> Vehicle:
    """Accepts the internal id, the public UUID, the code (VEH160) or the plate."""
    query = select(Vehicle)
    if ref.isdigit():
        vehicle = db.get(Vehicle, int(ref))
    else:
        value = ref.strip().upper()
        vehicle = db.scalar(query.where((Vehicle.code == value) | (Vehicle.plate == value)
                                        | (Vehicle.public_id == ref.strip().lower())))
    if vehicle is None:
        raise ApiError(404, f"No existe el vehículo {ref}.", "vehicle_not_found")
    return vehicle


def money_short(amount: float) -> str:
    """4129120 -> '$4,1 M'."""
    if amount >= 1_000_000:
        return f"${fmt_num(amount / 1_000_000, 1)} M"
    return fmt_cop(amount)


def efficiency_summary(vehicle: Vehicle, rules: dict[str, ActiveRule] | None = None) -> dict:
    median = GROUP_MEDIANS.get(vehicle.group)
    low_factor = rules["V01"].params["factor"] if rules else CATALOG_BY_CODE["V01"].params["factor"]
    high_factor = rules["V02"].params["factor"] if rules else CATALOG_BY_CODE["V02"].params["factor"]
    value = vehicle.reference_efficiency
    ratio = (value / median) if value and median else None
    if ratio is None:
        status = "inconclusive"
    elif ratio < low_factor:
        status = "low"
    elif ratio > high_factor:
        status = "high"
    else:
        status = "normal"
    return {
        "value": value,
        "unit": vehicle.efficiency_unit,
        "group": vehicle.group,
        "group_label": GROUP_LABELS.get(vehicle.group, vehicle.group),
        "group_median": median,
        "ratio_to_group": round(ratio, 3) if ratio else None,
        "difference_pct": round(ratio - 1, 4) if ratio else None,
        "low_limit": round(median * low_factor + 1e-9, 1) if median else None,  # 41.8 x 0.75 = 31.35 -> 31.4
        "high_limit": round(median * high_factor + 1e-9, 1) if median else None,
        "status": status,
        "status_label": {"low": "Bajo", "high": "Alto", "normal": "En su rango",
                         "inconclusive": "No concluyente"}[status],
        "source": "Análisis de 90 días (calculado en la semilla)",
    }


def vehicle_flags(vehicle: Vehicle, rules: dict[str, ActiveRule] | None = None) -> list[dict]:
    """Vehicle rules V01..V08 that apply, with their points and a readable explanation."""
    stats = vehicle.stats or {}
    eff = efficiency_summary(vehicle, rules)
    unit = vehicle.efficiency_unit
    out = []
    for code in vehicle.flags or []:
        rule_def = CATALOG_BY_CODE[code]
        points = rules[code].points if rules else rule_def.points
        version = rules[code].version if rules else 1
        text = rule_def.threshold_text
        if code == "V01" and eff["value"]:
            text = (f"Rinde {fmt_num(eff['value'], 1)} {unit} frente a la mediana de su grupo, {fmt_num(eff['group_median'], 1)} "
                    f"({fmt_pct(abs(eff['difference_pct']))} menos); el límite es {fmt_num(eff['low_limit'], 1)}")
        elif code == "V02" and eff["value"]:
            text = (f"Rinde {fmt_num(eff['value'], 1)} {unit}, {fmt_pct(eff['difference_pct'])} más que la mediana de su grupo "
                    f"({fmt_num(eff['group_median'], 1)}): sugiere combustible no registrado en estos proveedores")
        elif code == "V03":
            text = (f"Sus últimas 8 cargas rinden {fmt_pct(abs(stats.get('recent_drop', -0.31)))} menos que su propio "
                    "rendimiento: empeoró hace poco y puede ser una falla")
        elif code == "V04":
            text = (f"Odómetro congelado en el {fmt_pct(stats.get('frozen_share', 0.3))} de sus tanqueos: "
                    "sin control de km, la foto del tablero es obligatoria")
        elif code == "V05":
            text = (f"{stats.get('refuels_90d', 0)} tanqueos por {money_short(stats.get('amount_90d', 0))} "
                    "sin un solo servicio en EOM en los 90 días")
        elif code == "V06":
            text = "Carga con Terpel y con GoPass: ningún proveedor ve todo su consumo"
        elif code == "V07":
            text = (f"{fmt_pct(stats.get('odometer_issue_share', 0.1))} de sus tanqueos sin odómetro o con lectura atípica: "
                    "sus km y su rendimiento pierden precisión")
        elif code == "V08":
            text = f"{fmt_pct(stats.get('alert_share', 0.2))} de sus tanqueos con al menos una alerta"
        out.append({"code": code, "name": rule_def.name, "points": points, "explanation": text, "version": version})
    return out


def vehicle_payload(vehicle: Vehicle, rules: dict[str, ActiveRule] | None = None) -> dict:
    return {
        "id": vehicle.id,
        "public_id": vehicle.public_id,
        "code": vehicle.code,
        "plate": vehicle.plate,
        "fuel_type": vehicle.fuel_type,
        "fuel_type_label": FUEL_TYPE_LABELS.get(vehicle.fuel_type, vehicle.fuel_type),
        "group": vehicle.group,
        "group_label": GROUP_LABELS.get(vehicle.group, vehicle.group),
        "product": vehicle.product,
        "unit": vehicle.unit,
        "tank_capacity": vehicle.tank_capacity,
        "reference_efficiency": vehicle.reference_efficiency,
        "efficiency_unit": vehicle.efficiency_unit,
        "zone": vehicle.zone,
        "department": vehicle.department,
        "provider": vehicle.provider,
        "provider_label": PROVIDER_LABELS.get(vehicle.provider, vehicle.provider),
        "payment_method": PROVIDER_METHODS.get(vehicle.provider, "chip"),
        "flags": [f["code"] for f in vehicle_flags(vehicle, rules)],
    }


def transaction_payload(tx: ProviderTransaction, km_since_previous: int | None = None) -> dict:
    return {
        "id": tx.id,
        "provider": tx.provider,
        "provider_label": PROVIDER_LABELS.get(tx.provider, tx.provider),
        "external_id": tx.external_id,
        "timestamp": iso(tx.timestamp),
        "station": tx.station,
        "region": tx.region,
        "product": tx.product,
        "tank": tx.tank,
        "quantity": tx.quantity,
        "unit": tx.unit,
        "unit_price": tx.unit_price,
        "amount": tx.amount,
        "odometer": tx.odometer,
        "km_since_previous": km_since_previous,
        "sale_type": tx.sale_type,
        "source": tx.source,
    }


def service_payload(service: EomService, reference: datetime | None = None) -> dict:
    pending = reference is not None and to_local(service.start) >= to_local(reference)
    return {
        "id": service.id,
        "external_id": service.external_id,
        "start": iso(service.start),
        "end": iso(service.end),
        "origin": service.origin,
        "destination": service.destination,
        "zone": service.zone,
        "department": service.department,
        "km": service.km,
        "status": "pending" if pending else "done",
        "status_label": "Pendiente" if pending else "Cumplido",
    }


def transactions_before(db: Session, vehicle_id: int, moment: datetime) -> list[ProviderTransaction]:
    return list(db.scalars(select(ProviderTransaction)
                           .where(ProviderTransaction.vehicle_id == vehicle_id, ProviderTransaction.timestamp < moment)
                           .order_by(ProviderTransaction.timestamp, ProviderTransaction.id)).all())


def refuel_context(db: Session, vehicle: Vehicle, moment: datetime, odometer: int | None, tank: str) -> dict:
    """What the single ledger knows about the vehicle right before `moment`."""
    txs = transactions_before(db, vehicle.id, moment)
    same = [t for t in txs if t.tank == tank]
    last_any = txs[-1] if txs else None
    last_same = same[-1] if same else None
    last_with_odo = next((t for t in reversed(txs) if t.odometer is not None), None)
    last_same_with_odo = next((t for t in reversed(same) if t.odometer is not None), None)
    loads = [t.quantity for t in same if t.quantity and t.quantity > 0]
    since = moment - timedelta(hours=24)
    ctx = {
        "last_refuel": None,
        "last_refuel_same_fuel": transaction_payload(last_same) if last_same else None,
        "last_valid_odometer": last_with_odo.odometer if last_with_odo else None,
        "hours_since_last_reading": None,
        "km_since_prev": None,
        "hours_since_prev": None,
        "km_last_same": None,
        "last_load_same": last_same.quantity if last_same else None,
        "median_load": round(typical_load(loads), 2) if loads else None,
        "largest_loads": round(quantile(loads, 0.95), 2) if loads else None,
        "loads_24h": 1 + sum(1 for t in same if t.timestamp >= since),
        "refuels_in_ledger": len(txs),
        "providers": sorted({t.provider for t in txs}),
    }
    if last_any:
        hours = (moment - last_any.timestamp).total_seconds() / 3600
        ctx["last_refuel"] = {**transaction_payload(last_any), "hours_ago": round(hours, 1)}
        ctx["hours_since_prev"] = round(hours, 2)
    if last_with_odo:
        ctx["hours_since_last_reading"] = round((moment - last_with_odo.timestamp).total_seconds() / 3600, 2)
        if odometer is not None:
            ctx["km_since_prev"] = odometer - last_with_odo.odometer
    if last_same_with_odo and odometer is not None:
        ctx["km_last_same"] = odometer - last_same_with_odo.odometer
    return ctx


def services_context(db: Session, vehicle: Vehicle, moment: datetime, window_h: int = 24, night_window_h: int = 3) -> dict:
    """EOM services around `moment`: the day, the pending ones and the counts the rules need."""
    moment = to_local(moment)
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    in_eom = bool(db.scalar(select(func.count()).select_from(EomService).where(EomService.vehicle_id == vehicle.id)))

    def count(hours: int) -> int:
        return db.scalar(select(func.count()).select_from(EomService).where(
            EomService.vehicle_id == vehicle.id,
            EomService.start >= moment - timedelta(hours=hours),
            EomService.start <= moment + timedelta(hours=hours))) or 0

    today_services = list(db.scalars(select(EomService).where(
        EomService.vehicle_id == vehicle.id, EomService.start >= day_start, EomService.start < day_end)
        .order_by(EomService.start)).all())
    pending = [s for s in today_services if to_local(s.start) >= moment]
    return {
        "vehicle_in_eom": in_eom,
        "services_24h": count(window_h),
        "services_3h": count(night_window_h),
        "today": [service_payload(s, moment) for s in today_services],
        "today_count": len(today_services),
        "pending_count": len(pending),
        "next_service": service_payload(pending[0], moment) if pending else None,
        "km_per_service": km_per_service(vehicle.zone),
        "zone": vehicle.zone,
    }


def provider_comparison(txs: list[ProviderTransaction], vehicle: Vehicle) -> dict | None:
    """Why a single ledger: what GoPass computes alone versus the two providers together.

    GoPass divides the km since ITS previous refuel by ITS own gallons; it cannot see the loads
    the vehicle made with Terpel in between.
    """
    gopass = [t for t in txs if t.provider == "gopass" and t.odometer is not None]
    if len(gopass) < 2 or not any(t.provider == "terpel" for t in txs):
        return None
    previous, last = gopass[-2], gopass[-1]
    km = last.odometer - previous.odometer
    hidden = [t for t in txs if t.provider == "terpel" and previous.timestamp < t.timestamp < last.timestamp]
    hidden_gas = sum(t.quantity for t in hidden if t.tank == "cng")
    hidden_liquid = sum(t.quantity for t in hidden if t.tank == "liquid")
    alone = km / last.quantity if last.quantity else None
    gal_eq = last.quantity + hidden_liquid + hidden_gas / CNG_M3_PER_GALLON
    unified = km / gal_eq if gal_eq else None
    gas_loads = sum(1 for t in hidden if t.tank == "cng")
    return {
        "from": iso(previous.timestamp),
        "to": iso(last.timestamp),
        "km": km,
        "gopass_only": {"gallons": last.quantity, "efficiency": round(alone, 1) if alone else None, "unit": "km/gal"},
        "single_ledger": {
            "gallons": round(last.quantity + hidden_liquid, 3), "cng_m3": round(hidden_gas, 1),
            "gallon_equivalent": round(gal_eq, 2), "efficiency": round(unified, 1) if unified else None,
            "unit": "km/gal-eq", "cng_m3_per_gallon": CNG_M3_PER_GALLON,
        },
        "hidden_loads": len(hidden),
        "hidden_cng_loads": gas_loads,
        "explanation": (f"GoPass solo calcula {fmt_int(km)} km ÷ {fmt_num(last.quantity, 3)} gal = {fmt_int(alone)} km por galón, "
                        f"porque no ve sus {gas_loads} cargas de gas en Terpel ({fmt_num(hidden_gas, 1)} m³). "
                        f"En el libro único son {fmt_num(unified, 1)} km por galón equivalente."),
    }


def ledger_payload(db: Session, vehicle: Vehicle, rules: dict[str, ActiveRule]) -> dict:
    txs = list(db.scalars(select(ProviderTransaction).where(ProviderTransaction.vehicle_id == vehicle.id)
                          .order_by(ProviderTransaction.timestamp, ProviderTransaction.id)).all())
    entries, last_odo = [], None
    for tx in txs:
        km = tx.odometer - last_odo if tx.odometer is not None and last_odo is not None else None
        entries.append(transaction_payload(tx, km))
        if tx.odometer is not None:
            last_odo = tx.odometer
    by_provider = {}
    for tx in txs:
        item = by_provider.setdefault(tx.provider, {"provider": tx.provider,
                                                    "provider_label": PROVIDER_LABELS.get(tx.provider, tx.provider),
                                                    "refuels": 0, "amount": 0})
        item["refuels"] += 1
        item["amount"] += tx.amount
    services_90d = db.scalar(select(func.count()).select_from(EomService).where(EomService.vehicle_id == vehicle.id)) or 0
    return {
        "vehicle": vehicle_payload(vehicle, rules),
        "efficiency": efficiency_summary(vehicle, rules),
        "flags": vehicle_flags(vehicle, rules),
        "stats": vehicle.stats or {},
        "summary": {
            "refuels": len(txs),
            "amount": sum(t.amount for t in txs),
            "providers": list(by_provider.values()),
            "first": iso(txs[0].timestamp) if txs else None,
            "last": iso(txs[-1].timestamp) if txs else None,
            "eom_services_loaded": services_90d,
        },
        "comparison": provider_comparison(txs, vehicle),
        "entries": list(reversed(entries)),  # newest first
    }


__all__ = ["REFERENCE_PRICES", "PROVIDER_LABELS", "PROVIDER_METHODS", "EFFICIENCY_UNITS", "tank_of",
           "reference_price", "km_per_service", "vehicle_by_ref", "money_short", "efficiency_summary",
           "vehicle_flags", "vehicle_payload", "transaction_payload", "service_payload", "refuel_context",
           "services_context", "provider_comparison", "ledger_payload", "transactions_before"]
