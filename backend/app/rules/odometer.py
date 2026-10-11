"""Odometer validation: is the reading physically possible and, if not, is it a typing error?

Port of `classify_error` from the analysis code (`fuel/odometer.py`), without pandas. It also
returns the corrected value so the assistant can propose it to the driver (R02).
"""
from __future__ import annotations

import math

EXTRA_DIGIT = "extra_digit"
MISSING_DIGIT = "missing_digit"
CHANGED_DIGIT = "changed_digit"
SWAPPED_DIGITS = "swapped_digits"
INCONSISTENT = "inconsistent"
NO_REFERENCE = "no_reference"

TYPO_TYPES = (EXTRA_DIGIT, MISSING_DIGIT, CHANGED_DIGIT, SWAPPED_DIGITS)

ERROR_LABELS = {
    EXTRA_DIGIT: "dígito de más",
    MISSING_DIGIT: "dígito faltante",
    CHANGED_DIGIT: "dígito cambiado",
    SWAPPED_DIGITS: "dígitos invertidos",
    INCONSISTENT: "inconsistente",
    NO_REFERENCE: "sin referencia",
}


def _candidates(reported: int) -> dict[str, list[str]]:
    s, digits = str(int(reported)), "0123456789"
    return {
        EXTRA_DIGIT: [s[:p] + s[p + 1:] for p in range(len(s))],
        MISSING_DIGIT: [s[:p] + d + s[p:] for p in range(len(s) + 1) for d in digits],
        CHANGED_DIGIT: [s[:p] + d + s[p + 1:] for p in range(len(s)) for d in digits if d != s[p]],
        SWAPPED_DIGITS: [s[:p] + s[p + 1] + s[p] + s[p + 2:] for p in range(len(s) - 1)],
    }


def classify_error(reported: float | None, minimum: float | None, maximum: float | None,
                   tolerance: float = 20.0) -> tuple[str, int | None]:
    """Returns (error_type, corrected_value).

    The fix must land between the neighboring valid readings; with only one of them, the
    closest fix wins. Without a fix the reading is "inconsistent" and a person reviews it.
    """
    if reported is None:
        return ("no_data", None)
    lo = (-math.inf if minimum is None else minimum) - tolerance
    hi = (math.inf if maximum is None else maximum) + tolerance
    if math.isinf(lo) and math.isinf(hi):
        return (NO_REFERENCE, None)
    fits: dict[str, list[int]] = {}
    for kind, values in _candidates(int(reported)).items():
        ok = [int(c) for c in values if c and c[0] != "0" and lo <= int(c) <= hi]
        if ok:
            fits[kind] = ok
    if not fits:
        return (INCONSISTENT, None)
    if math.isinf(lo) or math.isinf(hi):  # a single valid neighbor
        neighbor = maximum if math.isinf(lo) else minimum
        kind = min(fits, key=lambda k: min(abs(x - neighbor) for x in fits[k]))
        return (kind, min(fits[kind], key=lambda x: abs(x - neighbor)))
    kind = next(iter(fits))
    anchor = minimum if minimum is not None else maximum
    return (kind, min(fits[kind], key=lambda x: abs(x - anchor)))


def check_reading(reported: int | None, last_valid: int | None, hours_since_last: float | None, *,
                  rollback_km: float = 50.0, max_km_per_day: float = 1200.0,
                  typo_tolerance_km: float = 20.0) -> dict:
    """Validates a new reading against the last valid one of the single ledger.

    A reading is atypical when reaching it would require the odometer to roll back more than
    `rollback_km` or to advance faster than `max_km_per_day`.
    """
    result = {"status": "valid", "error_type": None, "proposed": None,
              "expected_min": last_valid, "expected_max": None}
    if reported is None:
        result["status"] = "missing"
        return result
    if last_valid is None:
        return result
    days = max((hours_since_last or 0.0) / 24.0, 1.0 / 24.0)
    expected_max = last_valid + max_km_per_day * days + rollback_km
    result["expected_max"] = int(round(expected_max))
    if last_valid - rollback_km <= reported <= expected_max:
        return result
    kind, corrected = classify_error(reported, last_valid, expected_max, typo_tolerance_km)
    result.update(status="atypical", error_type=kind, proposed=corrected)
    return result


def describe_fix(reported: int, corrected: int, error_type: str) -> str:
    """Short explanation for the driver, e.g. 'el 3 quedó como 2'."""
    a, b = str(reported), str(corrected)
    if error_type == CHANGED_DIGIT and len(a) == len(b):
        for x, y in zip(a, b):
            if x != y:
                return f"el {y} quedó como {x}"
    if error_type == EXTRA_DIGIT:
        return "sobra un dígito"
    if error_type == MISSING_DIGIT:
        return "falta un dígito"
    if error_type == SWAPPED_DIGITS:
        return "dos dígitos quedaron invertidos"
    return ERROR_LABELS.get(error_type, "no cuadra con el último registro")
