"""Recommended amount: the formula of the current instruction sheet, made explicit.

available   = level read from the photo x tank capacity
pending     = EOM services until the end of the shift x typical km per service of the zone
to load     = min(capacity, pending / efficiency + half-tank reserve) - available
amount      = to load x reference price, rounded to the nearest $10,000 and limited by the cap
cap         = registered capacity or, without it, its largest loads (as in R07)
cross-check = consumption since the last refuel (km / efficiency) against the level read
"""
from __future__ import annotations

from app.timeutil import fmt_cop, fmt_int, fmt_num, fmt_pct, fmt_unit

ROUNDING_COP = 10_000
RESERVE_FRACTION = 0.5          # half tank: the minimum set by the instruction sheet
CROSS_CHECK_TOLERANCE = 0.15    # of the capacity: a gauge is not a precise instrument


def round_to_10k(value: float) -> int:
    """Nearest multiple of $10,000 (half rounds up)."""
    return int((value + ROUNDING_COP / 2) // ROUNDING_COP) * ROUNDING_COP


def _step(key: str, label: str, formula: str, result: float | int | None, display: str, unit: str = "") -> dict:
    return {"key": key, "label": label, "formula": formula, "result": result, "display": display, "unit": unit}


def compute_amount(*, level: float | None, capacity: float | None, largest_loads: float | None,
                   pending_services: int, km_per_service: float, efficiency: float | None,
                   price: float, unit: str = "gal", efficiency_unit: str = "km/gal",
                   last_load: float | None = None, km_since_last: float | None = None) -> dict:
    u = fmt_unit(unit)
    cap_quantity = capacity if capacity else largest_loads
    cap_source = "capacidad registrada" if capacity else "sus cargas más grandes"
    result: dict = {
        "computable": False, "needs_refuel": None, "quantity": None, "unit": unit,
        "raw_amount": None, "rounded_amount": None, "cap_amount": None, "amount": None,
        "price": price, "steps": [], "cross_check": None, "note": None,
    }
    if level is None or not cap_quantity or not efficiency:
        missing = "el nivel de combustible" if level is None else "la capacidad o el rendimiento del vehículo"
        result["note"] = f"No se puede calcular el valor: falta {missing}. El técnico lo define."
        return result

    available = level * cap_quantity
    pending_km = pending_services * km_per_service
    route_fuel = pending_km / efficiency
    reserve = RESERVE_FRACTION * cap_quantity
    need = min(cap_quantity, route_fuel + reserve)
    to_load = need - available
    cap_amount = int(cap_quantity * price // ROUNDING_COP) * ROUNDING_COP

    steps = [
        _step("available", "Disponible", f"{fmt_pct(level)} de nivel × {fmt_num(cap_quantity, 1)} {u} de capacidad",
              round(available, 2), f"{fmt_num(available, 2)} {u}", unit),
        _step("pending_route", "Ruta pendiente",
              f"{pending_services} servicios en EOM × {fmt_num(km_per_service, 0)} km típicos por servicio",
              round(pending_km, 1), f"{fmt_int(pending_km)} km", "km"),
        _step("route_fuel", "Combustible para la ruta",
              f"{fmt_int(pending_km)} km ÷ {fmt_num(efficiency, 1)} {efficiency_unit}",
              round(route_fuel, 2), f"{fmt_num(route_fuel, 2)} {u}", unit),
        _step("reserve", "Reserva de ½ tanque", f"½ × {fmt_num(cap_quantity, 1)} {u}",
              round(reserve, 2), f"{fmt_num(reserve, 2)} {u}", unit),
        _step("need", "Necesidad",
              f"mín({fmt_num(cap_quantity, 1)}; {fmt_num(route_fuel, 2)} + {fmt_num(reserve, 2)}) {u}",
              round(need, 2), f"{fmt_num(need, 2)} {u}", unit),
        _step("to_load", "A cargar", f"{fmt_num(need, 2)} − {fmt_num(available, 2)} {u}",
              round(to_load, 2), f"{fmt_num(to_load, 2)} {u}", unit),
    ]
    result.update(computable=True, quantity=round(to_load, 3), cap_amount=cap_amount)

    if to_load <= 0:
        steps.append(_step("amount", "Valor sugerido", "A cargar es 0 o menos: no necesita tanquear ahora",
                           0, fmt_cop(0), "COP"))
        result.update(needs_refuel=False, raw_amount=0, rounded_amount=0, amount=0, steps=steps)
    else:
        raw = to_load * price
        rounded = round_to_10k(raw)
        final = min(rounded, cap_amount)
        steps += [
            _step("raw_amount", "Valor", f"{fmt_num(to_load, 2)} {u} × {fmt_cop(price)} de referencia",
                  int(round(raw)), fmt_cop(raw), "COP"),
            _step("rounded_amount", "Redondeo", "al múltiplo de $10.000 más cercano", rounded, fmt_cop(rounded), "COP"),
            _step("cap", "Tope del vehículo",
                  f"{fmt_num(cap_quantity, 1)} {u} ({cap_source}) × {fmt_cop(price)}, hacia abajo al múltiplo de $10.000", cap_amount, fmt_cop(cap_amount), "COP"),
            _step("amount", "Valor sugerido", f"mín({fmt_cop(rounded)}; {fmt_cop(cap_amount)})",
                  final, fmt_cop(final), "COP"),
        ]
        result.update(needs_refuel=True, raw_amount=int(round(raw)), rounded_amount=rounded, amount=final, steps=steps)

    if km_since_last is not None and km_since_last >= 0:
        consumption = km_since_last / efficiency
        tolerance = CROSS_CHECK_TOLERANCE * cap_quantity
        expected_max = max(cap_quantity - consumption, 0.0)
        expected_min = max((last_load or 0.0) - consumption, 0.0)
        consistent = (expected_min - tolerance) <= available <= (expected_max + tolerance)
        if consistent:
            text = (f"Consumo desde el último tanqueo: {fmt_int(km_since_last)} km ÷ {fmt_num(efficiency, 1)} "
                    f"{efficiency_unit} = {fmt_num(consumption, 2)} {u}. Cuadra con el nivel leído.")
        elif available > expected_max + tolerance:
            text = (f"El nivel leído ({fmt_num(available, 1)} {u}) es mayor de lo posible: con {fmt_int(km_since_last)} km "
                    f"recorridos consumió {fmt_num(consumption, 1)} {u} y no podría tener más de {fmt_num(expected_max, 1)} {u}.")
        else:
            text = (f"El nivel leído ({fmt_num(available, 1)} {u}) es menor de lo esperado: cargó {fmt_num(last_load or 0, 1)} {u} "
                    f"y en {fmt_int(km_since_last)} km consumió {fmt_num(consumption, 1)} {u}; "
                    f"debería tener al menos {fmt_num(expected_min, 1)} {u}.")
        result["cross_check"] = {
            "km_since_last": km_since_last, "consumption": round(consumption, 2),
            "expected_min": round(expected_min, 2), "expected_max": round(expected_max, 2),
            "available": round(available, 2), "consistent": consistent, "unit": unit, "explanation": text,
        }
    return result
