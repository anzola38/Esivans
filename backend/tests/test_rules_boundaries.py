"""Rules engine at its thresholds: each rule R01..R14 with a case that triggers it and the closest
one that does not, their points, the typing-error classification, traffic light and priority.

Thresholds are the ones of the sheet "Reglas y umbrales": 50 km, 1,200 km per day, 1,000 km in 10 days
or less, 30 km and 50 %, more than 3 liquid and more than 5 gas loads in 24 h, 1.5 times, +-24 h,
22 to 4 h with +-3 h, $150,000 in 30 min, $2,000 and +-15 %.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.ledger import service as ledger
from app.models import EomService, Vehicle
from app.rules import odometer as odo
from app.rules.catalog import CATALOG, CATALOG_BY_CODE, priority, traffic_light
from app.rules.engine import active_from_def, default_rules, evaluate_request, evaluate_transaction, summarize
from app.timeutil import at, to_local, today

from .helpers import WA, conversation, detail, play, send

RULES = default_rules()

POINTS = {"R01": 1, "R02": 1, "R03": 2, "R04": 2, "R05": 3, "R06": 2, "R07": 3, "R08": 2, "R09": 2, "R10": 3,
          "R11": 2, "R12": 2, "R13": 1, "R14": 1, "C01": 2, "C02": 2, "C03": 4,
          "V01": 3, "V02": 2, "V03": 2, "V04": 3, "V05": 3, "V06": 1, "V07": 1, "V08": 2}

THRESHOLDS = {
    "R01": {}, "R02": {"typo_tolerance_km": 20}, "R03": {"rollback_km": 50, "max_km_per_day": 1200},
    "R04": {"max_jump_km": 1000, "max_days": 10}, "R05": {"min_km": 30, "load_fraction": 0.5},
    "R06": {"max_liquid_24h": 3, "max_cng_24h": 5}, "R07": {"factor": 1.5}, "R08": {"window_h": 24},
    "R09": {"night_start_h": 22, "night_end_h": 4, "window_h": 3}, "R10": {}, "R11": {},
    "R12": {"window_min": 30, "amount_cop": 150000}, "R13": {"amount_cop": 2000},
    "R14": {"max_deviation": 0.15, "window_days": 7}, "C01": {}, "C02": {"max_difference": 0.05}, "C03": {},
    "V01": {"factor": 0.75}, "V02": {"factor": 1.40}, "V03": {"factor": 0.75, "loads": 8}, "V04": {"share": 0.30},
    "V05": {"days": 90}, "V06": {}, "V07": {"share": 0.10}, "V08": {"share": 0.20, "min_events": 10},
}


def _ctx(**changes) -> dict:
    """A request with nothing to flag: gasoline vehicle in EOM, 142 km since its last refuel."""
    base = {
        "odometer": 48352, "odometer_reported": 48352, "odometer_error": None, "odometer_proposed": None,
        "last_valid_odometer": 48210, "km_since_prev": 142, "hours_since_prev": 16.0, "tank": "liquid", "unit": "gal",
        "load": 5.0, "km_last_same": 142, "median_load": 5.0, "largest_loads": 6.0, "loads_24h": 1,
        "frozen_odometer": False, "vehicle_in_eom": True, "services_24h": 12, "services_3h": 3, "hour": 9,
        "time_text": "09:40",
    }
    base.update(changes)
    return base


def _fired(rules=RULES, **changes) -> list[str]:
    return [r["code"] for r in summarize(evaluate_request(_ctx(**changes), rules))[1]]


def _check(code: str, **changes) -> dict:
    return next(c for c in evaluate_request(_ctx(**changes), RULES) if c["code"] == code)


# ----------------------------------------------------------------------------- catalog

def test_catalog_has_the_25_rules_with_the_points_of_the_sheet():
    assert [r.code for r in CATALOG] == list(POINTS)
    assert {r.code: r.points for r in CATALOG} == POINTS


def test_catalog_thresholds_are_the_ones_of_the_sheet():
    assert {r.code: r.params for r in CATALOG} == THRESHOLDS


def test_baseline_context_triggers_nothing():
    checks = evaluate_request(_ctx(), RULES)
    assert [c["code"] for c in checks] == [f"R{n:02d}" for n in range(1, 11)]   # one check per rule R01..R10
    assert summarize(checks) == (0, [])
    assert all(c["points"] == 0 for c in checks)


@pytest.mark.parametrize("code, changes", [
    ("R01", {"odometer": None}),
    ("R02", {"odometer_error": odo.CHANGED_DIGIT, "odometer_reported": 24086, "odometer_proposed": 34086}),
    ("R03", {"odometer_error": odo.INCONSISTENT}),
    ("R04", {"km_since_prev": 1001, "hours_since_prev": 48}),
    ("R05", {"km_last_same": 10}),
    ("R06", {"loads_24h": 4}),
    ("R07", {"load": 9.5}),
    ("R08", {"services_24h": 0}),
    ("R09", {"hour": 23, "services_3h": 0}),
])
def test_each_request_rule_scores_its_own_points(code, changes):
    points, reasons = summarize(evaluate_request(_ctx(**changes), RULES))
    assert [r["code"] for r in reasons] == [code]
    assert points == POINTS[code] and reasons[0]["points"] == POINTS[code]
    assert reasons[0]["rule_points"] == POINTS[code] and reasons[0]["triggered"] is True


# ----------------------------------------------------------------------------- R01

def test_r01_fires_only_without_an_odometer_reading():
    assert _fired(odometer=None) == ["R01"]
    assert _check("R01", odometer=None)["explanation"] == "no se registró odómetro"
    assert _fired(odometer=0) == []          # a reading of 0 km is a reading
    assert _check("R01")["explanation"] == "odómetro registrado: 48.352 km"


# ----------------------------------------------------------------------------- R02 and the classification

def test_typing_error_extra_digit():
    # 339948 between the valid readings 33,940 and 33,960: only dropping one of the 9s lands in range.
    assert odo.classify_error(339948, 33940, 33960) == (odo.EXTRA_DIGIT, 33948)
    assert odo.describe_fix(339948, 33948, odo.EXTRA_DIGIT) == "sobra un dígito"


def test_typing_error_missing_digit():
    # 3948 between 33,940 and 33,960: only adding a 3 in front lands in range.
    assert odo.classify_error(3948, 33940, 33960) == (odo.MISSING_DIGIT, 33948)
    assert odo.describe_fix(3948, 33948, odo.MISSING_DIGIT) == "falta un dígito"


def test_when_several_fixes_fit_the_closest_to_the_previous_reading_wins():
    # Dropping any of the last three digits of 339480 fits (33,980, 33,940 and 33,948): 33,940 is the closest to 33,900.
    assert odo.classify_error(339480, 33900, 34100) == (odo.EXTRA_DIGIT, 33940)
    assert odo.classify_error(3398, 33900, 34100) == (odo.MISSING_DIGIT, 33898)


def test_typing_error_changed_digit_is_the_veh015_case():
    assert odo.classify_error(24086, 33948, 34152) == (odo.CHANGED_DIGIT, 34086)
    assert odo.describe_fix(24086, 34086, odo.CHANGED_DIGIT) == "el 3 quedó como 2"


def test_typing_error_swapped_digits():
    assert odo.classify_error(33498, 33940, 33960) == (odo.SWAPPED_DIGITS, 33948)
    assert odo.describe_fix(33498, 33948, odo.SWAPPED_DIGITS) == "dos dígitos quedaron invertidos"


def test_reading_without_a_one_digit_fix_is_inconsistent():
    assert odo.classify_error(51777, 33948, 35000) == (odo.INCONSISTENT, None)
    assert odo.ERROR_LABELS[odo.INCONSISTENT] == "inconsistente"


def test_classification_without_neighbors_or_without_reading():
    assert odo.classify_error(24086, None, None) == (odo.NO_REFERENCE, None)
    assert odo.classify_error(None, 33948, 34152) == ("no_data", None)


def test_with_a_single_neighbor_the_closest_fix_wins():
    # Only the previous reading is known: 34,086 (138 km ahead) beats any 6-digit candidate.
    assert odo.classify_error(24086, 33948, None) == (odo.CHANGED_DIGIT, 34086)


def test_typo_tolerance_is_20_km_around_the_valid_neighbors():
    # 24,086 -> 34,086 only fits if 34,086 <= maximum + 20.
    assert odo.classify_error(24086, 33948, 34066) == (odo.CHANGED_DIGIT, 34086)
    assert odo.classify_error(24086, 33948, 34065) == (odo.INCONSISTENT, None)


@pytest.mark.parametrize("error", odo.TYPO_TYPES)
def test_r02_fires_with_every_typing_pattern(error):
    assert _fired(odometer_error=error, odometer_reported=24086, odometer_proposed=34086,
                  last_valid_odometer=33948) == ["R02"]


def test_r02_explains_reading_last_valid_and_corrected_value():
    check = _check("R02", odometer_error=odo.CHANGED_DIGIT, odometer_reported=24086, odometer_proposed=34086,
                   last_valid_odometer=33948)
    assert check["explanation"] == ("leyó 24.086 km (dígito cambiado); última lectura válida: 33.948 km; "
                                    "valor corregido: 34.086 km")
    assert check["treatment"] == "automatic"


def test_r02_does_not_fire_with_a_valid_or_an_unexplained_reading():
    assert "R02" not in _fired(odometer_error=None)
    assert "R02" not in _fired(odometer_error=odo.INCONSISTENT)
    assert "R02" not in _fired(odometer_error=odo.NO_REFERENCE)


# ----------------------------------------------------------------------------- R03 (50 km, 1,200 km per day)

def test_rollback_of_exactly_50_km_is_valid_and_51_is_atypical():
    assert odo.check_reading(39950, 40000, hours_since_last=24)["status"] == "valid"
    assert odo.check_reading(39949, 40000, hours_since_last=24)["status"] == "atypical"


def test_advance_of_1200_km_per_day_is_valid_and_one_more_km_is_atypical():
    # One day since the last reading: 1,200 km plus the 50 km of tolerance of the analysis code.
    limit = 40000 + 1200 + 50
    at_limit = odo.check_reading(limit, 40000, hours_since_last=24)
    assert at_limit["status"] == "valid" and at_limit["expected_max"] == limit
    assert odo.check_reading(limit + 1, 40000, hours_since_last=24)["status"] == "atypical"
    # Two days double the allowance.
    assert odo.check_reading(40000 + 2400 + 50, 40000, hours_since_last=48)["status"] == "valid"
    assert odo.check_reading(40000 + 2400 + 51, 40000, hours_since_last=48)["status"] == "atypical"


def test_time_window_never_goes_below_one_hour():
    # Two refuels in the same minute: 1,200 / 24 = 50 km of advance plus 50 of tolerance.
    assert odo.check_reading(40100, 40000, hours_since_last=0)["status"] == "valid"
    assert odo.check_reading(40101, 40000, hours_since_last=0)["status"] == "atypical"
    assert odo.check_reading(40100, 40000, hours_since_last=None)["expected_max"] == 40100


def test_reading_without_history_is_valid_and_missing_reading_is_reported():
    assert odo.check_reading(123456, None, None)["status"] == "valid"
    missing = odo.check_reading(None, 40000, 24)
    assert missing["status"] == "missing" and missing["proposed"] is None


def test_unexplained_atypical_reading_is_inconsistent_and_has_no_proposal():
    result = odo.check_reading(51777, 33948, 21.6)
    assert (result["status"], result["error_type"], result["proposed"]) == ("atypical", odo.INCONSISTENT, None)


@pytest.mark.parametrize("error", [odo.INCONSISTENT, odo.NO_REFERENCE])
def test_r03_fires_with_a_reading_nobody_can_explain(error):
    points, reasons = summarize(evaluate_request(_ctx(odometer_error=error, odometer_reported=51777), RULES))
    assert [r["code"] for r in reasons] == ["R03"] and points == 2
    assert reasons[0]["explanation"] == "reportó 51.777 km; última lectura válida: 48.210 km"
    assert reasons[0]["treatment"] == "review"


def test_r03_does_not_fire_with_a_valid_reading_or_a_typo():
    assert "R03" not in _fired(odometer_error=None)
    assert "R03" not in _fired(odometer_error=odo.CHANGED_DIGIT, odometer_proposed=34086)


def test_r03_thresholds_are_parameters_of_the_check():
    assert odo.check_reading(39989, 40000, 24, rollback_km=10)["status"] == "atypical"
    assert odo.check_reading(40600, 40000, 24, max_km_per_day=500)["status"] == "atypical"
    assert odo.check_reading(40550, 40000, 24, max_km_per_day=500)["status"] == "valid"


# ----------------------------------------------------------------------------- R04 (1,000 km in 10 days or less)

def test_r04_needs_more_than_1000_km():
    assert _fired(km_since_prev=1001, hours_since_prev=48) == ["R04"]
    assert _fired(km_since_prev=1000, hours_since_prev=48) == []


def test_r04_only_within_10_days():
    assert _fired(km_since_prev=1240, hours_since_prev=240) == ["R04"]        # exactly 10 days
    assert _fired(km_since_prev=1240, hours_since_prev=240.5) == []           # just over 10 days
    assert _fired(km_since_prev=1240, hours_since_prev=None) == []
    assert _fired(km_since_prev=None, hours_since_prev=48) == []


def test_r04_explanation_has_km_and_days():
    check = _check("R04", km_since_prev=1240, hours_since_prev=74.4)
    assert check["explanation"] == "1.240 km en 3,1 días: posible tanqueo no registrado en estos proveedores"
    assert _check("R04")["explanation"] == "142 km desde el último tanqueo"


# ----------------------------------------------------------------------------- R05 (30 km and 50 %)

def test_r05_needs_less_than_30_km_since_the_same_fuel():
    assert _fired(km_last_same=29) == ["R05"]
    assert _fired(km_last_same=30) == []
    assert _fired(km_last_same=0) == ["R05"]
    assert _fired(km_last_same=-5) == []          # a rollback is an odometer problem, not a refill
    assert _fired(km_last_same=None) == []


def test_r05_needs_half_of_the_typical_load_or_more():
    assert _fired(km_last_same=10, load=2.5, median_load=5.0) == ["R05"]      # exactly 50 %
    assert _fired(km_last_same=10, load=2.49, median_load=5.0) == []
    assert _fired(km_last_same=10, load=0, median_load=5.0) == []
    assert _fired(km_last_same=10, load=None) == []
    assert _fired(km_last_same=10, median_load=None) == []


def test_r05_is_skipped_when_the_odometer_is_frozen():
    assert _fired(km_last_same=0, frozen_odometer=True) == []


def test_r05_veh199_figures_6_7_m3_with_22_km_against_9_7():
    check = _check("R05", tank="cng", unit="m3", load=6.7, km_last_same=22, median_load=9.7, largest_loads=11.8)
    assert check["triggered"] is True and check["points"] == 3
    assert check["explanation"] == "cargó 6,7 m³ de GNV con 22 km desde su carga anterior (típica 9,7 m³)"


# ----------------------------------------------------------------------------- R06 (> 3 liquid, > 5 gas in 24 h)

def test_r06_liquid_allows_3_loads_in_24_h():
    assert _fired(loads_24h=3) == []
    assert _fired(loads_24h=4) == ["R06"]
    assert _check("R06", loads_24h=3)["explanation"] == "3 cargas de combustible líquido en 24 h (límite 3)"
    assert _check("R06", loads_24h=4)["explanation"] == "4 cargas de combustible líquido en 24 h"


def test_r06_gas_allows_5_loads_in_24_h():
    gas = {"tank": "cng", "unit": "m3"}
    assert _fired(loads_24h=5, **gas) == []
    assert _fired(loads_24h=6, **gas) == ["R06"]
    assert _check("R06", loads_24h=1, **gas)["explanation"] == "1 carga de GNV en 24 h (límite 5)"


# ----------------------------------------------------------------------------- R07 (1.5 times)

def test_r07_needs_more_than_1_5_times_its_largest_loads():
    assert _fired(load=6.0, largest_loads=4.0, median_load=20) == []        # exactly 1.5 times
    assert _fired(load=6.01, largest_loads=4.0, median_load=20) == ["R07"]
    assert _fired(load=6.01, largest_loads=None) == []
    assert _fired(load=None, largest_loads=4.0) == []


def test_r07_explanation_compares_with_the_largest_loads():
    check = _check("R07", load=26.4, largest_loads=12.7)
    assert check["explanation"] == "cargó 26,4 gal de combustible líquido; sus cargas más grandes son de 12,7 gal"
    assert check["points"] == 3


# ----------------------------------------------------------------------------- R08 (+-24 h, only in EOM)

def test_r08_fires_without_services_and_not_with_one():
    assert _fired(services_24h=0) == ["R08"]
    assert _fired(services_24h=1) == []
    assert _check("R08", services_24h=0)["explanation"] == "sin servicios con desplazamiento 24 h antes ni después"
    assert _check("R08", services_24h=1)["explanation"] == "1 servicios en ±24 h"


def test_r08_only_applies_to_vehicles_that_exist_in_eom():
    assert _fired(services_24h=0, vehicle_in_eom=False) == []
    check = _check("R08", services_24h=0, vehicle_in_eom=False)
    assert check["triggered"] is False
    assert check["explanation"] == "el vehículo no opera en EOM: aplica la regla por vehículo V05"


# ----------------------------------------------------------------------------- R09 (22 to 4 h, +-3 h)

@pytest.mark.parametrize("hour, fires", [(21, False), (22, True), (23, True), (0, True), (3, True), (4, False),
                                         (12, False)])
def test_r09_night_band_goes_from_22_to_4(hour, fires):
    assert _fired(hour=hour, services_3h=0, time_text=f"{hour:02d}:00") == (["R09"] if fires else [])


def test_r09_does_not_fire_with_a_nearby_service():
    assert _fired(hour=23, services_3h=1, time_text="23:14") == []
    assert _check("R09", hour=23, services_3h=1, time_text="23:14")["explanation"] == (
        "tanqueo a las 23:14 con servicio cercano o sin operación en EOM")
    assert _check("R09", hour=23, services_3h=0, time_text="23:14")["explanation"] == (
        "tanqueo a las 23:14 sin servicios cercanos")


def test_r09_only_applies_to_vehicles_that_exist_in_eom():
    # services_24h stays above zero so that only R09 is under test.
    assert _fired(hour=23, services_3h=0, vehicle_in_eom=False) == []
    assert _fired(hour=None, services_3h=0) == []


# ----------------------------------------------------------------------------- R10

def test_r10_is_listed_but_not_evaluated_on_a_request():
    check = _check("R10")
    assert check["triggered"] is False and check["evaluated"] is False
    assert check["points"] == 0 and check["rule_points"] == 3
    assert all(c["evaluated"] for c in evaluate_request(_ctx(), RULES) if c["code"] != "R10")


# ----------------------------------------------------------------------------- R11..R14

def _tx(**changes) -> list[dict]:
    base = {"sale_type": "En línea", "amount": 80000, "split_count": 1, "split_amount": 80000, "split_minutes": 0,
            "price_deviation": 0.0}
    base.update(changes)
    return evaluate_transaction(base, RULES)


def _tx_codes(**changes) -> list[str]:
    return [c["code"] for c in _tx(**changes)]


@pytest.mark.parametrize("sale_type", ["Fuera del sistema", "Recuperado", "Manual"])
def test_r11_fires_with_any_sale_type_other_than_online(sale_type):
    checks = _tx(sale_type=sale_type)
    assert [c["code"] for c in checks] == ["R11"] and checks[0]["points"] == 2
    assert checks[0]["explanation"] == f"tipo de venta: {sale_type}"


@pytest.mark.parametrize("sale_type", ["En línea", "en linea", " EN LÍNEA ", "", None])
def test_r11_does_not_fire_with_an_online_sale(sale_type):
    assert _tx_codes(sale_type=sale_type) == []


def test_r12_needs_more_than_150000_in_two_or_more_transactions():
    assert _tx_codes(split_count=2, split_amount=150000, split_minutes=12) == []
    assert _tx_codes(split_count=2, split_amount=150001, split_minutes=12) == ["R12"]
    assert _tx_codes(split_count=1, split_amount=400000) == []          # a single large load is not a split
    check = _tx(split_count=2, split_amount=172050, split_minutes=12.4)[0]
    assert check["explanation"] == "2 transacciones por $172.050 en 12 min" and check["points"] == 2


def test_r13_needs_less_than_2000():
    assert _tx_codes(amount=1999) == ["R13"]
    assert _tx_codes(amount=2000) == []
    check = _tx(amount=1500)[0]
    assert check["explanation"] == "transacción de $1.500, menos de $2.000" and check["points"] == 1


def test_r14_needs_more_than_15_percent_in_either_direction():
    assert _tx_codes(price_deviation=0.15) == []
    assert _tx_codes(price_deviation=-0.15) == []
    assert _tx_codes(price_deviation=0.151) == ["R14"]
    assert _tx_codes(price_deviation=-0.151) == ["R14"]
    assert _tx_codes(price_deviation=None) == []         # fewer than 3 neighbors: no median to compare
    assert _tx(price_deviation=0.2)[0]["explanation"] == "precio +20 % frente a la mediana de la estación"
    assert _tx(price_deviation=-0.2)[0]["explanation"] == "precio -20 % frente a la mediana de la estación"
    assert _tx(price_deviation=0.2)[0]["points"] == 1


def test_a_transaction_can_trigger_several_reconciliation_rules():
    assert _tx_codes(sale_type="Recuperado", amount=1500, price_deviation=0.3) == ["R11", "R13", "R14"]


# ----------------------------------------------------------------------------- thresholds come from the version

def _with(code: str, **params) -> dict:
    rules = dict(RULES)
    rules[code] = active_from_def(CATALOG_BY_CODE[code], params, version=2)
    return rules


def test_every_threshold_is_read_from_the_active_rule_version():
    assert _fired(_with("R04", max_jump_km=100), km_since_prev=142) == ["R04"]
    assert _fired(_with("R05", min_km=200)) == ["R05"]                       # 142 km is now "without travel"
    assert _fired(_with("R06", max_liquid_24h=0)) == ["R06"]
    assert _fired(_with("R07", factor=0.5)) == ["R07"]                       # 5.0 > 0.5 x 6.0
    assert _fired(_with("R09", night_start_h=9), services_3h=0) == ["R09"]   # 09:40 is now "night"
    assert _tx_codes() == []
    assert [c["code"] for c in evaluate_transaction({"amount": 80000}, _with("R13", amount_cop=100000))] == ["R13"]
    assert [c["code"] for c in evaluate_transaction({"price_deviation": 0.1}, _with("R14", max_deviation=0.05))] == ["R14"]


def test_points_come_from_the_active_rule_version():
    rules = dict(RULES)
    rules["R08"] = active_from_def(CATALOG_BY_CODE["R08"], points=5, version=3)
    points, reasons = summarize(evaluate_request(_ctx(services_24h=0), rules))
    assert points == 5 and reasons[0]["version"] == 3


# ----------------------------------------------------------------------------- traffic light and priority

@pytest.mark.parametrize("points, light", [(0, "green"), (1, "yellow"), (2, "yellow"), (3, "yellow"), (4, "red"),
                                           (5, "red"), (7, "red"), (12, "red")])
def test_traffic_light_by_points(points, light):
    assert traffic_light(points) == light


def test_an_inconsistency_between_sources_is_yellow_with_zero_points():
    assert traffic_light(0, has_inconsistency=True) == "yellow"
    assert traffic_light(3, has_inconsistency=True) == "yellow"
    assert traffic_light(4, has_inconsistency=True) == "red"     # an inconsistency never lowers a red


@pytest.mark.parametrize("points, level", [(1, "low"), (2, "medium"), (3, "medium"), (4, "high"), (8, "high")])
def test_priority_by_points(points, level):
    assert priority(points) == level


def test_points_add_up_across_rules():
    points, reasons = summarize(evaluate_request(
        _ctx(odometer=None, km_last_same=10, loads_24h=4, services_24h=0, services_3h=0, hour=23), RULES))
    assert [r["code"] for r in reasons] == ["R01", "R05", "R06", "R08", "R09"]
    assert points == 1 + 3 + 2 + 2 + 2
    assert traffic_light(points) == "red" and priority(points) == "high"


# ----------------------------------------------------------------------------- windows against the ledger

def _vehicle(db, code: str) -> Vehicle:
    return db.scalars(select(Vehicle).where(Vehicle.code == code)).one()


def test_r08_window_counts_a_service_exactly_24_hours_away(fresh, db):
    vehicle = _vehicle(db, "VEH199")       # its only EOM services are 15 to 20 days old
    last = to_local(db.scalars(select(EomService.start).where(EomService.vehicle_id == vehicle.id)
                               .order_by(EomService.start.desc())).first())
    assert last == at(today() - timedelta(days=15), "10:30")
    at_24h = ledger.services_context(db, vehicle, last + timedelta(hours=24))
    assert at_24h["vehicle_in_eom"] is True and at_24h["services_24h"] == 1
    after = ledger.services_context(db, vehicle, last + timedelta(hours=24, minutes=1))
    assert after["vehicle_in_eom"] is True and after["services_24h"] == 0


def test_r09_window_counts_a_service_exactly_3_hours_away(fresh, db):
    vehicle = _vehicle(db, "VEH901")       # first service of today at 06:00
    assert ledger.services_context(db, vehicle, at(today(), "03:00"))["services_3h"] == 1
    assert ledger.services_context(db, vehicle, at(today(), "02:59"))["services_3h"] == 0


def test_vehicle_without_eom_services_is_reported_as_not_in_eom(fresh, db):
    context = ledger.services_context(db, _vehicle(db, "VEH015"), at(today(), "23:30"))
    assert context["vehicle_in_eom"] is False and context["services_24h"] == 0 and context["today_count"] == 0


def _play_green_at(client, time: str) -> dict:
    send(client, case="GREEN", text="Hola, necesito tanquear", time=time)
    send(client, case="GREEN", text="Sí, es para esa ruta")
    send(client, case="GREEN", media_id="media-veh901")
    send(client, case="GREEN", text="Sí, es correcto")
    return detail(client, conversation(client, WA["GREEN"])["request"]["id"])


def test_request_at_02_59_without_a_service_within_3_hours_gets_r09(fresh):
    request = _play_green_at(fresh, "02:59")
    assert request["rule_codes"] == ["R09"] and request["points"] == 2 and request["traffic_light"] == "yellow"
    reason = request["evaluation"]["reasons"][0]
    assert reason["explanation"] == "tanqueo a las 02:59 sin servicios cercanos"
    assert request["context"]["services"]["services_3h"] == 0 and request["context"]["services"]["services_24h"] > 0


def test_request_at_03_00_with_the_06_00_service_three_hours_later_stays_green(fresh):
    request = _play_green_at(fresh, "03:00")
    assert request["rule_codes"] == [] and request["points"] == 0 and request["traffic_light"] == "green"
    r09 = next(c for c in request["evaluation"]["checks"] if c["code"] == "R09")
    assert r09["triggered"] is False
    assert r09["explanation"] == "tanqueo a las 03:00 con servicio cercano o sin operación en EOM"
    assert request["context"]["services"]["services_3h"] == 1


def test_vehicle_outside_eom_never_gets_r08_nor_r09_even_at_night(fresh):
    script = [("Buenas, necesito combustible", None), ("Traslado no programado", None), (None, "media-veh015"),
              ("Sí, es 34.086", None)]
    send(fresh, case="VEH015", text=script[0][0], time="23:30")
    for text, media_id in script[1:]:
        send(fresh, case="VEH015", text=text, media_id=media_id)
    request = detail(fresh, conversation(fresh, WA["VEH015"])["request"]["id"])
    assert request["occurred_at"][11:16] == "23:30"
    assert request["rule_codes"] == ["R02"] and request["points"] == 1
    checks = {c["code"]: c for c in request["evaluation"]["checks"]}
    assert checks["R08"]["triggered"] is False and checks["R09"]["triggered"] is False
    assert checks["R08"]["explanation"] == "el vehículo no opera en EOM: aplica la regla por vehículo V05"


def test_veh199_request_reports_the_ten_checks_with_their_state(fresh):
    request = detail(fresh, play(fresh, "VEH199")["request"]["id"])
    checks = request["evaluation"]["checks"]
    assert [c["code"] for c in checks] == [f"R{n:02d}" for n in range(1, 11)]
    assert {c["code"] for c in checks if c["triggered"]} == {"R05", "R08", "R09"}
    assert [c["code"] for c in checks if not c["evaluated"]] == ["R10"]
    assert next(c for c in checks if c["code"] == "R06")["explanation"] == "1 carga de GNV en 24 h (límite 5)"
    assert next(c for c in checks if c["code"] == "R07")["explanation"] == "6,7 m³ frente a cargas más grandes de 11,8 m³"
