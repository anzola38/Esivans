"""Recommended amount: the formula step by step, rounding to $10,000, caps, "nothing to load",
the cross-check against the level read and the product of the data sheet."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.rules.amount import compute_amount, round_to_10k

from .helpers import TECH, WA, authorize, conversation, decide, detail, in_review, plain, play


def _amount(**changes) -> dict:
    """Green case of the demo: 1/4 of a 12 gal tank, 6 pending services of 18 km, 40.5 km/gal, $16,000."""
    base = dict(level=0.25, capacity=12.0, largest_loads=5.6, pending_services=6, km_per_service=18.0,
                efficiency=40.5, price=16000, unit="gal", efficiency_unit="km/gal", last_load=5.0, km_since_last=142)
    base.update(changes)
    return compute_amount(**base)


def _steps(result: dict) -> dict:
    return {s["key"]: s for s in result["steps"]}


# ----------------------------------------------------------------------------- formula

def test_formula_step_by_step_for_the_green_case():
    result = _amount()
    steps = _steps(result)
    assert list(steps) == ["available", "pending_route", "route_fuel", "reserve", "need", "to_load", "raw_amount",
                           "rounded_amount", "cap", "amount"]
    assert steps["available"]["result"] == 3.0            # 25 % x 12 gal
    assert steps["pending_route"]["result"] == 108.0      # 6 services x 18 km
    assert steps["route_fuel"]["result"] == 2.67          # 108 km / 40.5 km/gal
    assert steps["reserve"]["result"] == 6.0              # half tank
    assert steps["need"]["result"] == 8.67                # min(12; 2.67 + 6)
    assert steps["to_load"]["result"] == 5.67             # 8.67 - 3
    assert steps["raw_amount"]["result"] == 90667         # 5.667 x 16,000
    assert steps["rounded_amount"]["result"] == 90000
    assert steps["cap"]["result"] == 190000               # 12 x 16,000 = 192,000, rounded down
    assert steps["amount"]["result"] == 90000
    assert result["quantity"] == 5.667 and result["raw_amount"] == 90667
    assert result["rounded_amount"] == 90000 and result["cap_amount"] == 190000 and result["amount"] == 90000
    assert result["computable"] is True and result["needs_refuel"] is True and result["note"] is None


def test_formula_texts_are_written_in_es_co_format():
    steps = _steps(_amount())
    assert plain(steps["available"]["formula"]) == "25 % de nivel × 12,0 gal de capacidad"
    assert steps["available"]["display"] == "3,00 gal"
    assert steps["pending_route"]["formula"] == "6 servicios en EOM × 18 km típicos por servicio"
    assert steps["route_fuel"]["formula"] == "108 km ÷ 40,5 km/gal"
    assert steps["need"]["formula"] == "mín(12,0; 2,67 + 6,00) gal"
    assert steps["to_load"]["formula"] == "8,67 − 3,00 gal"
    assert steps["raw_amount"]["formula"] == "5,67 gal × $16.000 de referencia"
    assert steps["raw_amount"]["display"] == "$90.667"
    assert steps["cap"]["formula"] == "12,0 gal (capacidad registrada) × $16.000, hacia abajo al múltiplo de $10.000"
    assert steps["amount"]["formula"] == "mín($90.000; $190.000)" and steps["amount"]["display"] == "$90.000"
    assert [s["unit"] for s in _amount()["steps"]] == ["gal", "km", "gal", "gal", "gal", "gal", "COP", "COP", "COP", "COP"]


def test_need_is_limited_by_the_tank_capacity():
    # 40 services x 18 km / 40.5 = 17.8 gal of route: more than the 12 gal tank.
    result = _amount(pending_services=40)
    assert _steps(result)["need"]["result"] == 12.0
    assert result["quantity"] == 9.0          # 12 - 3 available


def test_gas_vehicle_uses_cubic_meters():
    result = _amount(level=0.25, capacity=14.0, pending_services=0, efficiency=16.2, price=3200, unit="m3",
                     efficiency_unit="km/m³", last_load=3.0, km_since_last=22)
    assert result["quantity"] == 3.5 and result["raw_amount"] == 11200
    assert result["rounded_amount"] == 10000 and result["cap_amount"] == 40000 and result["amount"] == 10000
    assert _steps(result)["to_load"]["display"] == "3,50 m³"


# ----------------------------------------------------------------------------- rounding

@pytest.mark.parametrize("value, rounded", [
    (0, 0), (4999, 0), (5000, 10000), (5001, 10000), (14999, 10000), (15000, 20000),
    (84999, 80000), (85000, 90000), (85001, 90000), (90667, 90000), (94999, 90000), (95000, 100000),
    (48000, 50000), (11200, 10000), (195960, 200000),
])
def test_round_to_the_nearest_10000_with_half_up(value, rounded):
    assert round_to_10k(value) == rounded


@pytest.mark.parametrize("price, raw, rounded", [(16999, 84995, 80000), (17000, 85000, 90000), (17001, 85005, 90000)])
def test_rounding_on_both_sides_of_the_half_through_the_formula(price, raw, rounded):
    # 2 services x 18 km / 18 km/gal = 2 gal; need 8 gal; available 3 gal; exactly 5 gal to load.
    result = _amount(pending_services=2, efficiency=18.0, price=price, km_since_last=None)
    assert result["quantity"] == 5.0
    assert result["raw_amount"] == raw and result["rounded_amount"] == rounded and result["amount"] == rounded


def test_amount_is_always_a_multiple_of_10000():
    for services in range(0, 12):
        for level in (0.0, 0.125, 0.25, 0.375, 0.5):
            result = _amount(pending_services=services, level=level)
            assert result["amount"] % 10000 == 0 and result["cap_amount"] % 10000 == 0
            assert result["amount"] <= result["cap_amount"]


# ----------------------------------------------------------------------------- caps

def test_cap_by_registered_capacity_limits_the_amount():
    # Empty tank and a long route: 12 gal x $16,330 = $195,960 rounds to $200,000, above the cap.
    result = _amount(level=0.0, pending_services=40, price=16330)
    assert result["quantity"] == 12.0 and result["raw_amount"] == 195960
    assert result["rounded_amount"] == 200000
    assert result["cap_amount"] == 190000          # rounded down: the amount must never exceed the tank
    assert result["amount"] == 190000
    assert _steps(result)["amount"]["formula"] == "mín($200.000; $190.000)"


def test_cap_uses_its_largest_loads_when_there_is_no_capacity():
    result = _amount(capacity=None, largest_loads=10.0, level=0.0, pending_services=40)
    assert result["quantity"] == 10.0
    assert result["cap_amount"] == 160000 and result["amount"] == 160000
    assert _steps(result)["cap"]["formula"] == (
        "10,0 gal (sus cargas más grandes) × $16.000, hacia abajo al múltiplo de $10.000")
    assert _steps(result)["available"]["formula"].endswith("10,0 gal de capacidad")


def test_registered_capacity_wins_over_the_largest_loads():
    assert _amount(capacity=12.0, largest_loads=30.0)["cap_amount"] == 190000


@pytest.mark.parametrize("changes, missing", [
    ({"level": None}, "el nivel de combustible"),
    ({"capacity": None, "largest_loads": None}, "la capacidad o el rendimiento del vehículo"),
    ({"efficiency": None}, "la capacidad o el rendimiento del vehículo"),
])
def test_amount_is_not_computable_without_level_capacity_or_efficiency(changes, missing):
    result = _amount(**changes)
    assert result["computable"] is False and result["amount"] is None and result["steps"] == []
    assert result["needs_refuel"] is None and result["cross_check"] is None
    assert result["note"] == f"No se puede calcular el valor: falta {missing}. El técnico lo define."


# ----------------------------------------------------------------------------- to load <= 0

def test_negative_quantity_means_no_refuel_needed():
    # VEH902: 7/8 of tank and 2 pending services.
    result = _amount(level=0.875, pending_services=2, efficiency=42.3, last_load=6.25, km_since_last=32)
    assert result["quantity"] == -3.649
    assert result["needs_refuel"] is False and result["amount"] == 0 and result["raw_amount"] == 0
    steps = _steps(result)
    assert list(steps) == ["available", "pending_route", "route_fuel", "reserve", "need", "to_load", "amount"]
    assert steps["to_load"]["display"] == "-3,65 gal"
    assert steps["amount"]["result"] == 0 and steps["amount"]["display"] == "$0"
    assert steps["amount"]["formula"] == "A cargar es 0 o menos: no necesita tanquear ahora"


def test_exactly_zero_to_load_means_no_refuel_needed():
    result = _amount(level=0.5, pending_services=0)       # half tank and nothing pending: need = reserve
    assert result["quantity"] == 0.0 and result["needs_refuel"] is False and result["amount"] == 0


def test_just_above_zero_still_needs_refuel():
    result = _amount(level=0.5, pending_services=3)       # 54 km / 40.5 = 1.333 gal over the reserve
    assert result["quantity"] == 1.333 and result["needs_refuel"] is True
    assert result["raw_amount"] == 21333 and result["amount"] == 20000


# ----------------------------------------------------------------------------- cross-check

def test_cross_check_that_matches():
    check = _amount()["cross_check"]
    assert check["consistent"] is True
    assert check["km_since_last"] == 142 and check["consumption"] == 3.51      # 142 / 40.5
    assert check["expected_min"] == 1.49 and check["expected_max"] == 8.49 and check["available"] == 3.0
    assert check["explanation"] == ("Consumo desde el último tanqueo: 142 km ÷ 40,5 km/gal = 3,51 gal. "
                                    "Cuadra con el nivel leído.")


def test_cross_check_flags_a_level_lower_than_expected():
    # Loaded 9 gal, drove 20 km (0.49 gal): it should have at least 8.5 gal, not 0.6.
    check = _amount(level=0.05, last_load=9.0, km_since_last=20)["cross_check"]
    assert check["consistent"] is False and check["expected_min"] == 8.51 and check["available"] == 0.6
    assert check["explanation"] == ("El nivel leído (0,6 gal) es menor de lo esperado: cargó 9,0 gal y en 20 km "
                                    "consumió 0,5 gal; debería tener al menos 8,5 gal.")


def test_cross_check_flags_a_level_higher_than_possible():
    # 405 km at 40.5 km/gal are 10 gal: no more than 2 gal can be left in a 12 gal tank.
    check = _amount(level=0.5, last_load=5.0, km_since_last=405)["cross_check"]
    assert check["consistent"] is False and check["expected_max"] == 2.0 and check["available"] == 6.0
    assert check["explanation"] == ("El nivel leído (6,0 gal) es mayor de lo posible: con 405 km recorridos "
                                    "consumió 10,0 gal y no podría tener más de 2,0 gal.")


@pytest.mark.parametrize("level, consistent", [(0.30, True), (0.33, False)])
def test_cross_check_tolerance_is_15_percent_of_the_capacity(level, consistent):
    # Expected maximum 2.0 gal plus 1.8 gal of tolerance = 3.8 gal: 3.6 gal fits, 3.96 gal does not.
    assert _amount(level=level, last_load=5.0, km_since_last=405)["cross_check"]["consistent"] is consistent


@pytest.mark.parametrize("km", [None, -9862])
def test_cross_check_is_skipped_without_a_usable_distance(km):
    assert _amount(km_since_last=km)["cross_check"] is None


# ----------------------------------------------------------------------------- through the API

def test_green_case_detail_shows_the_ten_steps_and_90000(fresh):
    request = in_review(fresh, "GREEN")
    calculation = request["calculation"]
    assert [s["key"] for s in calculation["steps"]] == ["available", "pending_route", "route_fuel", "reserve", "need",
                                                        "to_load", "raw_amount", "rounded_amount", "cap", "amount"]
    assert [s["result"] for s in calculation["steps"]] == [3.0, 108.0, 2.67, 6.0, 8.67, 5.67, 90667, 90000, 190000, 90000]
    assert calculation["amount"] == 90000 and request["suggested_amount"] == 90000
    assert calculation["price"] == 16000 and calculation["product"] == "Gasolina Corriente"
    assert calculation["efficiency_used"] == 40.5 and calculation["efficiency_source"] == "rendimiento del vehículo"
    assert calculation["cross_check"]["consistent"] is True and request["has_inconsistency"] is False
    assert request["context"]["services"]["pending_count"] == 6
    assert request["context"]["services"]["km_per_service"] == 18.0


def test_veh015_rounds_48000_up_to_50000(fresh):
    calculation = in_review(fresh, "VEH015")["calculation"]
    assert calculation["quantity"] == 3.0 and calculation["raw_amount"] == 48000
    assert calculation["rounded_amount"] == 50000 and calculation["amount"] == 50000
    assert calculation["product"] == "Gasolina Corriente"      # a dual-fuel vehicle asks for its liquid tank


def test_veh199_rounds_11200_down_to_10000_in_cubic_meters(fresh):
    calculation = in_review(fresh, "VEH199")["calculation"]
    assert calculation["unit"] == "m3" and calculation["product"] == "GNV" and calculation["price"] == 3200
    assert calculation["quantity"] == 3.5 and calculation["raw_amount"] == 11200
    assert calculation["rounded_amount"] == 10000 and calculation["cap_amount"] == 40000 and calculation["amount"] == 10000


def test_cross_check_mismatch_puts_the_request_in_yellow_with_zero_points(fresh, db):
    # The last refuel of VEH901 becomes 12 gal: after 142 km it should still have about 8.5 gal, not 3.
    db.execute(text("UPDATE provider_transaction SET quantity = 12.0 WHERE external_id = 'TER-010031'"))
    db.commit()
    request = in_review(fresh, "GREEN")
    assert request["traffic_light"] == "yellow" and request["points"] == 0
    assert request["rule_codes"] == [] and request["has_inconsistency"] is True
    assert request["one_click_allowed"] is False
    reason = request["evaluation"]["reasons"][0]
    assert reason["code"] == "INC" and reason["kind"] == "inconsistency" and reason["points"] == 0
    assert reason["name"] == "Inconsistencia entre fuentes"
    assert reason["explanation"] == request["calculation"]["cross_check"]["explanation"]
    assert reason["explanation"].startswith("El nivel leído (3,0 gal) es menor de lo esperado: cargó 12,0 gal")
    # Not green: approving needs the reason.
    assert decide(fresh, request["id"], action="approve").json()["code"] == "reason_required"


def test_cap_falls_back_to_the_largest_loads_for_a_vehicle_without_capacity(fresh, db):
    db.execute(text("UPDATE vehicle SET tank_capacity = NULL WHERE code = 'VEH901'"))
    db.commit()
    request = in_review(fresh, "GREEN")
    calculation = request["calculation"]
    assert request["context"]["largest_loads"] == 5.62
    cap = next(s for s in calculation["steps"] if s["key"] == "cap")
    assert "5,6 gal (sus cargas más grandes)" in cap["formula"]
    assert calculation["cap_amount"] == 80000          # 5.62 gal x $16,000 = $89,920, rounded down
    assert calculation["amount"] == 70000              # 4.07 gal x $16,000 = $65,147, to the nearest $10,000
    assert decide(fresh, request["id"], action="adjust", amount=90000, reason="Prueba del tope").json()["cap_amount"] == 80000


def test_product_is_corriente_unless_the_data_sheet_says_extra(fresh, db):
    corriente = in_review(fresh, "GREEN")
    assert corriente["calculation"]["product"] == "Gasolina Corriente" and corriente["calculation"]["price"] == 16000
    assert corriente["vehicle"]["product"] == "Gasolina Corriente"

    assert fresh.post("/api/dev/reset").status_code == 200
    db.execute(text("UPDATE vehicle SET product = 'Gasolina Extra' WHERE code = 'VEH901'"))
    db.commit()
    extra = in_review(fresh, "GREEN")
    calculation = extra["calculation"]
    assert calculation["product"] == "Gasolina Extra" and calculation["price"] == 21250
    assert calculation["raw_amount"] == 120417 and calculation["amount"] == 120000      # 5.667 gal x $21,250
    assert calculation["cap_amount"] == 250000                                            # 12 gal x $21,250 = $255,000
    approved = decide(fresh, extra["id"], action="approve").json()
    assert approved["enablement"]["product"] == "Gasolina Extra" and approved["enablement"]["amount"] == 120000
    enabled = authorize(fresh, extra["id"], "TER-EXTRA-1").json()
    assert enabled["authorization"]["product"] == "Gasolina Extra"
    last = conversation(fresh, WA["GREEN"])["messages"][-1]
    assert last["kind"] == "authorization" and "$120.000 de Gasolina Extra" in last["text"]


def test_no_fuel_case_suggests_zero_and_explains_it_to_the_driver(fresh):
    chat = play(fresh, "NO_FUEL", steps=4)
    message = chat["messages"][-1]
    assert message["kind"] == "not_needed"
    assert plain(message["text"]) == ("Luis, con el nivel que leí (10,50 gal) te alcanza para tu ruta pendiente y la "
                                      "reserva de ½ tanque: por ahora no necesitas tanquear (-3,6 gal a cargar). "
                                      "¿Lo dejamos así?")
    request = detail(fresh, chat["request"]["id"], TECH)
    assert request["suggested_amount"] == 0 and request["calculation"]["needs_refuel"] is False
    assert request["calculation"]["quantity"] == -3.649
    assert [s["key"] for s in request["calculation"]["steps"]][-1] == "amount"
    assert request["calculation"]["steps"][-1]["result"] == 0
