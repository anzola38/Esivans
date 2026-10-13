"""Seed: deterministic, 20 to 30 vehicles, the 7 cases of the brief with their figures, the vehicle
rules V01..V08 and dates relative to the day it is loaded (the green case always has services "today")."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.rules.catalog import GROUP_MEDIANS
from app.seed import data as seed_data
from app.seed import loader
from app.timeutil import at, to_local, today

from .helpers import COORD, TECH, WA, alerts, conversation, detail, imported, plain, play, sample_csv, vehicle_alert

COUNTS = {"vehicles": 24, "drivers": 24, "transactions": 878, "eom_services": 1534, "alerts": 19, "rules": 25}


def _vehicles(client) -> dict:
    return {v["code"]: v for v in client.get("/api/vehicles", headers=TECH).json()["items"]}


def _ledger(client, code: str) -> dict:
    return client.get(f"/api/vehicles/{code}/ledger", headers=TECH).json()


def _relative(db) -> dict:
    """Everything the seed loads, with dates expressed in days before the seed date."""
    day0 = today()

    def days_ago(moment) -> tuple:
        local = to_local(moment)
        return ((day0 - local.date()).days, local.strftime("%H:%M"))

    transactions = [(r[0], r[1], *days_ago(r[2]), r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]) for r in db.execute(text(
        "SELECT t.external_id, v.code, t.occurred_at, t.provider, t.station, t.product, t.quantity, t.unit_price, "
        "t.amount, t.odometer, t.sale_type FROM provider_transaction t JOIN vehicle v ON v.id = t.vehicle_id "
        "ORDER BY t.id")).all()]
    services = [(r[0], r[1], *days_ago(r[2]), r[3], r[4]) for r in db.execute(text(
        "SELECT s.external_id, v.code, s.start_at, s.origin, s.destination FROM eom_service s "
        "JOIN vehicle v ON v.id = s.vehicle_id ORDER BY s.id")).all()]
    alert_rows = [(r[0], r[1], r[2], r[3], r[4], r[5], *days_ago(r[6]), *days_ago(r[7]), r[8], r[9]) for r in db.execute(text(
        "SELECT a.kind, v.code, a.rule_code, a.points, a.priority, a.reason, a.created_at, a.due_at, a.status, "
        "a.review_result FROM alert a JOIN vehicle v ON v.id = a.vehicle_id ORDER BY a.id")).all()]
    vehicles = [tuple(r) for r in db.execute(text(
        "SELECT code, plate, fuel_type, vehicle_group, product, unit, tank_capacity, reference_efficiency, provider, "
        "flags::text, stats::text FROM vehicle ORDER BY id")).all()]
    drivers = [tuple(r) for r in db.execute(text("SELECT name, phone FROM driver ORDER BY id")).all()]
    rules = [tuple(r) for r in db.execute(text(
        "SELECT code, version, threshold::text, points FROM rule_version ORDER BY code, version")).all()]
    return {"transactions": transactions, "services": services, "alerts": alert_rows, "vehicles": vehicles,
            "drivers": drivers, "rules": rules}


# ----------------------------------------------------------------------------- size and determinism

def test_seed_counts(fresh, db):
    summary = fresh.post("/api/dev/reset").json()
    assert {k: summary[k] for k in COUNTS} == COUNTS
    assert 20 <= summary["vehicles"] <= 30
    for table, expected in (("vehicle", 24), ("driver", 24), ("assignment", 24), ("provider_transaction", 878),
                            ("eom_service", 1534), ("alert", 19), ("rule_version", 25)):
        assert db.scalar(text(f"SELECT count(*) FROM {table}")) == expected, table
    assert summary["seed_date"] == today().isoformat()


def test_seed_data_declares_between_20_and_30_vehicles_with_unique_identifiers():
    vehicles = seed_data.VEHICLES
    assert 20 <= len(vehicles) <= 30 and len(vehicles) == 24
    for key in ("code", "plate", "phone", "driver"):
        assert len({v[key] for v in vehicles}) == len(vehicles), key
    assert {v["group"] for v in vehicles} == {"gasoline", "dual_fuel", "light_diesel", "heavy_diesel", "cng"}
    assert {v["provider"] for v in vehicles} == {"terpel", "gopass"}


def test_two_loads_give_exactly_the_same_data(fresh, db):
    first = _relative(db)
    first_alerts = [{k: v for k, v in a.items() if k != "hours_to_due"} for a in alerts(fresh)["items"]]
    db.rollback()                                # close the read transaction before the reset empties the tables
    assert fresh.post("/api/dev/reset").status_code == 200
    second = _relative(db)
    for key in first:
        assert second[key] == first[key], key
    assert [{k: v for k, v in a.items() if k != "hours_to_due"} for a in alerts(fresh)["items"]] == first_alerts
    assert len(first["transactions"]) == 878 and len(first["services"]) == 1534 and len(first["alerts"]) == 19


def test_load_on_another_day_gives_the_same_counts_and_relative_figures(fresh, db, clock):
    same_day = _relative(db)
    veh160 = _ledger(fresh, "VEH160")["comparison"]
    clock.advance(days=5)
    db.rollback()
    summary = fresh.post("/api/dev/reset").json()
    assert summary["seed_date"] == today().isoformat() and {k: summary[k] for k in COUNTS} == COUNTS
    other_day = _relative(db)                    # relative to the new "today"
    for key in same_day:
        assert other_day[key] == same_day[key], key
    moved = _ledger(fresh, "VEH160")["comparison"]
    assert {k: moved[k] for k in ("km", "gopass_only", "single_ledger", "hidden_cng_loads", "explanation")} == {
        k: veh160[k] for k in ("km", "gopass_only", "single_ledger", "hidden_cng_loads", "explanation")}
    assert moved["to"] == at(today() - timedelta(days=6), "10:33").isoformat() != veh160["to"]


def test_seed_has_no_refuels_today_and_ends_yesterday(fresh, db):
    newest, oldest = db.execute(text("SELECT max(occurred_at), min(occurred_at) FROM provider_transaction")).one()
    assert to_local(newest).date() == today() - timedelta(days=1)
    assert to_local(oldest).date() == today() - timedelta(days=90)
    assert db.scalar(text("SELECT count(*) FROM provider_transaction WHERE source <> 'seed'")) == 0
    assert db.scalar(text("SELECT count(DISTINCT tx_hash) FROM provider_transaction")) == 878


def test_every_driver_has_one_current_assignment_to_one_vehicle(fresh, db):
    rows = db.execute(text(
        "SELECT v.code, d.phone, a.valid_to FROM assignment a JOIN vehicle v ON v.id = a.vehicle_id "
        "JOIN driver d ON d.id = a.driver_id ORDER BY v.id")).all()
    assert len(rows) == 24 and all(r[2] is None for r in rows)
    assert len({r[0] for r in rows}) == 24 and len({r[1] for r in rows}) == 24
    assert dict((r[0], r[1]) for r in rows)["VEH901"] == WA["GREEN"]


# ----------------------------------------------------------------------------- the 7 cases of the brief

def test_case_green_veh901_has_services_today_and_a_coherent_last_refuel(fresh, db):
    vehicle = _vehicles(fresh)["VEH901"]
    assert vehicle["plate"] == "ZZA901" and vehicle["product"] == "Gasolina Corriente" and vehicle["flags"] == []
    assert vehicle["tank_capacity"] == 12.0 and vehicle["reference_efficiency"] == 40.5 and vehicle["provider"] == "terpel"
    starts = [to_local(r[0]).strftime("%H:%M") for r in db.execute(text(
        "SELECT s.start_at FROM eom_service s JOIN vehicle v ON v.id = s.vehicle_id WHERE v.code = 'VEH901' "
        "AND s.start_at >= :start AND s.start_at < :end ORDER BY s.start_at"),
        {"start": at(today(), "00:00"), "end": at(today() + timedelta(days=1), "00:00")}).all()]
    assert starts == ["06:00", "07:30", "09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00"]
    last = _ledger(fresh, "VEH901")["entries"][0]
    assert last["odometer"] == 48210 and last["amount"] == 80000 and last["quantity"] == 5.0
    assert last["timestamp"] == at(today() - timedelta(days=1), "17:30").isoformat()


def test_case_veh015_last_valid_reading_is_33948(fresh):
    ledger = _ledger(fresh, "VEH015")
    last = ledger["entries"][0]
    assert last["odometer"] == 33948 and last["product"] == "Gasolina Corriente"
    assert last["timestamp"] == at(today() - timedelta(days=1), "16:45").isoformat()
    assert ledger["vehicle"]["flags"] == ["V01", "V05"] and ledger["summary"]["eom_services_loaded"] == 0
    assert ledger["stats"]["refuels_90d"] == 99 == ledger["summary"]["refuels"]
    assert ledger["stats"]["amount_90d"] == 4984000 == ledger["summary"]["amount"]
    # The photo of the case reads 24,086 and the dashboard shows 34,086: 138 km after the last valid reading.
    assert 34086 - last["odometer"] == 138


def test_case_veh199_last_gas_load_leaves_22_km_and_a_typical_load_of_9_7(fresh):
    ledger = _ledger(fresh, "VEH199")
    last = ledger["entries"][0]
    assert last["odometer"] == 195384 and last["product"] == "GNV" and last["unit"] == "m3" and last["quantity"] == 3.0
    assert last["timestamp"] == at(today() - timedelta(days=1), "15:40").isoformat()
    assert 195406 - last["odometer"] == 22                      # the photo of the case reads 195,406 km
    quantities = sorted(e["quantity"] for e in ledger["entries"])
    assert quantities[len(quantities) // 2] == 9.7              # median of its 49 loads
    assert ledger["vehicle"]["tank_capacity"] == 14.0 and ledger["vehicle"]["flags"] == ["V08"]
    assert ledger["summary"]["eom_services_loaded"] == 24       # it exists in EOM, but 15 to 20 days ago
    assert seed_data.DEMO_CASES[2]["time"] == "23:14" and seed_data.DEMO_CASES[2]["script"][0]["text"].count("6,7 m3") == 1


def test_case_veh023_loads_corriente_at_16330_until_the_extra_at_21250(fresh):
    ledger = _ledger(fresh, "VEH023")
    assert ledger["vehicle"]["product"] == "Gasolina Corriente" and ledger["vehicle"]["flags"] == []
    assert {e["product"] for e in ledger["entries"]} == {"Gasolina Corriente"}
    assert {e["unit_price"] for e in ledger["entries"]} == {16330.0}
    assert {e["station"] for e in ledger["entries"]} == {"EDS Montería Centro"}
    veh023 = next(d for d in imported(fresh, sample_csv(fresh))["deviations"] if d["vehicle"]["code"] == "VEH023")
    difference = veh023["evidence"]["product_difference"]
    assert (difference["sold_price"], difference["corriente_price"]) == (21250.0, 16330.0)
    assert difference["gallons"] == 5.647 and difference["overpaid"] == 27783
    assert difference["overpaid"] == round((21250 - 16330) * 5.647)


def test_case_veh129_scores_8_points(fresh):
    vehicle = _vehicles(fresh)["VEH129"]
    assert vehicle["flags"] == ["V01", "V05", "V08"] and vehicle["reference_efficiency"] == 20.3
    alert = vehicle_alert(fresh, "VEH129")
    assert alert["points"] == 8 and alert["priority"] == "high" and alert["status"] == "open"
    ledger = _ledger(fresh, "VEH129")
    assert ledger["summary"]["refuels"] == 102 and ledger["summary"]["amount"] == 4128960
    assert ledger["summary"]["eom_services_loaded"] == 0
    assert "102 tanqueos por $4,1 M" in alert["reason"] and "20,3 km/gal-eq" in alert["reason"]
    assert plain(alert["reason"]).count("61 % menos") == 1


def test_case_veh215_yields_24_against_31_4(fresh):
    vehicle = _vehicles(fresh)["VEH215"]
    assert vehicle["reference_efficiency"] == 24.0 and vehicle["flags"] == ["V01"]
    assert vehicle["efficiency"]["low_limit"] == 31.4 and vehicle["efficiency"]["group_median"] == 41.8
    assert vehicle["efficiency"]["status"] == "low" and vehicle["efficiency"]["status_label"] == "Bajo"
    ledger = _ledger(fresh, "VEH215")
    assert ledger["stats"]["km_90d"] == 1755 and ledger["stats"]["fuel_90d"] == 73.04 and ledger["summary"]["refuels"] == 17
    assert round(1755 / 73.04, 1) == 24.0
    odometers = [e["odometer"] for e in ledger["entries"]]
    assert odometers[0] - odometers[-1] == 1755                 # its 17 refuels cover exactly those km
    assert "24,0 km/gal" in vehicle_alert(fresh, "VEH215")["reason"] and "31,4" in vehicle_alert(fresh, "VEH215")["reason"]


def test_case_veh160_gopass_alone_would_compute_783(fresh):
    comparison = _ledger(fresh, "VEH160")["comparison"]
    assert comparison["km"] == 4803 and comparison["gopass_only"]["gallons"] == 6.135
    assert round(comparison["gopass_only"]["efficiency"]) == 783 and comparison["hidden_cng_loads"] == 34
    assert _vehicles(fresh)["VEH160"]["flags"] == ["V06"] and _vehicles(fresh)["VEH160"]["provider"] == "gopass"


# ----------------------------------------------------------------------------- vehicle rules V01..V08

def test_vehicle_rules_of_the_seed(fresh):
    flags = {code: v["flags"] for code, v in _vehicles(fresh).items() if v["flags"]}
    assert flags == {"VEH015": ["V01", "V05"], "VEH129": ["V01", "V05", "V08"], "VEH199": ["V08"], "VEH215": ["V01"],
                     "VEH160": ["V06"], "VEH910": ["V04"], "VEH911": ["V02"], "VEH915": ["V07"], "VEH916": ["V03"]}
    assert {flag for values in flags.values() for flag in values} == {f"V{n:02d}" for n in range(1, 9)}


def test_every_flagged_vehicle_has_one_vehicle_alert_with_the_points_of_its_rules(fresh):
    points = {"V01": 3, "V02": 2, "V03": 2, "V04": 3, "V05": 3, "V06": 1, "V07": 1, "V08": 2}
    vehicle_alerts = alerts(fresh, "kind=vehicle")["items"]
    vehicles = _vehicles(fresh)
    assert sorted(a["vehicle"]["code"] for a in vehicle_alerts) == sorted(c for c, v in vehicles.items() if v["flags"])
    for alert in vehicle_alerts:
        flags = vehicles[alert["vehicle"]["code"]]["flags"]
        assert alert["rule_codes"] == flags
        assert alert["points"] == sum(points[f] for f in flags)
    assert {a["vehicle"]["code"]: a["points"] for a in vehicle_alerts} == {
        "VEH129": 8, "VEH015": 6, "VEH215": 3, "VEH910": 3, "VEH199": 2, "VEH911": 2, "VEH916": 2, "VEH160": 1,
        "VEH915": 1}


def test_v01_and_v02_match_the_thresholds_75_and_140_percent_of_the_group_median(fresh):
    for code, vehicle in _vehicles(fresh).items():
        efficiency = vehicle["efficiency"]
        median = GROUP_MEDIANS[vehicle["group"]]
        assert efficiency["group_median"] == median
        assert efficiency["low_limit"] == round(median * 0.75 + 1e-9, 1)
        assert efficiency["high_limit"] == round(median * 1.40 + 1e-9, 1)
        value = vehicle["reference_efficiency"]
        if value is None:
            assert efficiency["status"] == "inconclusive" and code == "VEH910"
            continue
        assert ("V01" in vehicle["flags"]) is (value < 0.75 * median), code
        assert ("V02" in vehicle["flags"]) is (value > 1.40 * median), code
        assert efficiency["status"] == ("low" if value < 0.75 * median else "high" if value > 1.40 * median else "normal")
    assert _vehicles(fresh)["VEH911"]["efficiency"]["status_label"] == "Alto"


def test_v04_frozen_odometer_and_v07_missing_readings_are_visible_in_the_ledger(fresh):
    frozen = [e["odometer"] for e in _ledger(fresh, "VEH910")["entries"]]
    most_common = max(set(frozen), key=frozen.count)
    assert frozen.count(most_common) / len(frozen) >= 0.30          # V04: 30 % or more with the same odometer
    assert _ledger(fresh, "VEH910")["flags"][0]["explanation"].startswith("Odómetro congelado en el 62")
    missing = [e for e in _ledger(fresh, "VEH915")["entries"] if e["odometer"] is None]
    assert len(missing) / 28 >= 0.10                                # V07: 10 % or more without odometer


def test_v05_vehicles_have_no_eom_services_and_v06_uses_both_providers(fresh):
    vehicles = _vehicles(fresh)
    for code in ("VEH015", "VEH129"):
        assert "V05" in vehicles[code]["flags"] and _ledger(fresh, code)["summary"]["eom_services_loaded"] == 0
    for code, vehicle in vehicles.items():
        if "V05" not in vehicle["flags"]:
            assert _ledger(fresh, code)["summary"]["eom_services_loaded"] > 0, code
    providers = {code: {p["provider"] for p in _ledger(fresh, code)["summary"]["providers"]} for code in vehicles}
    assert [code for code, used in providers.items() if len(used) == 2] == ["VEH160"]


def test_seed_refuel_alerts_are_consistent_with_their_transactions(fresh):
    refuel = alerts(fresh, "kind=refuel")["items"]
    assert len(refuel) == 10
    by_key = {(a["vehicle"]["code"], tuple(a["rule_codes"])): a for a in refuel}
    night = by_key[("VEH199", ("R08", "R09"))]
    assert night["evidence"]["transaction"]["timestamp"][11:16] == "22:13"
    assert "tanqueo a las 22:13 sin servicios cercanos" in night["reason"] and night["review_result"] == "confirmed"
    jump = by_key[("VEH904", ("R04",))]
    assert jump["evidence"]["transaction"]["odometer"] - jump["evidence"]["previous_transaction"]["odometer"] == 1240
    assert jump["reason"].startswith("R04 Salto de kilometraje: 1.240 km en ")
    no_odometer = by_key[("VEH905", ("R01",))]
    assert no_odometer["evidence"]["transaction"]["odometer"] is None and no_odometer["review_result"] == "data_error"
    recovered = by_key[("VEH906", ("R05", "R11"))]
    assert recovered["evidence"]["transaction"]["sale_type"] == "Recuperado"
    assert recovered["evidence"]["transaction"]["provider"] == "gopass"
    big = by_key[("VEH908", ("R07",))]
    assert big["evidence"]["transaction"]["quantity"] == 26.4 and big["evidence"]["transaction"]["quantity"] > 1.5 * 12.7


# ----------------------------------------------------------------------------- relative to the day it is loaded

def test_seed_loaded_on_another_day_keeps_the_green_case_green(fresh, clock):
    clock.advance(days=3)
    summary = fresh.post("/api/dev/reset").json()
    assert summary["seed_date"] == today().isoformat()
    chat = play(fresh, "GREEN")
    request = detail(fresh, chat["request"]["id"])
    assert request["occurred_at"] == at(today(), "09:40").isoformat()
    assert request["traffic_light"] == "green" and request["points"] == 0 and request["suggested_amount"] == 90000
    services = request["context"]["services"]
    assert services["today_count"] == 9 and services["pending_count"] == 6
    assert services["next_service"]["start"] == at(today(), "10:30").isoformat()
    assert request["context"]["last_refuel"]["timestamp"] == at(today() - timedelta(days=1), "17:30").isoformat()
    assert request["context"]["km_since_last_refuel"] == 142
    assert "10:30" in plain(chat["messages"][3]["text"])


@pytest.mark.parametrize("hours", [5, 11, 17, 23])
def test_demo_cases_do_not_depend_on_the_time_of_day(fresh, clock, hours):
    clock.advance(hours=hours)                    # may cross midnight: the seed is then reloaded for that day
    assert fresh.post("/api/dev/reset").json()["seed_date"] == today().isoformat()
    green = detail(fresh, play(fresh, "GREEN")["request"]["id"])
    assert (green["traffic_light"], green["points"], green["suggested_amount"]) == ("green", 0, 90000)
    yellow = detail(fresh, play(fresh, "VEH015")["request"]["id"])
    assert (yellow["traffic_light"], yellow["rule_codes"], yellow["suggested_amount"]) == ("yellow", ["R02"], 50000)
    assert yellow["evidence"]["proposed_odometer"] == 34086
    red = detail(fresh, play(fresh, "VEH199")["request"]["id"])
    assert (red["traffic_light"], red["points"], red["rule_codes"]) == ("red", 7, ["R05", "R08", "R09"])
    assert red["occurred_at"] == at(today(), "23:14").isoformat()
    counts = alerts(fresh)["counts"]
    assert (counts["total"], counts["open"], counts["reviewed"], counts["overdue"]) == (19, 11, 8, 2)


def test_ensure_seed_keeps_a_seed_of_today_and_reloads_one_from_another_day(fresh, db, clock):
    assert loader.ensure_seed(db) == "vigente"
    loaded_on = today().isoformat()
    play(fresh, "GREEN")
    clock.advance(days=1)
    db.rollback()
    assert loader.ensure_seed(db) == f"recargada (la anterior era del {loaded_on})"
    assert loader.seed_date(db) == today().isoformat() != loaded_on
    assert fresh.get("/api/health").json()["seed_date"] == today().isoformat()
    assert conversation(fresh, WA["GREEN"])["request"] is None          # the reload starts from a clean queue
    assert db.scalar(text("SELECT count(*) FROM provider_transaction")) == 878
    assert loader.ensure_seed(db) == "vigente"


def test_container_started_on_another_day_reloads_the_seed_instead_of_failing(fresh, clock):
    """Same steps as `app.start.main()` when the containers were left with the seed of a previous day."""
    from app.db import SessionLocal

    loaded_on = today().isoformat()
    clock.advance(days=2)
    with SessionLocal() as session:
        assert loader.ensure_seed(session) == f"recargada (la anterior era del {loaded_on})"
    with SessionLocal() as session:
        assert loader.seed_date(session) == today().isoformat()
        assert loader.ensure_seed(session) == "vigente"
    request = detail(fresh, play(fresh, "GREEN")["request"]["id"])
    assert request["traffic_light"] == "green" and request["suggested_amount"] == 90000
    assert request["context"]["services"]["pending_count"] == 6


def test_first_start_with_an_empty_database_loads_the_seed(fresh, db):
    db.execute(text("UPDATE app_meta SET key = key || '_old'"))      # as if the seed had never been loaded
    db.commit()
    assert loader.seed_date(db) is None
    db.rollback()
    assert loader.ensure_seed(db) == "cargada"
    assert loader.seed_date(db) == today().isoformat()
    assert db.scalar(text("SELECT count(*) FROM vehicle")) == 24
