"""Rules engine, traffic light, odometer and recommended amount (pure functions, no database)."""
from __future__ import annotations

from app.rules import odometer as odo
from app.rules.amount import compute_amount, round_to_10k
from app.rules.catalog import priority, traffic_light
from app.rules.engine import default_rules, evaluate_request, evaluate_transaction, quantile, summarize

RULES = default_rules()


def _ctx(**changes) -> dict:
    base = {
        "odometer": 48352, "odometer_reported": 48352, "odometer_error": None, "odometer_proposed": None,
        "last_valid_odometer": 48210, "km_since_prev": 142, "hours_since_prev": 16.0, "tank": "liquid", "unit": "gal",
        "load": 5.67, "km_last_same": 142, "median_load": 5.0, "largest_loads": 5.6, "loads_24h": 2,
        "frozen_odometer": False, "vehicle_in_eom": True, "services_24h": 12, "services_3h": 3, "hour": 9,
        "time_text": "09:40",
    }
    base.update(changes)
    return base


# ----------------------------------------------------------------------------- R02 (VEH015)

def test_r02_veh015_reading_is_corrected_to_34086():
    # Example of the technical annex: 24,086 between the valid readings 33,948 and 34,152.
    assert odo.classify_error(24086, 33948, 34152) == (odo.CHANGED_DIGIT, 34086)

    check = odo.check_reading(24086, 33948, hours_since_last=21.6)
    assert check["status"] == "atypical"
    assert check["error_type"] == odo.CHANGED_DIGIT
    assert check["proposed"] == 34086
    assert odo.describe_fix(24086, 34086, odo.CHANGED_DIGIT) == "el 3 quedó como 2"

    checks = evaluate_request(_ctx(odometer=34086, odometer_reported=24086, odometer_error=odo.CHANGED_DIGIT,
                                   odometer_proposed=34086, last_valid_odometer=33948, km_since_prev=138,
                                   km_last_same=138, vehicle_in_eom=False, services_24h=0, services_3h=0, hour=14,
                                   time_text="14:20", load=3.0), RULES)
    points, reasons = summarize(checks)
    assert [r["code"] for r in reasons] == ["R02"]
    assert points == 1
    assert traffic_light(points) == "yellow"
    assert "34.086" in reasons[0]["explanation"]


def test_valid_reading_and_unexplained_reading():
    assert odo.check_reading(34086, 33948, 21.6)["status"] == "valid"
    unexplained = odo.check_reading(51777, 33948, 21.6)
    assert unexplained["status"] == "atypical" and unexplained["error_type"] == odo.INCONSISTENT
    checks = evaluate_request(_ctx(odometer_error=odo.INCONSISTENT, odometer_reported=51777), RULES)
    assert [r["code"] for r in summarize(checks)[1]] == ["R03"]


def test_other_typing_patterns():
    assert odo.classify_error(339480, 33900, 34100)[0] == odo.EXTRA_DIGIT
    assert odo.classify_error(3398, 33900, 34100)[0] == odo.MISSING_DIGIT
    assert odo.classify_error(33498, 33940, 33960) == (odo.SWAPPED_DIGITS, 33948)


# ----------------------------------------------------------------------------- R05 + R08 + R09 (VEH199)

def test_veh199_night_refill_scores_7_points_and_red():
    ctx = _ctx(odometer=195406, odometer_reported=195406, last_valid_odometer=195384, km_since_prev=22,
               hours_since_prev=31.6, tank="cng", unit="m3", load=6.7, km_last_same=22, median_load=9.7,
               largest_loads=11.8, loads_24h=1, vehicle_in_eom=True, services_24h=0, services_3h=0, hour=23,
               time_text="23:14")
    points, reasons = summarize(evaluate_request(ctx, RULES))
    assert [r["code"] for r in reasons] == ["R05", "R08", "R09"]
    assert [r["points"] for r in reasons] == [3, 2, 2]
    assert points == 7
    assert traffic_light(points) == "red"
    assert priority(points) == "high"
    assert reasons[0]["explanation"] == ("cargó 6,7 m³ de GNV con 22 km desde su carga anterior (típica 9,7 m³)")
    assert reasons[1]["explanation"] == "sin servicios con desplazamiento 24 h antes ni después"
    assert reasons[2]["explanation"] == "tanqueo a las 23:14 sin servicios cercanos"


def test_r08_and_r09_only_apply_to_vehicles_that_exist_in_eom():
    ctx = _ctx(vehicle_in_eom=False, services_24h=0, services_3h=0, hour=23, time_text="23:14")
    assert summarize(evaluate_request(ctx, RULES))[0] == 0


def test_r01_r04_r06_r07():
    def codes(**changes):
        return [r["code"] for r in summarize(evaluate_request(_ctx(**changes), RULES))[1]]

    assert codes(odometer=None) == ["R01"]
    assert codes(km_since_prev=1240, hours_since_prev=50) == ["R04"]
    assert codes(km_since_prev=1240, hours_since_prev=300) == []      # more than 10 days: not comparable
    assert codes(loads_24h=4) == ["R06"]
    assert codes(loads_24h=4, tank="cng", unit="m3") == []            # gas allows up to 5
    assert codes(load=9.0) == ["R07"]                                  # 9.0 > 1.5 x 5.6


def test_thresholds_come_from_the_rule_version():
    from app.rules.catalog import CATALOG_BY_CODE
    from app.rules.engine import active_from_def

    rules = dict(RULES)
    rules["R05"] = active_from_def(CATALOG_BY_CODE["R05"], {"min_km": 10}, version=2)
    ctx = _ctx(tank="cng", unit="m3", load=6.7, km_last_same=22, median_load=9.7, largest_loads=11.8,
               vehicle_in_eom=False)
    assert summarize(evaluate_request(ctx, rules))[0] == 0  # 22 km is no longer under the threshold


# ----------------------------------------------------------------------------- traffic light

def test_traffic_light_and_priority():
    assert traffic_light(0) == "green"
    assert traffic_light(0, has_inconsistency=True) == "yellow"
    assert [traffic_light(p) for p in (1, 2, 3)] == ["yellow"] * 3
    assert traffic_light(4) == "red" and traffic_light(7) == "red"
    assert [priority(p) for p in (1, 2, 3, 4, 8)] == ["low", "medium", "medium", "high", "high"]


# ----------------------------------------------------------------------------- recommended amount

def _amount(**changes) -> dict:
    base = dict(level=0.25, capacity=12.0, largest_loads=5.6, pending_services=6, km_per_service=18.0,
                efficiency=40.5, price=16000, unit="gal", efficiency_unit="km/gal", last_load=5.0, km_since_last=142)
    base.update(changes)
    return compute_amount(**base)


def test_amount_formula_and_rounding():
    result = _amount()
    # available 3.0; route 108 km / 40.5 = 2.667; need min(12, 2.667 + 6) = 8.667; to load 5.667 gal
    assert abs(result["quantity"] - 5.667) < 0.001
    assert result["raw_amount"] == 90667
    assert result["rounded_amount"] == 90000 and result["amount"] == 90000
    assert result["needs_refuel"] is True
    assert [s["key"] for s in result["steps"]] == ["available", "pending_route", "route_fuel", "reserve", "need",
                                                   "to_load", "raw_amount", "rounded_amount", "cap", "amount"]
    assert result["cross_check"]["consistent"] is True
    assert round_to_10k(94999) == 90000 and round_to_10k(95000) == 100000 and round_to_10k(4999) == 0


def test_amount_is_limited_by_the_cap():
    # Empty tank and a long route: need is capped by the capacity and the amount by the cap.
    result = _amount(level=0.0, pending_services=40, price=16330)
    assert result["quantity"] == 12.0
    assert result["rounded_amount"] == 200000          # 12 x 16,330 = 195,960 -> 200,000
    assert result["cap_amount"] == 190000              # capacity x price, rounded down
    assert result["amount"] == 190000


def test_cap_uses_largest_loads_when_capacity_is_unknown():
    result = _amount(capacity=None, largest_loads=10.0, level=0.0, pending_services=40)
    assert result["cap_amount"] == 160000 and result["amount"] == 160000


def test_zero_or_less_means_no_refuel_needed():
    result = _amount(level=0.875, pending_services=2, efficiency=42.3, last_load=6.25, km_since_last=32)
    assert result["quantity"] < 0
    assert result["needs_refuel"] is False
    assert result["amount"] == 0


def test_cross_check_flags_a_level_that_does_not_match():
    result = _amount(level=0.05, last_load=9.0, km_since_last=20)
    assert result["cross_check"]["consistent"] is False


def test_amount_not_computable_without_level():
    result = _amount(level=None)
    assert result["computable"] is False and result["amount"] is None


# ----------------------------------------------------------------------------- reconciliation rules

def test_reconciliation_rules_r11_to_r14():
    def codes(**tx):
        base = {"sale_type": "En línea", "amount": 80000, "split_count": 1, "split_amount": 80000,
                "split_minutes": 0, "price_deviation": 0.0}
        base.update(tx)
        return [c["code"] for c in evaluate_transaction(base, RULES)]

    assert codes() == []
    assert codes(sale_type="Fuera del sistema") == ["R11"]
    assert codes(split_count=2, split_amount=172050, split_minutes=12) == ["R12"]
    assert codes(amount=1500) == ["R13"]
    assert codes(price_deviation=0.2) == ["R14"]
    assert quantile([1, 2, 3, 4, 5], 0.5) == 3
