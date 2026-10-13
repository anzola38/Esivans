"""Alerts of the coordinator: order by priority and points, deadlines (48 hours and the week), the
three review results with comment, author and date, roles and the precision measured per rule."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.timeutil import at, now, today

from .helpers import (COORD, FINANCE, SUPPORT, TECH, alerts, audit_items, authorize, authorized_green, decide, imported,
                      in_review, plain, review, rule, sample_csv, vehicle_alert)

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _refuel_alert(client, vehicle: str, codes: list[str]) -> dict:
    return next(a for a in alerts(client, "kind=refuel")["items"]
                if a["vehicle"]["code"] == vehicle and a["rule_codes"] == codes)


# ----------------------------------------------------------------------------- list, order and priority

def test_seed_has_19_alerts_with_these_counts(fresh):
    counts = alerts(fresh)["counts"]
    assert counts == {"total": 19, "open": 11, "reviewed": 8, "open_high": 4, "open_medium": 6, "open_low": 1,
                      "overdue": 2, "confirmed": 4, "precision": 0.5}


def test_alerts_are_ordered_open_first_then_by_priority_and_points(fresh):
    items = alerts(fresh)["items"]
    statuses = [a["status"] for a in items]
    assert statuses == ["open"] * 11 + ["reviewed"] * 8
    for group in (items[:11], items[11:]):
        keys = [(PRIORITY_RANK[a["priority"]], -a["points"]) for a in group]
        assert keys == sorted(keys)
    assert [(a["vehicle"]["code"], a["points"], a["priority"]) for a in items[:11]] == [
        ("VEH129", 8, "high"), ("VEH015", 6, "high"), ("VEH906", 5, "high"), ("VEH199", 5, "high"),
        ("VEH908", 3, "medium"), ("VEH215", 3, "medium"), ("VEH910", 3, "medium"),
        ("VEH904", 2, "medium"), ("VEH199", 2, "medium"), ("VEH911", 2, "medium"),
        ("VEH160", 1, "low")]


def test_priority_is_high_from_4_points_medium_with_2_or_3_and_low_with_1(fresh):
    for alert in alerts(fresh)["items"]:
        expected = "high" if alert["points"] >= 4 else "medium" if alert["points"] >= 2 else "low"
        assert alert["priority"] == expected, alert["vehicle"]["code"]
        assert alert["priority_label"] == {"high": "Alta", "medium": "Media", "low": "Baja"}[expected]
        assert alert["points"] == sum(r["points"] for r in alert["reasons"])
        assert all(1 <= r["points"] <= 3 for r in alert["reasons"])
        assert alert["rule_codes"] == [r["code"] for r in alert["reasons"]]
        assert alert["rule_code"] == ", ".join(alert["rule_codes"])


def test_veh129_scores_8_points_with_three_vehicle_rules(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    assert alert["kind"] == "vehicle" and alert["kind_label"] == "Vehículo"
    assert alert["rule_codes"] == ["V01", "V05", "V08"] and alert["points"] == 8 and alert["priority"] == "high"
    assert [(r["code"], r["points"]) for r in alert["reasons"]] == [("V01", 3), ("V05", 3), ("V08", 2)]
    assert plain(alert["reason"]) == (
        "V01 Rendimiento bajo: Rinde 20,3 km/gal-eq frente a la mediana de su grupo, 52,7 (61 % menos); el límite es 39,5"
        " | V05 Sin servicios en EOM: 102 tanqueos por $4,1 M sin un solo servicio en EOM en los 90 días"
        " | V08 Muchas alertas: 26 % de sus tanqueos con al menos una alerta")
    evidence = alert["evidence"]
    assert evidence["efficiency"]["value"] == 20.3 and evidence["efficiency"]["group_median"] == 52.7
    assert evidence["efficiency"]["low_limit"] == 39.5 and evidence["efficiency"]["status"] == "low"
    assert evidence["stats"]["refuels_90d"] == 102 and evidence["stats"]["amount_90d"] == 4128960
    assert evidence["stats"]["services_90d"] == 0 and evidence["ledger_url"] == "/api/vehicles/VEH129/ledger"
    assert alert["rules_version"] == "v1" and alert["status_label"] == "Abierta"


def test_veh215_yields_24_against_a_limit_of_31_4(fresh):
    alert = vehicle_alert(fresh, "VEH215")
    assert alert["rule_codes"] == ["V01"] and alert["points"] == 3 and alert["priority"] == "medium"
    assert plain(alert["reason"]) == ("V01 Rendimiento bajo: Rinde 24,0 km/gal frente a la mediana de su grupo, 41,8 "
                                      "(43 % menos); el límite es 31,4")
    assert alert["evidence"]["efficiency"]["value"] == 24.0 and alert["evidence"]["efficiency"]["low_limit"] == 31.4


def test_refuel_alert_keeps_the_transaction_and_the_previous_one_as_evidence(fresh):
    alert = _refuel_alert(fresh, "VEH199", ["R05", "R08"])
    assert alert["kind"] == "refuel" and alert["kind_label"] == "Tanqueo" and alert["points"] == 5
    assert alert["reason"] == ("R05 Recarga sin recorrido: cargó 6,6 m³ de GNV con 20 km desde su carga anterior "
                               "(típica 9,7 m³) | R08 Sin servicios en EOM: sin servicios con desplazamiento 24 h "
                               "antes ni después")
    evidence = alert["evidence"]
    assert evidence["transaction"]["quantity"] == 6.6 and evidence["transaction"]["timestamp"][11:16] == "15:17"
    assert evidence["transaction"]["odometer"] - evidence["previous_transaction"]["odometer"] == 20
    assert evidence["source"] == "Prueba con datos históricos"


@pytest.mark.parametrize("query, total", [("status=open", 11), ("status=reviewed", 8), ("kind=vehicle", 9),
                                          ("kind=refuel", 10), ("kind=reconciliation", 0), ("priority=high", 6),
                                          ("priority=medium", 10), ("priority=low", 3),
                                          ("status=open&kind=vehicle&priority=high", 2)])
def test_alert_filters(fresh, query, total):
    listing = alerts(fresh, query)
    assert listing["counts"]["total"] == total == len(listing["items"])
    for key, value in (pair.split("=") for pair in query.split("&")):
        assert all(a[key] == value for a in listing["items"])


def test_unknown_filter_value_is_a_validation_error(fresh):
    response = fresh.get("/api/alerts?priority=urgente", headers=COORD)
    assert response.status_code == 422 and response.json()["code"] == "validation_error"


# ----------------------------------------------------------------------------- deadlines

def test_high_priority_is_due_in_48_hours_and_the_rest_within_the_week(fresh):
    for alert in alerts(fresh)["items"]:
        allowed = datetime.fromisoformat(alert["due_at"]) - datetime.fromisoformat(alert["created_at"])
        if alert["priority"] == "high":
            assert allowed == timedelta(hours=48) and alert["deadline_label"] == "48 horas"
        else:
            assert allowed == timedelta(days=7) and alert["deadline_label"] == "En la semana"


def test_high_priority_alerts_older_than_48_hours_are_marked_overdue(fresh):
    listing = alerts(fresh, "status=open")
    overdue = [(a["vehicle"]["code"], a["rule_codes"]) for a in listing["items"] if a["overdue"]]
    assert overdue == [("VEH015", ["V01", "V05"]), ("VEH906", ["R05", "R11"])]
    veh015 = vehicle_alert(fresh, "VEH015")
    assert veh015["created_at"] == at(today() - timedelta(days=3), "07:00").isoformat()
    assert veh015["due_at"] == at(today() - timedelta(days=1), "07:00").isoformat()
    assert veh015["hours_to_due"] < 0
    fresh_alert = vehicle_alert(fresh, "VEH129")
    assert fresh_alert["created_at"] == at(today() - timedelta(days=1), "07:00").isoformat()
    assert fresh_alert["overdue"] is False and fresh_alert["hours_to_due"] > 0


def test_alert_becomes_overdue_exactly_when_its_deadline_passes(fresh, clock):
    due = datetime.fromisoformat(vehicle_alert(fresh, "VEH129")["due_at"])
    clock.advance(seconds=(due - now()).total_seconds() - 60)            # one minute before the 48 hours
    before = vehicle_alert(fresh, "VEH129")
    assert before["overdue"] is False and before["hours_to_due"] == 0.0
    clock.advance(seconds=120)                                           # one minute after
    after = vehicle_alert(fresh, "VEH129")
    assert after["overdue"] is True and after["hours_to_due"] <= 0
    assert alerts(fresh)["counts"]["overdue"] == 4                       # VEH015, VEH906, VEH129 and VEH199 (R05, R08)


def test_alerts_of_the_week_become_overdue_after_seven_days(fresh, clock):
    alert = vehicle_alert(fresh, "VEH215")
    due = datetime.fromisoformat(alert["due_at"])
    assert alert["overdue"] is False and due == at(today() + timedelta(days=6), "07:00")
    clock.advance(seconds=(due - now()).total_seconds() - 60)
    assert vehicle_alert(fresh, "VEH215")["overdue"] is False
    clock.advance(seconds=120)
    assert vehicle_alert(fresh, "VEH215")["overdue"] is True
    assert alerts(fresh)["counts"]["overdue"] == alerts(fresh)["counts"]["open"] == 11


def test_reviewed_alerts_are_never_overdue(fresh, clock):
    clock.advance(days=30)
    reviewed = alerts(fresh, "status=reviewed")["items"]
    assert len(reviewed) == 8
    assert all(a["overdue"] is False and a["hours_to_due"] is None for a in reviewed)


# ----------------------------------------------------------------------------- review: the three results

@pytest.mark.parametrize("sent, stored, label", [
    ("Confirmado", "confirmed", "Confirmado"), ("confirmed", "confirmed", "Confirmado"),
    ("Justificado", "justified", "Justificado"), ("justified", "justified", "Justificado"),
    ("Error de dato", "data_error", "Error de dato"), ("data_error", "data_error", "Error de dato"),
])
def test_review_records_result_comment_author_and_date(fresh, sent, stored, label):
    alert = vehicle_alert(fresh, "VEH129")
    response = review(fresh, alert["id"], sent, "Se revisó con la evidencia del libro único.")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == alert["id"] and body["status"] == "reviewed" and body["status_label"] == "Revisada"
    assert body["review_result"] == stored and body["review_result_label"] == label
    assert body["review_comment"] == "Se revisó con la evidencia del libro único."
    assert body["reviewed_by"] == "Andres Molina"
    assert abs((now() - datetime.fromisoformat(body["reviewed_at"])).total_seconds()) < 60
    assert body["overdue"] is False and body["hours_to_due"] is None
    # The rest of the alert is untouched.
    assert body["points"] == 8 and body["rule_codes"] == ["V01", "V05", "V08"] and body["reason"] == alert["reason"]
    stored_alert = vehicle_alert(fresh, "VEH129")
    assert stored_alert == body


def test_review_moves_the_alert_out_of_the_open_ones(fresh):
    alert = vehicle_alert(fresh, "VEH015")
    review(fresh, alert["id"], "justified", "Opera en una ruta que no registra EOM.")
    counts = alerts(fresh)["counts"]
    assert counts["open"] == 10 and counts["reviewed"] == 9 and counts["open_high"] == 3 and counts["overdue"] == 1
    assert counts["confirmed"] == 4 and counts["precision"] == 0.444          # 4 confirmed of 9 reviewed
    assert alert["id"] not in [a["id"] for a in alerts(fresh, "status=open")["items"]]


def test_reviewer_name_is_decoded_from_the_header(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    headers = {"X-Demo-Role": "coordinator", "X-Demo-User": "Mar%C3%ADa%20Salcedo"}
    assert review(fresh, alert["id"], headers=headers).json()["reviewed_by"] == "María Salcedo"


@pytest.mark.parametrize("body", [{"review_result": "confirmed"}, {"review_result": "confirmed", "comment": ""},
                                  {"review_result": "confirmed", "comment": "ok"},
                                  {"review_result": "confirmed", "comment": "x" * 501}, {"comment": "Sin resultado"}])
def test_comment_and_result_are_mandatory(fresh, body):
    alert = vehicle_alert(fresh, "VEH129")
    response = fresh.patch(f"/api/alerts/{alert['id']}", json=body, headers=COORD)
    assert response.status_code == 422 and response.json()["code"] == "validation_error"
    assert vehicle_alert(fresh, "VEH129")["status"] == "open"


def test_comment_made_only_of_spaces_is_not_a_comment(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    response = review(fresh, alert["id"], "confirmed", "      ")
    assert response.status_code == 422 and response.json()["code"] == "comment_required"
    assert vehicle_alert(fresh, "VEH129")["status"] == "open"
    assert audit_items(fresh, "action=alert.reviewed") == []


def test_comment_of_three_characters_is_the_minimum(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    assert review(fresh, alert["id"], "confirmed", "ok.").status_code == 200


def test_unknown_result_is_rejected(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    response = review(fresh, alert["id"], "cerrado", "Comentario válido")
    assert response.status_code == 422
    assert response.json() == {"detail": "El resultado debe ser Confirmado, Justificado o Error de dato.",
                               "code": "invalid_review_result", "allowed": ["confirmed", "justified", "data_error"]}
    assert vehicle_alert(fresh, "VEH129")["status"] == "open"


def test_unknown_alert_is_a_404(fresh):
    response = review(fresh, 9999)
    assert response.status_code == 404 and response.json()["code"] == "alert_not_found"


@pytest.mark.xfail(strict=True, reason=(
    "HU-17 pide registrar el resultado una vez, con autor y fecha. Hoy PATCH /alerts/{id} deja volver a registrar una "
    "alerta ya revisada y pisa resultado, comentario, autor y fecha (el contrato lo documenta como permitido y el "
    "rastro queda solo en la bitácora). No se cambia sin decisión de producto: bloquearlo cambia lo que ve el presentador."))
def test_reviewed_alert_cannot_be_reviewed_again(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    assert review(fresh, alert["id"], "confirmed", "Se envía a revisión mecánica.").status_code == 200
    again = review(fresh, alert["id"], "justified", "Cambio de opinión.", headers=TECH)
    assert again.status_code == 409
    current = vehicle_alert(fresh, "VEH129")
    assert current["review_result"] == "confirmed" and current["reviewed_by"] == "Andres Molina"


def test_every_review_of_an_alert_stays_in_the_audit_log(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    review(fresh, alert["id"], "confirmed", "Se envía a revisión mecánica.")
    review(fresh, alert["id"], "justified", "Mantenimiento explicó el consumo.", headers=TECH)
    entries = audit_items(fresh, "action=alert.reviewed")
    assert [(e["actor"], e["after"]["review_result"]) for e in reversed(entries)] == [
        ("Andres Molina", "confirmed"), ("Laura Gomez", "justified")]
    assert entries[0]["before"] == {"status": "reviewed", "review_result": "confirmed",
                                    "review_comment": "Se envía a revisión mecánica.", "reviewed_by": "Andres Molina"}


# ----------------------------------------------------------------------------- roles

def test_coordinator_and_technician_can_review(fresh):
    first = vehicle_alert(fresh, "VEH129")
    second = vehicle_alert(fresh, "VEH015")
    assert review(fresh, first["id"], headers=COORD).json()["reviewed_by"] == "Andres Molina"
    assert review(fresh, second["id"], headers=TECH).json()["reviewed_by"] == "Laura Gomez"


@pytest.mark.parametrize("headers", [FINANCE, SUPPORT])
def test_finance_and_support_cannot_review(fresh, headers):
    alert = vehicle_alert(fresh, "VEH129")
    response = review(fresh, alert["id"], headers=headers)
    assert response.status_code == 403 and response.json()["code"] == "forbidden"
    assert response.json()["allowed_roles"] == ["coordinator", "technician"]
    assert vehicle_alert(fresh, "VEH129")["status"] == "open"
    assert audit_items(fresh, "action=access.denied")[0]["after"]["path"] == f"/api/alerts/{alert['id']}"


@pytest.mark.parametrize("headers", [TECH, COORD, FINANCE, SUPPORT])
def test_every_role_can_read_the_alerts(fresh, headers):
    assert alerts(fresh, headers=headers)["counts"]["total"] == 19


# ----------------------------------------------------------------------------- precision per rule

def test_precision_per_rule_is_confirmed_over_reviewed(fresh):
    catalog = {r["code"]: (r["reviewed"], r["confirmed"], r["precision"])
               for r in fresh.get("/api/rules", headers=COORD).json()["items"]}
    assert catalog["R08"] == (3, 2, 0.667)          # two confirmed and one justified
    assert catalog["R01"] == (2, 1, 0.5)            # one confirmed and one data error
    assert catalog["R05"] == (1, 1, 1.0) and catalog["R09"] == (1, 1, 1.0) and catalog["R11"] == (1, 1, 1.0)
    assert catalog["R06"] == (1, 0, 0.0)            # its only review was justified
    assert catalog["V03"] == (1, 1, 1.0) and catalog["V07"] == (1, 0, 0.0)
    for code in ("R02", "R03", "R04", "R07", "R10", "R12", "R13", "R14", "C01", "C02", "V01", "V02", "V04", "V05",
                 "V06", "V08"):
        assert catalog[code] == (0, 0, None), code          # nothing reviewed: no precision yet


def test_precision_changes_with_each_review(fresh):
    review(fresh, vehicle_alert(fresh, "VEH129")["id"], "confirmed", "Se envía a revisión mecánica.")
    for code in ("V01", "V05", "V08"):
        current = rule(fresh, code)
        assert (current["reviewed"], current["confirmed"], current["precision"]) == (1, 1, 1.0)

    review(fresh, vehicle_alert(fresh, "VEH015")["id"], "justified", "Ruta sin registro en EOM.")
    assert (rule(fresh, "V01")["reviewed"], rule(fresh, "V01")["confirmed"], rule(fresh, "V01")["precision"]) == (2, 1, 0.5)
    assert rule(fresh, "V05")["precision"] == 0.5 and rule(fresh, "V08")["precision"] == 1.0

    review(fresh, vehicle_alert(fresh, "VEH215")["id"], "data_error", "Odómetro mal digitado en la estación.")
    assert (rule(fresh, "V01")["reviewed"], rule(fresh, "V01")["confirmed"], rule(fresh, "V01")["precision"]) == (3, 1, 0.333)

    review(fresh, _refuel_alert(fresh, "VEH199", ["R05", "R08"])["id"], "justified", "Apoyo a otra zona.")
    assert (rule(fresh, "R05")["reviewed"], rule(fresh, "R05")["confirmed"], rule(fresh, "R05")["precision"]) == (2, 1, 0.5)
    assert (rule(fresh, "R08")["reviewed"], rule(fresh, "R08")["confirmed"], rule(fresh, "R08")["precision"]) == (4, 2, 0.5)


def test_precision_of_a_reconciliation_rule_appears_after_reviewing_its_alert(fresh):
    result = imported(fresh, sample_csv(fresh))
    veh023 = next(d for d in result["deviations"] if d["vehicle"]["code"] == "VEH023")
    assert rule(fresh, "C01")["precision"] is None
    review(fresh, veh023["id"], "Confirmado", "Se habló con la conductora: debía cargar Corriente.")
    c01 = rule(fresh, "C01")
    assert (c01["reviewed"], c01["confirmed"], c01["precision"]) == (1, 1, 1.0)
    assert alerts(fresh, "kind=reconciliation")["counts"]["reviewed"] == 1


# ----------------------------------------------------------------------------- C03: red request authorized

def _red_alerts(client) -> list[dict]:
    return [a for a in alerts(client)["items"] if a["rule_codes"] == ["C03"]]


def _authorized_red(client, **decision) -> dict:
    request = in_review(client, "VEH199")
    assert request["evaluation"]["traffic_light"] == "red"
    assert decide(client, request["id"], **decision).status_code == 200
    assert _red_alerts(client) == []  # the alert is born with the enablement, not with the decision
    response = authorize(client, request["id"], "TER-ROJO-1")
    assert response.status_code == 200, response.text
    return response.json()


def test_red_request_adjusted_and_enabled_leaves_one_high_alert_for_the_coordinator(fresh):
    request = _authorized_red(fresh, action="adjust", amount=20000, reason="Apoyo nocturno confirmado con el coordinador")
    assert request["status"] == "authorized" and request["authorization"]["amount"] == 20000
    [alert] = _red_alerts(fresh)
    assert alert["kind"] == "refuel" and alert["entity"] == "fuel_request" and alert["entity_id"] == request["id"]
    assert alert["vehicle"]["code"] == "VEH199" and alert["status"] == "open"
    # same 7 points the technician saw on the request (R05 + R08 + R09)
    assert alert["points"] == 7 and alert["priority"] == "high" and alert["deadline_label"] == "48 horas"
    due, created = datetime.fromisoformat(alert["due_at"]), datetime.fromisoformat(alert["created_at"])
    assert due - created == timedelta(hours=48)
    assert plain(alert["reasons"][0]["explanation"]) == (
        'El técnico Laura Gomez autorizó $20.000 a VEH199 con el semáforo en rojo (7 puntos: R05, R08, R09). '
        'Motivo: "Apoyo nocturno confirmado con el coordinador". Valor sugerido: $10.000.')
    assert plain(alert["reason"]).startswith("C03 Autorización de solicitud en rojo: El técnico Laura Gomez")
    assert alert["evidence"]["request"]["reference"] == "TER-ROJO-1"
    log = [i for i in audit_items(fresh, f"request_id={request['id']}") if i["action"] == "alert.created"]
    assert len(log) == 1 and log[0]["actor"] == "sistema" and log[0]["after"]["alert_id"] == alert["id"]
    assert rule(fresh, "C03")["stage"] == "after_authorization" and rule(fresh, "C03")["points"] == 4


def test_red_request_approved_with_reason_also_leaves_the_alert(fresh):
    _authorized_red(fresh, action="approve", reason="Servicio urgente confirmado")
    [alert] = _red_alerts(fresh)
    assert "autorizó $10.000 a VEH199" in plain(alert["reason"]) and alert["priority"] == "high"


def test_red_request_rejected_leaves_no_alert(fresh):
    request = in_review(fresh, "VEH199")
    before = alerts(fresh)["counts"]["total"]
    assert decide(fresh, request["id"], action="reject", reason="Sin servicio asignado").status_code == 200
    assert authorize(fresh, request["id"]).status_code == 409
    assert _red_alerts(fresh) == [] and alerts(fresh)["counts"]["total"] == before


def test_green_request_authorized_leaves_no_alert(fresh):
    before = alerts(fresh)["counts"]["total"]
    authorized_green(fresh)
    assert _red_alerts(fresh) == [] and alerts(fresh)["counts"]["total"] == before


def test_red_authorization_alert_is_created_only_once(fresh, db):
    from app.models import FuelRequest
    from app.reconciliation.service import flag_red_authorization

    request = _authorized_red(fresh, action="adjust", amount=20000, reason="Apoyo nocturno confirmado con el coordinador")
    assert authorize(fresh, request["id"], "TER-ROJO-2").status_code == 409  # a second enablement does not pass
    assert flag_red_authorization(db, db.get(FuelRequest, request["id"])) is None
    db.commit()
    assert len(_red_alerts(fresh)) == 1
