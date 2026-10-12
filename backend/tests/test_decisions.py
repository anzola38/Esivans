"""Decision of the technician: one-click approval only in green, mandatory reason outside the
recommendation, the cap, a single decision per request, roles and the message to the driver."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.models import Decision
from app.timeutil import now

from .helpers import (COORD, FINANCE, SUPPORT, TECH, WA, audit_items, authorize, conversation, decide, detail,
                      in_review, kinds, outbox, play, queue)


# ----------------------------------------------------------------------------- one click (green)

def test_green_request_is_approved_in_one_click_with_the_suggested_amount(fresh):
    request = in_review(fresh, "GREEN")
    assert request["one_click_allowed"] is True
    response = decide(fresh, request["id"], action="approve")
    assert response.status_code == 200, response.text
    body = response.json()
    decision = body["decision"]
    assert decision["action"] == "approve" and decision["action_label"] == "Aprobada"
    assert decision["amount"] == 90000 and decision["one_click"] is True and decision["reason"] is None
    assert decision["decided_by"] == "Laura Gomez" and decision["role"] == "technician"
    assert decision["role_label"] == "Técnico de Control y Monitoreo"
    assert abs((now() - datetime.fromisoformat(decision["decided_at"])).total_seconds()) < 60
    # Approved but not enabled yet: still open, in the "pending enablement" stage.
    assert body["status"] == "in_review" and body["stage"] == "pending_enablement" and body["stage_label"] == "Por habilitar"
    assert body["one_click_allowed"] is False and body["decision_action"] == "approve" and body["decided_by"] == "Laura Gomez"
    assert body["sla_remaining_seconds"] is None and body["sla_breached"] is False


def test_approval_alone_does_not_message_the_driver_until_the_enablement(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    assert kinds(conversation(fresh, WA["GREEN"]))[-1] == "in_review"
    authorize(fresh, request["id"], "TER-MSG-0001")
    assert kinds(conversation(fresh, WA["GREEN"]))[-1] == "authorization"


def test_approving_with_the_same_amount_as_suggested_is_still_one_click(fresh):
    request = in_review(fresh, "GREEN")
    decision = decide(fresh, request["id"], action="approve", amount=90000).json()["decision"]
    assert decision["action"] == "approve" and decision["one_click"] is True and decision["amount"] == 90000


def test_green_approval_with_a_reason_is_recorded_but_is_not_one_click(fresh):
    request = in_review(fresh, "GREEN")
    decision = decide(fresh, request["id"], action="approve", reason="Confirmado con el conductor").json()["decision"]
    assert decision["action"] == "approve" and decision["one_click"] is False
    assert decision["reason"] == "Confirmado con el conductor"


def test_decision_counts_leave_the_queue_colors(fresh):
    green = in_review(fresh, "GREEN")
    in_review(fresh, "VEH015")
    in_review(fresh, "VEH199")
    assert queue(fresh)["counts"] == {"total": 3, "in_review": 3, "green": 1, "yellow": 1, "red": 1, "sla_breached": 0}
    decide(fresh, green["id"], action="approve")
    listing = queue(fresh)
    assert listing["counts"] == {"total": 3, "in_review": 3, "green": 0, "yellow": 1, "red": 1, "sla_breached": 0}
    assert {i["vehicle"]["code"]: i["stage"] for i in listing["items"]} == {
        "VEH901": "pending_enablement", "VEH015": "in_review", "VEH199": "in_review"}


# ----------------------------------------------------------------------------- mandatory reason

def test_yellow_request_cannot_be_approved_without_a_reason(fresh):
    request = in_review(fresh, "VEH015")
    assert request["traffic_light"] == "yellow" and request["one_click_allowed"] is False
    response = decide(fresh, request["id"], action="approve")
    assert response.status_code == 422
    assert response.json() == {"detail": "El semáforo no está en verde: para autorizar debes dejar el motivo.",
                               "code": "reason_required", "traffic_light": "yellow"}
    assert detail(fresh, request["id"])["decision"] is None

    approved = decide(fresh, request["id"], action="approve", reason="Kilometraje corregido y confirmado")
    assert approved.status_code == 200
    decision = approved.json()["decision"]
    assert decision["action"] == "approve" and decision["one_click"] is False and decision["amount"] == 50000
    assert decision["reason"] == "Kilometraje corregido y confirmado"


def test_red_request_cannot_be_approved_without_a_reason(fresh):
    request = in_review(fresh, "VEH199")
    response = decide(fresh, request["id"], action="approve")
    assert response.status_code == 422
    assert response.json()["code"] == "reason_required" and response.json()["traffic_light"] == "red"
    # No rule blocks: with the reason the technician can still approve a red request.
    approved = decide(fresh, request["id"], action="approve", reason="Apoyo nocturno confirmado por radio")
    assert approved.status_code == 200 and approved.json()["decision"]["amount"] == 10000


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_adjusting_needs_a_reason_even_in_green(fresh, reason):
    request = in_review(fresh, "GREEN")
    body = {"action": "adjust", "amount": 70000}
    if reason is not None:
        body["reason"] = reason
    response = decide(fresh, request["id"], **body)
    assert response.status_code == 422
    assert response.json() == {"detail": "Ajustar el valor exige un motivo.", "code": "reason_required"}


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_rejecting_needs_a_reason(fresh, reason):
    request = in_review(fresh, "GREEN")
    body = {"action": "reject"}
    if reason is not None:
        body["reason"] = reason
    response = decide(fresh, request["id"], **body)
    assert response.status_code == 422
    assert response.json() == {"detail": "Rechazar exige un motivo: el conductor lo recibe en el chat.",
                               "code": "reason_required"}
    assert detail(fresh, request["id"])["status"] == "in_review"


def test_approving_with_a_different_amount_is_an_adjustment_and_needs_a_reason(fresh):
    request = in_review(fresh, "GREEN")
    missing = decide(fresh, request["id"], action="approve", amount=70000)
    assert missing.status_code == 422 and missing.json()["code"] == "reason_required"
    adjusted = decide(fresh, request["id"], action="approve", amount=70000, reason="Solo cubre medio turno")
    assert adjusted.status_code == 200
    decision = adjusted.json()["decision"]
    assert decision["action"] == "adjust" and decision["action_label"] == "Ajustada"
    assert decision["amount"] == 70000 and decision["one_click"] is False and decision["original_amount"] == 90000


# ----------------------------------------------------------------------------- adjust: amount and cap

def test_adjust_keeps_the_original_calculation(fresh):
    request = in_review(fresh, "VEH199")
    original = request["calculation"]
    response = decide(fresh, request["id"], action="adjust", amount=20000, reason="Apoyo nocturno confirmado por radio")
    assert response.status_code == 200
    body = response.json()
    decision = body["decision"]
    assert decision["action"] == "adjust" and decision["amount"] == 20000 and decision["one_click"] is False
    assert decision["original_amount"] == 10000
    assert decision["original_calculation"] == original
    assert [s["key"] for s in decision["original_calculation"]["steps"]][-1] == "amount"
    # The evaluation is not rewritten: the suggestion stays next to the decision.
    assert body["suggested_amount"] == 10000 and body["calculation"] == original
    assert body["enablement"]["amount"] == 20000 and body["stage"] == "pending_enablement"


def test_adjust_needs_an_amount_greater_than_zero(fresh):
    request = in_review(fresh, "GREEN")
    for body in ({"action": "adjust", "reason": "Prueba"}, {"action": "adjust", "amount": 0, "reason": "Prueba"}):
        response = decide(fresh, request["id"], **body)
        assert response.status_code == 422
        assert response.json() == {"detail": "Indica el valor ajustado en pesos (mayor a cero).", "code": "amount_required"}
    negative = decide(fresh, request["id"], action="adjust", amount=-1000, reason="Prueba")
    assert negative.status_code == 422 and negative.json()["code"] == "validation_error"
    assert negative.json()["errors"][0]["field"] == "amount"


def test_adjust_above_the_cap_is_rejected_and_at_the_cap_is_accepted(fresh):
    request = in_review(fresh, "GREEN")
    assert request["calculation"]["cap_amount"] == 190000
    above = decide(fresh, request["id"], action="adjust", amount=190001, reason="Ruta larga")
    assert above.status_code == 422
    assert above.json() == {"detail": "El valor supera el tope del vehículo ($190.000).", "code": "above_cap",
                            "cap_amount": 190000}
    assert detail(fresh, request["id"])["decision"] is None
    at_cap = decide(fresh, request["id"], action="adjust", amount=190000, reason="Ruta larga")
    assert at_cap.status_code == 200 and at_cap.json()["decision"]["amount"] == 190000


def test_cap_of_a_gas_vehicle_is_40000(fresh):
    request = in_review(fresh, "VEH199")
    above = decide(fresh, request["id"], action="adjust", amount=50000, reason="Prueba")
    assert above.status_code == 422 and above.json()["cap_amount"] == 40000
    assert above.json()["detail"] == "El valor supera el tope del vehículo ($40.000)."


# ----------------------------------------------------------------------------- reject

def test_rejection_closes_the_request_and_tells_the_driver_the_reason(fresh):
    request = in_review(fresh, "VEH199")
    response = decide(fresh, request["id"], action="reject", reason="Sin servicio que respalde la carga.")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected" and body["status_label"] == "Rechazada" and body["stage"] == "rejected"
    assert body["closed_at"] is not None and body["enablement"] is None and body["authorization"] is None
    decision = body["decision"]
    assert decision["action"] == "reject" and decision["amount"] is None and decision["one_click"] is False
    assert decision["reason"] == "Sin servicio que respalde la carga."
    assert body["status_history"][-1]["status"] == "rejected"
    assert body["status_history"][-1]["note"] == "Rechazada por Laura Gomez: Sin servicio que respalde la carga."
    last = conversation(fresh, WA["VEH199"])["messages"][-1]
    assert last["kind"] == "rejection"
    assert last["text"] == ("Wilson, tu solicitud no fue autorizada. Motivo: Sin servicio que respalde la carga. "
                            "Si necesitas ayuda, responde este mensaje y te atiende el técnico de turno.")
    assert conversation(fresh, WA["VEH199"])["request"]["is_open"] is False
    assert queue(fresh, "in_review")["items"] == []


def test_rejected_request_cannot_be_enabled(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="reject", reason="Ya tanqueó en la mañana")
    response = authorize(fresh, request["id"], "TER-NO-0001")
    assert response.status_code == 409 and response.json()["code"] == "not_approved"


def test_unregistered_number_can_only_be_rejected(fresh):
    request_id = play(fresh, "UNREGISTERED")["request"]["id"]
    for body in ({"action": "approve", "reason": "Lo conozco"}, {"action": "adjust", "amount": 50000, "reason": "x"}):
        response = decide(fresh, request_id, **body)
        assert response.status_code == 422 and response.json()["code"] == "vehicle_required"
    rejected = decide(fresh, request_id, action="reject", reason="No es conductor de la empresa")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    last = conversation(fresh, WA["UNREGISTERED"])["messages"][-1]
    assert last["kind"] == "rejection"
    assert last["text"].startswith("Hola, tu solicitud no fue autorizada. Motivo: No es conductor de la empresa.")


# ----------------------------------------------------------------------------- a single decision

def test_second_decision_is_rejected_with_who_decided(fresh, db):
    request = in_review(fresh, "GREEN")
    first = decide(fresh, request["id"], action="approve").json()["decision"]
    second = decide(fresh, request["id"], action="reject", reason="Otro criterio", headers=COORD)
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "already_decided"
    assert body["detail"].startswith("Esta solicitud ya fue decidida por Laura Gomez (aprobada) el ")
    assert body["decision"]["decided_by"] == "Laura Gomez" and body["decision"]["action"] == "approve"
    # Nothing changed: same decision, still one, and the request was not rejected.
    after = detail(fresh, request["id"])
    assert after["decision"] == first and after["status"] == "in_review"
    assert db.scalar(select(func.count()).select_from(Decision)) == 1
    assert [e["event_type"] for e in outbox(fresh)].count("DecisionRecorded") == 1


def test_second_decision_after_a_rejection_is_also_a_409(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="reject", reason="Duplicada", headers=COORD)
    again = decide(fresh, request["id"], action="approve")
    assert again.status_code == 409 and again.json()["code"] == "already_decided"
    assert "Andres Molina (rechazada)" in again.json()["detail"]


def test_request_that_is_not_in_review_cannot_be_decided(fresh):
    request_id = play(fresh, "GREEN", steps=2)["request"]["id"]
    response = decide(fresh, request_id, action="approve")
    assert response.status_code == 409
    assert response.json() == {"detail": ("La solicitud todavía no está en revisión: el asistente sigue reuniendo la "
                                          "información."), "code": "not_in_review", "status": "awaiting_evidence"}


def test_unknown_request_is_a_404(fresh):
    response = decide(fresh, 999, action="approve")
    assert response.status_code == 404 and response.json()["code"] == "request_not_found"
    assert fresh.get("/api/requests/999", headers=TECH).status_code == 404


def test_unknown_action_is_a_validation_error(fresh):
    request = in_review(fresh, "GREEN")
    response = decide(fresh, request["id"], action="autoapprove")
    assert response.status_code == 422 and response.json()["code"] == "validation_error"
    assert response.json()["errors"][0]["field"] == "action"


# ----------------------------------------------------------------------------- roles

@pytest.mark.parametrize("headers, label", [(FINANCE, "Administración y finanzas"), (SUPPORT, "Soporte")])
def test_finance_and_support_cannot_decide(fresh, headers, label):
    request = in_review(fresh, "GREEN")
    response = decide(fresh, request["id"], headers=headers, action="approve")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "forbidden" and body["allowed_roles"] == ["technician", "coordinator"]
    assert body["detail"] == (f"Tu rol ({label}) no puede hacer esta acción. Roles permitidos: "
                              "Técnico de Control y Monitoreo, Coordinador.")
    assert detail(fresh, request["id"])["decision"] is None
    denied = audit_items(fresh, "action=access.denied")[0]
    assert denied["actor"] == headers["X-Demo-User"] and denied["role"] == headers["X-Demo-Role"]
    assert denied["after"] == {"method": "POST", "path": f"/api/requests/{request['id']}/decision",
                               "allowed_roles": ["technician", "coordinator"]}
    assert denied["summary"] == f"{label} intentó POST /api/requests/{request['id']}/decision sin permiso"


def test_coordinator_can_decide(fresh):
    request = in_review(fresh, "GREEN")
    response = decide(fresh, request["id"], headers=COORD, action="approve")
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["decided_by"] == "Andres Molina" and decision["role"] == "coordinator"
    assert decision["role_label"] == "Coordinador" and decision["one_click"] is True


def test_every_role_can_read_the_queue_and_the_detail(fresh):
    request = in_review(fresh, "GREEN")
    for headers in (TECH, COORD, FINANCE, SUPPORT):
        assert queue(fresh, "in_review", headers)["counts"]["green"] == 1
        assert detail(fresh, request["id"], headers)["suggested_amount"] == 90000


def test_role_headers_default_to_technician_and_decode_the_user_name(fresh):
    request = in_review(fresh, "GREEN")
    default = fresh.post(f"/api/requests/{request['id']}/decision", json={"action": "approve"})
    assert default.status_code == 200
    assert default.json()["decision"]["decided_by"] == "Laura Gómez" and default.json()["decision"]["role"] == "technician"

    assert fresh.post("/api/dev/reset").status_code == 200
    request = in_review(fresh, "GREEN")
    encoded = {"X-Demo-Role": "coordinator", "X-Demo-User": "Andr%C3%A9s%20Molina"}
    assert decide(fresh, request["id"], headers=encoded, action="approve").json()["decision"]["decided_by"] == "Andrés Molina"


def test_unknown_role_is_a_400(fresh):
    response = fresh.get("/api/requests", headers={"X-Demo-Role": "admin"})
    assert response.status_code == 400 and response.json()["code"] == "unknown_role"


def test_unknown_queue_filter_is_a_422(fresh):
    response = fresh.get("/api/requests?status=pendiente", headers=TECH)
    assert response.status_code == 422 and response.json()["code"] == "unknown_status"


# ----------------------------------------------------------------------------- record of the decision

def test_decision_is_recorded_in_the_audit_log_with_before_after_and_rules_version(fresh):
    request = in_review(fresh, "VEH199")
    decide(fresh, request["id"], action="adjust", amount=20000, reason="Apoyo nocturno confirmado por radio")
    entry = audit_items(fresh, "action=decision")[0]
    assert entry["action"] == "decision.adjust" and entry["entity"] == "decision" and entry["request_id"] == request["id"]
    assert entry["actor"] == "Laura Gomez" and entry["role"] == "technician"
    assert entry["before"] == {"suggested_amount": 10000, "traffic_light": "red", "points": 7, "rules_version": "v1"}
    assert entry["after"] == {"action": "adjust", "amount": 20000, "one_click": False,
                              "reason": "Apoyo nocturno confirmado por radio"}
    assert entry["summary"] == ("Laura Gomez ajustó la solicitud por $20.000 (sugerido $10.000). "
                                "Motivo: Apoyo nocturno confirmado por radio")


def test_decision_emits_decision_recorded_in_the_outbox(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    event = outbox(fresh)[0]
    assert event["event_type"] == "DecisionRecorded" and event["aggregate"] == "request"
    assert event["aggregate_id"] == str(request["id"]) and event["published_at"] is None
    assert event["payload"] == {"request_id": request["id"], "action": "approve", "amount": 90000,
                                "decided_by": "Laura Gomez", "traffic_light": "green", "one_click": True}


def test_queue_puts_open_requests_first_and_closed_ones_last(fresh):
    green = in_review(fresh, "GREEN")
    red = in_review(fresh, "VEH199")
    yellow = in_review(fresh, "VEH015")
    decide(fresh, red["id"], action="reject", reason="Sin soporte")
    listing = queue(fresh, None)
    assert [i["id"] for i in listing["items"]] == [green["id"], yellow["id"], red["id"]]
    assert [i["status"] for i in listing["items"]] == ["in_review", "in_review", "rejected"]
    assert [i["id"] for i in queue(fresh, "open")["items"]] == [green["id"], yellow["id"]]
    assert [i["id"] for i in queue(fresh, "closed")["items"]] == [red["id"]]
    assert [i["id"] for i in queue(fresh, "rejected,authorized")["items"]] == [red["id"]]
