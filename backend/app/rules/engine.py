"""Rules engine in pure Python (no pandas, no database).

`evaluate_request` applies R01 to R10 to the context of ONE request, exactly as
`fuel/rules.py` evaluates a one-row DataFrame. `evaluate_transaction` applies R11 to R14 at
reconciliation. Thresholds and points come from the current `rule_version` rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from app.rules import odometer as odo
from app.rules.catalog import CATALOG, TREATMENT_LABELS, RuleDef
from app.timeutil import fmt_cop, fmt_int, fmt_num, fmt_unit

TANK_NAMES = {"cng": "GNV", "liquid": "combustible líquido"}


@dataclass(frozen=True)
class ActiveRule:
    code: str
    name: str
    stage: str
    treatment: str
    points: int
    params: dict = field(default_factory=dict)
    version: int = 1
    threshold_text: str = ""


def default_rules() -> dict[str, ActiveRule]:
    """Initial catalog as active rules (used by tests and as a fallback)."""
    return {r.code: active_from_def(r) for r in CATALOG}


def active_from_def(rule: RuleDef, params: dict | None = None, points: int | None = None,
                    version: int = 1) -> ActiveRule:
    merged = {**rule.params, **(params or {})}
    return ActiveRule(rule.code, rule.name, rule.stage, rule.treatment,
                      rule.points if points is None else points, merged, version, rule.threshold_text)


def quantile(values: list[float], q: float) -> float | None:
    """Linear-interpolation quantile (same as the pandas default)."""
    if not values:
        return None
    data = sorted(values)
    pos = (len(data) - 1) * q
    low = int(pos)
    high = min(low + 1, len(data) - 1)
    return data[low] + (data[high] - data[low]) * (pos - low)


def typical_load(values: list[float]) -> float | None:
    return median(values) if values else None


def _check(rule: ActiveRule, triggered: bool, explanation: str, evaluated: bool = True) -> dict:
    return {
        "code": rule.code,
        "name": rule.name,
        "points": rule.points if triggered else 0,
        "rule_points": rule.points,
        "triggered": bool(triggered),
        "evaluated": evaluated,
        "explanation": explanation,
        "threshold": rule.threshold_text,
        "treatment": rule.treatment,
        "treatment_label": TREATMENT_LABELS.get(rule.treatment, rule.treatment),
        "version": rule.version,
    }


def evaluate_request(ctx: dict, rules: dict[str, ActiveRule]) -> list[dict]:
    """Returns one check per rule R01..R10 (triggered or not) with its explanation.

    Context keys: odometer, odometer_reported, odometer_error, odometer_proposed,
    last_valid_odometer, km_since_prev, hours_since_prev, tank, unit, load, km_last_same,
    median_load, largest_loads, loads_24h, frozen_odometer, vehicle_in_eom, services_24h,
    services_3h, hour, time_text.
    """
    checks: list[dict] = []
    unit = fmt_unit(ctx.get("unit") or "gal")
    tank = ctx.get("tank") or "liquid"
    tank_name = TANK_NAMES.get(tank, tank)
    load = ctx.get("load")
    error = ctx.get("odometer_error")
    last_valid = ctx.get("last_valid_odometer")

    # R01 - no odometer reading.
    r = rules["R01"]
    missing = ctx.get("odometer") is None
    checks.append(_check(r, missing, "no se registró odómetro" if missing
                         else f"odómetro registrado: {fmt_int(ctx.get('odometer'))} km"))

    # R02 - atypical reading explained by one digit.
    r = rules["R02"]
    typo = error in odo.TYPO_TYPES
    if typo:
        text = (f"leyó {fmt_int(ctx.get('odometer_reported'))} km ({odo.ERROR_LABELS[error]}); "
                f"última lectura válida: {fmt_int(last_valid)} km; "
                f"valor corregido: {fmt_int(ctx.get('odometer_proposed'))} km")
    else:
        text = "la lectura no tiene patrón de error de digitación"
    checks.append(_check(r, typo, text))

    # R03 - atypical reading without explanation.
    r = rules["R03"]
    inconsistent = error in (odo.INCONSISTENT, odo.NO_REFERENCE)
    if inconsistent:
        text = (f"reportó {fmt_int(ctx.get('odometer_reported'))} km; "
                f"última lectura válida: {fmt_int(last_valid)} km")
    else:
        text = "la lectura es coherente con el último registro"
    checks.append(_check(r, inconsistent, text))

    # R04 - mileage jump since the last refuel.
    r = rules["R04"]
    km_prev, hours_prev = ctx.get("km_since_prev"), ctx.get("hours_since_prev")
    jump = (km_prev is not None and hours_prev is not None and km_prev > r.params["max_jump_km"]
            and hours_prev <= r.params["max_days"] * 24)
    if jump:
        text = (f"{fmt_int(km_prev)} km en {fmt_num(hours_prev / 24, 1)} días: "
                "posible tanqueo no registrado en estos proveedores")
    elif km_prev is not None:
        text = f"{fmt_int(km_prev)} km desde el último tanqueo"
    else:
        text = "sin km para comparar"
    checks.append(_check(r, jump, text))

    # R05 - refill without travel (per tank).
    r = rules["R05"]
    km_same, typical = ctx.get("km_last_same"), ctx.get("median_load")
    refill = (load is not None and load > 0 and km_same is not None and 0 <= km_same < r.params["min_km"]
              and typical is not None and load >= r.params["load_fraction"] * typical
              and not ctx.get("frozen_odometer"))
    if refill:
        text = (f"cargó {fmt_num(load, 1)} {unit} de {tank_name} con {fmt_int(km_same)} km desde su carga anterior "
                f"(típica {fmt_num(typical, 1)} {unit})")
    elif km_same is not None:
        text = f"{fmt_int(km_same)} km desde su carga anterior del mismo combustible"
    else:
        text = "sin carga anterior del mismo combustible para comparar"
    checks.append(_check(r, refill, text))

    # R06 - too many loads in 24 h (per tank).
    r = rules["R06"]
    limit = r.params["max_cng_24h"] if tank == "cng" else r.params["max_liquid_24h"]
    n24 = ctx.get("loads_24h") or 0
    frequent = n24 > limit
    checks.append(_check(r, frequent, f"{n24} carga{'' if n24 == 1 else 's'} de {tank_name} en 24 h"
                         + ("" if frequent else f" (límite {limit})")))

    # R07 - load above its typical capacity (per tank).
    r = rules["R07"]
    largest = ctx.get("largest_loads")
    over = load is not None and largest is not None and load > r.params["factor"] * largest
    if over:
        text = (f"cargó {fmt_num(load, 1)} {unit} de {tank_name}; "
                f"sus cargas más grandes son de {fmt_num(largest, 1)} {unit}")
    elif largest is not None and load is not None:
        text = f"{fmt_num(load, 1)} {unit} frente a cargas más grandes de {fmt_num(largest, 1)} {unit}"
    else:
        text = "sin historial de cargas para comparar"
    checks.append(_check(r, over, text))

    # R08 - no EOM services with travel in the window (only if the vehicle exists in EOM).
    r = rules["R08"]
    in_eom = bool(ctx.get("vehicle_in_eom"))
    window = int(r.params["window_h"])
    no_service = in_eom and (ctx.get("services_24h") or 0) == 0
    if no_service:
        text = f"sin servicios con desplazamiento {window} h antes ni después"
    elif not in_eom:
        text = "el vehículo no opera en EOM: aplica la regla por vehículo V05"
    else:
        text = f"{ctx.get('services_24h')} servicios en ±{window} h"
    checks.append(_check(r, no_service, text))

    # R09 - night refuel without a nearby service.
    r = rules["R09"]
    hour = ctx.get("hour")
    night = hour is not None and (hour >= r.params["night_start_h"] or hour < r.params["night_end_h"])
    nocturnal = night and in_eom and (ctx.get("services_3h") or 0) == 0
    if nocturnal:
        text = f"tanqueo a las {ctx.get('time_text')} sin servicios cercanos"
    elif night:
        text = f"tanqueo a las {ctx.get('time_text')} con servicio cercano o sin operación en EOM"
    else:
        text = f"solicitud a las {ctx.get('time_text')}, fuera de la franja nocturna"
    checks.append(_check(r, nocturnal, text))

    # R10 - station outside the operation zone: needs the real station, known at reconciliation.
    r = rules["R10"]
    checks.append(_check(r, False, "se evalúa con la estación real, cuando llega la transacción del proveedor",
                         evaluated=False))
    return checks


def evaluate_transaction(tx: dict, rules: dict[str, ActiveRule]) -> list[dict]:
    """R11 to R14 for one provider transaction.

    Keys: sale_type, amount, split_count, split_amount, split_minutes, price_deviation.
    """
    out: list[dict] = []
    r = rules["R11"]
    sale_type = (tx.get("sale_type") or "").strip()
    special = sale_type.lower() not in ("en línea", "en linea", "")
    if special:
        out.append(_check(r, True, f"tipo de venta: {sale_type}"))
    r = rules["R12"]
    if (tx.get("split_count") or 1) > 1 and (tx.get("split_amount") or 0) > r.params["amount_cop"]:
        out.append(_check(r, True, f"{tx['split_count']} transacciones por {fmt_cop(tx['split_amount'])} "
                                   f"en {int(round(tx.get('split_minutes') or 0))} min"))
    r = rules["R13"]
    if tx.get("amount") is not None and tx["amount"] < r.params["amount_cop"]:
        out.append(_check(r, True, f"transacción de {fmt_cop(tx['amount'])}, menos de {fmt_cop(r.params['amount_cop'])}"))
    r = rules["R14"]
    deviation = tx.get("price_deviation")
    if deviation is not None and abs(deviation) > r.params["max_deviation"]:
        sign = "+" if deviation > 0 else "-"
        out.append(_check(r, True, f"precio {sign}{fmt_num(abs(deviation) * 100, 0)} % frente a la mediana de la estación"))
    return out


def summarize(checks: list[dict]) -> tuple[int, list[dict]]:
    """Total points and the list of triggered rules (the reasons shown to the technician)."""
    reasons = [c for c in checks if c["triggered"]]
    return sum(c["points"] for c in reasons), reasons
