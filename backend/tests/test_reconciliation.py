"""Import of the provider file and reconciliation: idempotency, rejected rows, product (C01),
authorized vs. recorded amount (C02), R11 to R14, roles and the domain events."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.models import Alert, ProviderTransaction
from app.timeutil import to_local, today

from .helpers import (COORD, CSV_HEADER, FINANCE, SUPPORT, TECH, alerts, authorized_green, csv_file, csv_row, day, decide,
                      detail, import_csv, imported, in_review, outbox, plain, put_rule, sample_csv)

S1 = "EDS Montería Centro"
SEED_TRANSACTIONS = 878


def _transactions(db) -> int:
    return db.scalar(select(func.count()).select_from(ProviderTransaction))


def _deviation(result: dict, vehicle: str) -> dict:
    return next(d for d in result["deviations"] if d["vehicle"]["code"] == vehicle)


def _codes(result: dict) -> list[list[str]]:
    return [d["rule_codes"] for d in result["deviations"]]


VEH023_ROW = "TER-900102,{day} 07:42:35,VEH023,ZZA023,EDS Montería Centro,NORTE,Gasolina Extra,5.647,gal,21250,119999,87512,En línea"


# ----------------------------------------------------------------------------- sample file

def test_sample_file_has_ten_rows_dated_yesterday(fresh):
    response = fresh.get("/api/dev/samples/terpel")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0] == CSV_HEADER and len(lines) == 11
    assert "{{" not in response.text
    assert all(line.split(",")[1].startswith(day(1)) for line in lines[1:])
    assert lines[2] == VEH023_ROW.format(day=day(1))


def test_sample_file_loads_ten_transactions_and_five_alerts(fresh, db):
    result = imported(fresh, sample_csv(fresh))
    assert (result["rows"], result["imported"], result["duplicates"], result["rejected"]) == (10, 10, 0, 0)
    assert result["alerts_created"] == 5 and result["provider"] == "terpel" and result["provider_label"] == "Terpel"
    assert result["rules_version"] == "v1" and result["matched_authorizations"] == []
    assert result["message"] == ("10 transacciones nuevas en el libro único, 0 duplicadas sin cargar, "
                                 "0 rechazadas y 5 alertas.")
    assert {d["vehicle"]["code"]: d["rule_codes"] for d in result["deviations"]} == {
        "VEH023": ["C01"], "VEH907": ["R13"], "VEH918": ["R01", "R11"], "VEH912": ["R12"], "VEH904": ["R14"]}
    assert {d["vehicle"]["code"]: (d["points"], d["priority"]) for d in result["deviations"]} == {
        "VEH023": (2, "medium"), "VEH907": (1, "low"), "VEH918": (3, "medium"), "VEH912": (2, "medium"),
        "VEH904": (1, "low")}
    assert all(d["kind"] == "reconciliation" and d["status"] == "open" and d["rules_version"] == "v1"
               for d in result["deviations"])
    assert [line["status"] for line in result["lines"]] == ["imported"] * 10
    assert [line["line"] for line in result["lines"]] == list(range(2, 12))
    assert {line["vehicle"]: line.get("rule_codes") for line in result["lines"] if line.get("alert_id")} == {
        "VEH023": ["C01"], "VEH907": ["R13"], "VEH918": ["R01", "R11"], "VEH912": ["R12"], "VEH904": ["R14"]}
    assert _transactions(db) == SEED_TRANSACTIONS + 10
    assert db.scalar(select(func.count()).select_from(ProviderTransaction).where(ProviderTransaction.source == "import")) == 10


def test_imported_transactions_enter_the_single_ledger_of_the_vehicle(fresh):
    before = fresh.get("/api/vehicles/VEH023/ledger", headers=TECH).json()["summary"]["refuels"]
    imported(fresh, sample_csv(fresh))
    ledger = fresh.get("/api/vehicles/VEH023/ledger", headers=TECH).json()
    assert before == 30 and ledger["summary"]["refuels"] == 31
    newest = ledger["entries"][0]
    assert newest["external_id"] == "TER-900102" and newest["source"] == "import"
    assert newest["product"] == "Gasolina Extra" and newest["quantity"] == 5.647 and newest["amount"] == 119999
    assert newest["odometer"] == 87512 and newest["km_since_previous"] == 92


def test_the_new_alerts_show_up_in_the_alert_list(fresh):
    assert alerts(fresh, "kind=reconciliation")["items"] == []
    imported(fresh, sample_csv(fresh))
    listing = alerts(fresh, "kind=reconciliation")
    assert listing["counts"]["total"] == 5 and listing["counts"]["open"] == 5
    assert alerts(fresh)["counts"]["total"] == 24 and alerts(fresh)["counts"]["open"] == 16


# ----------------------------------------------------------------------------- idempotency

def test_second_load_of_the_same_file_duplicates_nothing(fresh, db):
    content = sample_csv(fresh)
    imported(fresh, content)
    alerts_before = db.scalar(select(func.count()).select_from(Alert))
    again = imported(fresh, content)
    assert (again["rows"], again["imported"], again["duplicates"], again["rejected"]) == (10, 0, 10, 0)
    assert again["alerts_created"] == 0 and again["deviations"] == [] and again["overpaid_by_product"] == 0
    assert again["batch_id"] == 2
    assert [line["status"] for line in again["lines"]] == ["duplicate"] * 10
    assert again["lines"][0]["message"] == "Ya estaba en el libro único (mismo hash de transacción)"
    assert again["message"] == ("0 transacciones nuevas en el libro único, 10 duplicadas sin cargar, "
                                "0 rechazadas y 0 alertas.")
    assert _transactions(db) == SEED_TRANSACTIONS + 10
    assert db.scalar(select(func.count()).select_from(Alert)) == alerts_before == 24


def test_idempotency_does_not_depend_on_how_the_file_is_sent(fresh, db):
    content = sample_csv(fresh)
    as_json = imported(fresh, content)
    assert as_json["imported"] == 10
    raw = fresh.post("/api/integrations/terpel/imports", content=content.encode("utf-8"),
                     headers={**FINANCE, "Content-Type": "text/csv", "X-Filename": "crudo.csv"})
    assert raw.status_code == 200 and raw.json()["duplicates"] == 10 and raw.json()["filename"] == "crudo.csv"
    multipart = fresh.post("/api/integrations/terpel/imports", headers=FINANCE,
                           files={"file": ("adjunto.csv", content.encode("utf-8"), "text/csv")})
    assert multipart.status_code == 200 and multipart.json()["duplicates"] == 10
    assert multipart.json()["filename"] == "adjunto.csv" and multipart.json()["imported"] == 0
    with_bom_and_semicolons = "﻿" + content.replace(",", ";")
    assert imported(fresh, with_bom_and_semicolons)["duplicates"] == 10
    assert _transactions(db) == SEED_TRANSACTIONS + 10


def test_a_changed_row_is_a_new_transaction_and_the_rest_stay_duplicates(fresh):
    content = sample_csv(fresh)
    imported(fresh, content)
    changed = content.replace("TER-900103", "TER-900199")
    result = imported(fresh, changed)
    assert (result["imported"], result["duplicates"]) == (1, 9)
    assert [line["status"] for line in result["lines"]].count("imported") == 1


def test_seed_transactions_are_also_protected_by_the_hash(fresh, db):
    row = db.execute(text(
        "SELECT t.external_id, t.occurred_at, v.code, v.plate, t.station, t.product, t.quantity, t.unit, "
        "t.unit_price, t.amount, t.odometer, t.sale_type FROM provider_transaction t JOIN vehicle v ON v.id = t.vehicle_id "
        "WHERE t.external_id = 'TER-010031'")).one()
    line = ",".join(str(v) for v in [row[0], to_local(row[1]).strftime("%Y-%m-%d %H:%M:%S"), row[2], row[3], row[4], "NORTE", row[5],
                                     f"{row[6]:.3f}", row[7], int(row[8]), row[9], row[10], row[11]])
    result = imported(fresh, csv_file(line))
    assert (result["imported"], result["duplicates"]) == (0, 1)
    assert _transactions(db) == SEED_TRANSACTIONS


# ----------------------------------------------------------------------------- rejected rows and bad files

def test_invalid_rows_are_rejected_with_their_reason_and_the_valid_one_is_loaded(fresh, db):
    content = csv_file(
        csv_row("TER-X1", "VEH999", 80000),
        f"TER-X2,{day()} 10:00:00,VEH903,ZZA903,EDS Cereté Norte,NORTE,Gasolina Corriente,,gal,16000,80000,72300,En línea",
        "TER-X3,no-es-fecha,VEH903,ZZA903,EDS Cereté Norte,NORTE,Gasolina Corriente,5.000,gal,16000,80000,72300,En línea",
        f"TER-X4,{day()} 10:00:00,VEH903,ZZA903,EDS Cereté Norte,NORTE,Gasolina Corriente,cinco,gal,16000,80000,72300,En línea",
        csv_row("TER-X5", "VEH903", 80000, odometer=72400),
    )
    result = imported(fresh, content)
    assert (result["rows"], result["imported"], result["duplicates"], result["rejected"]) == (5, 1, 0, 4)
    lines = {line["external_id"]: line for line in result["lines"]}
    assert lines["TER-X1"]["status"] == "rejected" and lines["TER-X1"]["line"] == 2
    assert lines["TER-X1"]["message"] == "Fila rechazada: vehículo VEH999 no existe en el maestro"
    assert lines["TER-X2"]["status"] == "rejected"
    assert lines["TER-X2"]["message"] == "Fila rechazada: cantidad, precio o valor vacío"
    assert lines["TER-X3"]["status"] == "rejected"
    assert lines["TER-X3"]["message"] == "Fila rechazada: fecha no reconocida: no-es-fecha"
    assert lines["TER-X4"]["status"] == "rejected"
    assert lines["TER-X4"]["message"] == "Fila rechazada: número no válido: cinco"
    assert lines["TER-X5"]["status"] == "imported" and lines["TER-X5"]["message"] is None
    assert result["message"] == "1 transacciones nuevas en el libro único, 0 duplicadas sin cargar, 4 rechazadas y 0 alertas."
    assert _transactions(db) == SEED_TRANSACTIONS + 1


def test_vehicle_is_found_by_plate_when_the_code_is_missing(fresh):
    line = f"TER-P1,{day()} 19:00:00,,ZZA903,EDS Cereté Norte,NORTE,Gasolina Corriente,5.000,gal,16000,80000,72400,En línea"
    result = imported(fresh, csv_file(line))
    assert result["imported"] == 1 and result["rejected"] == 0


def test_unknown_provider_is_a_404(fresh):
    response = import_csv(fresh, sample_csv(fresh), provider="shell")
    assert response.status_code == 404
    assert response.json() == {"detail": "Proveedor desconocido: shell. Usa terpel o gopass.", "code": "unknown_provider"}


def test_gopass_files_are_accepted_too(fresh):
    line = csv_row("GOP-1", "VEH906", 70000, station="Estación aliada Sahagún", unit_price=16030, odometer=54700)
    response = import_csv(fresh, csv_file(line), provider="gopass")
    assert response.status_code == 200
    assert response.json()["provider_label"] == "GoPass" and response.json()["imported"] == 1


def test_empty_file_and_missing_columns_are_422(fresh, db):
    empty = import_csv(fresh, "   \n")
    assert empty.status_code == 422 and empty.json() == {"detail": "El archivo está vacío.", "code": "empty_file"}
    missing = import_csv(fresh, "external_id,timestamp,vehicle\nTER-1,2026-01-01 10:00:00,VEH903\n")
    assert missing.status_code == 422 and missing.json()["code"] == "missing_columns"
    assert missing.json()["detail"] == "Al archivo le faltan columnas: product, quantity, unit_price, amount."
    no_content = fresh.post("/api/integrations/terpel/imports", json={"filename": "x.csv"}, headers=FINANCE)
    assert no_content.status_code == 422 and no_content.json()["code"] == "content_required"
    no_file = fresh.post("/api/integrations/terpel/imports", headers=FINANCE, data={"otro": "campo"},
                         files={"adjunto": ("x.csv", b"a,b", "text/csv")})
    assert no_file.status_code == 422 and no_file.json()["code"] == "file_required"
    assert _transactions(db) == SEED_TRANSACTIONS


# ----------------------------------------------------------------------------- roles

@pytest.mark.parametrize("headers, user", [(FINANCE, "Paola Ruiz"), (COORD, "Andres Molina"), (TECH, "Laura Gomez")])
def test_finance_coordinator_and_technician_can_import(fresh, headers, user):
    response = import_csv(fresh, sample_csv(fresh), headers)
    assert response.status_code == 200 and response.json()["imported"] == 10
    entry = fresh.get("/api/audit?action=import", headers=COORD).json()["items"][0]
    assert entry["actor"] == user and entry["role"] == headers["X-Demo-Role"]


def test_support_cannot_import(fresh, db):
    response = import_csv(fresh, sample_csv(fresh), SUPPORT)
    assert response.status_code == 403
    assert response.json()["allowed_roles"] == ["finance", "coordinator", "technician"]
    assert _transactions(db) == SEED_TRANSACTIONS and outbox(fresh) == []


# ----------------------------------------------------------------------------- C01: product (VEH023)

def test_veh023_paid_27783_more_for_extra_than_for_corriente(fresh):
    result = imported(fresh, sample_csv(fresh))
    assert result["overpaid_by_product"] == 27783
    alert = _deviation(result, "VEH023")
    assert alert["rule_codes"] == ["C01"] and alert["points"] == 2 and alert["priority"] == "medium"
    assert alert["reasons"][0]["name"] == "Producto distinto al de la ficha técnica"
    assert alert["reason"] == (
        "C01 Producto distinto al de la ficha técnica: cargó Gasolina Extra a $21.250 por galón y su ficha pide "
        "Corriente, que estaba a $16.330 en la misma estación ese día: 5,647 galones y $27.783 pagados de más")
    difference = alert["evidence"]["product_difference"]
    assert difference == {"authorized_product": "Gasolina Corriente", "sold_product": "Gasolina Extra",
                          "sold_price": 21250.0, "corriente_price": 16330.0,
                          "corriente_price_source": "misma estación, mismo día", "difference_per_gallon": 4920.0,
                          "gallons": 5.647, "overpaid": 27783}
    transaction = alert["evidence"]["transaction"]
    assert transaction["external_id"] == "TER-900102" and transaction["station"] == S1
    assert transaction["unit_price"] == 21250.0 and transaction["quantity"] == 5.647 and transaction["amount"] == 119999


def test_c01_uses_the_reference_price_when_the_station_sold_no_corriente_that_day(fresh):
    result = imported(fresh, csv_file(VEH023_ROW.format(day=day(1))))
    difference = _deviation(result, "VEH023")["evidence"]["product_difference"]
    assert difference["corriente_price"] == 16000.0
    assert difference["corriente_price_source"] == "precio de referencia más cercano"
    assert difference["overpaid"] == 29647 and result["overpaid_by_product"] == 29647      # 5.647 x (21,250 - 16,000)


def test_c01_does_not_fire_for_corriente_nor_for_a_vehicle_whose_data_sheet_asks_for_extra(fresh, db):
    corriente = csv_row("TER-C1", "VEH023", 80000, station=S1, unit_price=16330, odometer=87512)
    assert imported(fresh, csv_file(corriente))["deviations"] == []
    db.execute(text("UPDATE vehicle SET product = 'Gasolina Extra' WHERE code = 'VEH023'"))
    db.commit()
    result = imported(fresh, csv_file(VEH023_ROW.format(day=day(1))))
    assert result["imported"] == 1 and result["deviations"] == [] and result["overpaid_by_product"] == 0


# ----------------------------------------------------------------------------- C02: authorized vs. recorded

def test_authorization_of_the_demo_matches_its_row_in_the_sample_file(fresh):
    request = authorized_green(fresh, "TER-CONCILIA-1")
    content = sample_csv(fresh)
    extra = content.strip().splitlines()[-1].split(",")
    assert len(content.strip().splitlines()) == 12
    assert extra[0] == "TER-AUT0001" and extra[2] == "VEH901" and extra[6] == "Gasolina Corriente"
    assert extra[7] == "5.625" and extra[9] == "16000" and extra[10] == "90000" and extra[11] == "48352"

    result = imported(fresh, content)
    assert result["imported"] == 11 and result["alerts_created"] == 5
    assert result["matched_authorizations"] == [{
        "authorization_id": 1, "request_id": request["id"], "reference": "TER-CONCILIA-1",
        "authorized_amount": 90000, "recorded_amount": 90000, "difference": 0, "difference_share": 0.0,
        "within_tolerance": True, "vehicle": "VEH901"}]
    assert "VEH901" not in [d["vehicle"]["code"] for d in result["deviations"]]
    authorization = detail(fresh, request["id"])["authorization"]
    assert authorization["reconciled"] is True and authorization["reconciled_difference"] == 0
    # Once reconciled, the sample no longer adds the row.
    assert len(sample_csv(fresh).strip().splitlines()) == 11


@pytest.mark.parametrize("amount, share, fires", [(90000, 0.0, False), (94500, 0.05, False), (85500, 0.05, False),
                                                  (94501, 0.05, True), (85499, 0.05, True), (100000, 0.1111, True)])
def test_c02_fires_when_the_recorded_amount_differs_more_than_5_percent(fresh, amount, share, fires):
    request = authorized_green(fresh, "TER-C02-1")
    result = imported(fresh, csv_file(csv_row("TER-C02-TX", "VEH901", amount, odometer=48400)))
    match = result["matched_authorizations"][0]
    assert match["authorized_amount"] == 90000 and match["recorded_amount"] == amount
    assert match["difference"] == amount - 90000 and match["difference_share"] == share
    assert match["within_tolerance"] is (not fires)
    assert _codes(result) == ([["C02"]] if fires else [])
    assert detail(fresh, request["id"])["authorization"]["reconciled_difference"] == amount - 90000


def test_c02_alert_explains_authorized_and_recorded(fresh):
    authorized_green(fresh, "TER-C02-2")
    result = imported(fresh, csv_file(csv_row("TER-C02-TX", "VEH901", 100000, odometer=48400)))
    alert = result["deviations"][0]
    assert alert["rule_codes"] == ["C02"] and alert["points"] == 2 and alert["priority"] == "medium"
    assert plain(alert["reason"]) == ("C02 Valor distinto al autorizado: autorizado $90.000 (referencia TER-C02-2) y el "
                                      "proveedor registró $100.000: diferencia de $10.000 (11,1 %)")
    assert alert["evidence"]["authorization"]["reference"] == "TER-C02-2"
    assert alert["evidence"]["authorization"]["within_tolerance"] is False


def test_transaction_without_an_authorization_is_not_matched(fresh):
    result = imported(fresh, csv_file(csv_row("TER-SOLA", "VEH901", 100000, odometer=48400)))
    assert result["matched_authorizations"] == [] and result["deviations"] == []


def test_approved_but_not_enabled_request_has_nothing_to_reconcile(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    result = imported(fresh, csv_file(csv_row("TER-SIN-HAB", "VEH901", 150000, odometer=48400)))
    assert result["matched_authorizations"] == [] and result["deviations"] == []
    assert len(sample_csv(fresh).strip().splitlines()) == 11


def test_an_authorization_is_reconciled_only_once(fresh):
    request = authorized_green(fresh, "TER-UNA-VEZ")
    first = imported(fresh, csv_file(csv_row("TER-A", "VEH901", 90000, odometer=48400)))
    second = imported(fresh, csv_file(csv_row("TER-B", "VEH901", 140000, hour="21:00:00", odometer=48500)))
    assert len(first["matched_authorizations"]) == 1 and second["matched_authorizations"] == []
    assert second["deviations"] == []
    assert detail(fresh, request["id"])["authorization"]["reconciled_difference"] == 0


def test_c02_tolerance_comes_from_the_rule_version(fresh):
    put_rule(fresh, "C02", threshold={"max_difference": 0.2}, reason="Tolerancia de prueba")
    authorized_green(fresh, "TER-C02-3")
    result = imported(fresh, csv_file(csv_row("TER-C02-TX", "VEH901", 100000, odometer=48400)))
    assert result["matched_authorizations"][0]["within_tolerance"] is True and result["deviations"] == []


# ----------------------------------------------------------------------------- R11..R14 on real rows

def test_r11_sale_out_of_the_system_and_r01_without_odometer(fresh):
    alert = _deviation(imported(fresh, sample_csv(fresh)), "VEH918")
    assert alert["rule_codes"] == ["R01", "R11"] and alert["points"] == 3
    assert alert["reason"] == ("R01 Odómetro sin dato: no se registró odómetro | "
                               "R11 Venta fuera del sistema o recuperada: tipo de venta: Fuera del sistema")
    assert alert["evidence"]["transaction"]["odometer"] is None
    assert alert["evidence"]["transaction"]["sale_type"] == "Fuera del sistema"


def test_r11_alone_and_not_for_an_online_sale(fresh):
    recovered = imported(fresh, csv_file(csv_row("TER-R11", "VEH903", 80000, sale_type="Recuperado", odometer=72400)))
    assert _codes(recovered) == [["R11"]] and recovered["deviations"][0]["points"] == 2
    online = imported(fresh, csv_file(csv_row("TER-OK", "VEH907", 80000, sale_type="En línea", odometer=58900)))
    assert online["deviations"] == []


def test_r12_two_loads_in_12_minutes_for_172050(fresh):
    alert = _deviation(imported(fresh, sample_csv(fresh)), "VEH912")
    assert alert["rule_codes"] == ["R12"] and alert["points"] == 2
    assert alert["reason"] == "R12 Carga fraccionada sobre el tope: 2 transacciones por $172.050 en 12 min"
    assert alert["evidence"]["transaction"]["external_id"] == "TER-900107"       # the alert goes on the last one


@pytest.mark.parametrize("second_hour, amounts, fires", [
    ("20:30:00", (75000, 75000), False),      # exactly $150,000 in exactly 30 minutes: not more than the limit
    ("20:30:00", (75000, 75001), True),       # $150,001 in exactly 30 minutes
    ("20:31:00", (100000, 100000), False),    # $200,000, but 31 minutes apart
    ("20:10:00", (100000, 100000), True),
])
def test_r12_limits_are_150000_and_30_minutes(fresh, second_hour, amounts, fires):
    rows = [csv_row("TER-S1", "VEH908", amounts[0], hour="20:00:00", product="Diesel", unit_price=11100, odometer=118300),
            csv_row("TER-S2", "VEH908", amounts[1], hour=second_hour, product="Diesel", unit_price=11100, odometer=118300)]
    result = imported(fresh, csv_file(*rows))
    assert result["imported"] == 2
    assert _codes(result) == ([["R12"]] if fires else [])


def test_r12_does_not_mix_different_products(fresh):
    rows = [csv_row("TER-M1", "VEH913", 100000, hour="20:00:00", odometer=133700),
            csv_row("TER-M2", "VEH913", 100000, hour="20:10:00", product="GNV", unit_price=3200, unit="m3",
                    station="EDS GNV Montería Sur", odometer=133700)]
    assert imported(fresh, csv_file(*rows))["deviations"] == []


def test_r13_transaction_under_2000(fresh):
    alert = _deviation(imported(fresh, sample_csv(fresh)), "VEH907")
    assert alert["rule_codes"] == ["R13"] and alert["points"] == 1 and alert["priority"] == "low"
    assert alert["reason"] == "R13 Transacción de valor mínimo: transacción de $1.500, menos de $2.000"


@pytest.mark.parametrize("amount, fires", [(1999, True), (2000, False)])
def test_r13_limit_is_2000(fresh, amount, fires):
    result = imported(fresh, csv_file(csv_row("TER-R13", "VEH903", amount, odometer=72400)))
    assert _codes(result) == ([["R13"]] if fires else [])


def test_r14_price_20_percent_over_the_station_median(fresh):
    alert = _deviation(imported(fresh, sample_csv(fresh)), "VEH904")
    assert alert["rule_codes"] == ["R14"] and alert["points"] == 1
    assert plain(alert["reason"]) == "R14 Precio unitario atípico: precio +20 % frente a la mediana de la estación"
    assert alert["evidence"]["station_median_price"] == 16000.0
    assert alert["evidence"]["transaction"]["unit_price"] == 19200.0


@pytest.mark.parametrize("unit_price, fires", [(18400, False), (18401, True), (13600, False), (13599, True)])
def test_r14_limit_is_15_percent_in_either_direction(fresh, unit_price, fires):
    # The station sells Corriente at $16,000: 15 % is $18,400 above and $13,600 below.
    result = imported(fresh, csv_file(csv_row("TER-R14", "VEH903", 80000, unit_price=unit_price, quantity=5.0,
                                              odometer=72400)))
    assert _codes(result) == ([["R14"]] if fires else [])


def test_r14_needs_at_least_three_neighbors_to_have_a_median(fresh):
    row = csv_row("TER-NUEVA", "VEH903", 80000, station="EDS Nueva Sin Historia", unit_price=30000, quantity=2.667,
                  odometer=72400)
    result = imported(fresh, csv_file(row))
    assert result["imported"] == 1 and result["deviations"] == []


def test_thresholds_of_the_reconciliation_rules_come_from_the_rule_version(fresh):
    put_rule(fresh, "R13", threshold={"amount_cop": 1000}, reason="Prueba")
    put_rule(fresh, "R14", threshold={"max_deviation": 0.25}, reason="Prueba")
    result = imported(fresh, sample_csv(fresh))
    assert result["rules_version"] == "v3" and result["alerts_created"] == 3
    assert sorted(d["vehicle"]["code"] for d in result["deviations"]) == ["VEH023", "VEH912", "VEH918"]
    assert all(d["rules_version"] == "v3" for d in result["deviations"])


# ----------------------------------------------------------------------------- outbox

def test_import_emits_transaction_imported_and_one_deviation_detected_per_alert(fresh):
    result = imported(fresh, sample_csv(fresh))
    events = list(reversed(outbox(fresh)))
    assert [e["event_type"] for e in events] == ["DeviationDetected"] * 5 + ["TransactionImported"]
    batch = events[-1]
    assert batch["aggregate"] == "import_batch" and batch["aggregate_id"] == str(result["batch_id"])
    assert batch["payload"] == {"batch_id": result["batch_id"], "provider": "terpel", "rows": 10, "imported": 10,
                                "duplicates": 0, "rejected": 0, "alerts": 5}
    by_vehicle = {e["payload"]["vehicle"]: e for e in events[:-1]}
    veh023 = by_vehicle["VEH023"]
    alert = _deviation(result, "VEH023")
    assert veh023["aggregate"] == "alert" and veh023["aggregate_id"] == str(alert["id"])
    assert veh023["payload"] == {"alert_id": alert["id"], "vehicle": "VEH023", "rules": ["C01"], "points": 2,
                                 "priority": "medium", "transaction_id": alert["evidence"]["transaction"]["id"]}
    assert all(e["published_at"] is None for e in events)


def test_second_load_only_emits_the_batch_event(fresh):
    content = sample_csv(fresh)
    imported(fresh, content)
    imported(fresh, content)
    types = [e["event_type"] for e in outbox(fresh)]
    assert types.count("DeviationDetected") == 5 and types.count("TransactionImported") == 2
    assert outbox(fresh)[0]["payload"]["duplicates"] == 10 and outbox(fresh)[0]["payload"]["alerts"] == 0


def test_dates_of_the_file_are_stored_in_bogota_time(fresh, db):
    imported(fresh, sample_csv(fresh))
    stored = db.execute(text("SELECT occurred_at FROM provider_transaction WHERE external_id = 'TER-900102'")).scalar_one()
    assert to_local(stored).isoformat() == f"{(today() - timedelta(days=1)).isoformat()}T07:42:35-05:00"
