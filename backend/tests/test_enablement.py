"""Enablement of the chip or card (the technician does it in the MVP): prefilled values, reference,
2-hour validity, only once and only after approving, and the message the driver receives."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.timeutil import at, now, today

from .helpers import (COORD, FINANCE, SUPPORT, TECH, WA, audit_items, authorize, authorized_green, conversation, decide,
                      detail, in_review, plain, play, queue, send)


def test_enablement_panel_is_prefilled_after_approving(fresh):
    request = in_review(fresh, "GREEN")
    assert request["enablement"] is None                     # nothing to enable before the decision
    body = decide(fresh, request["id"], action="approve").json()
    assert body["enablement"] == {
        "provider": "terpel", "provider_label": "Terpel", "payment_method": "chip",
        "plate": "ZZA901", "vehicle_code": "VEH901", "product": "Gasolina Corriente",
        "amount": 90000, "valid_minutes": 120,
        "suggested_reference": f"TER-{now():%y%m%d}-{request['id']:04d}",
    }
    assert body["authorization"] is None and body["status"] == "in_review"


def test_enablement_panel_carries_the_adjusted_amount_and_the_gas_product(fresh):
    request = in_review(fresh, "VEH199")
    body = decide(fresh, request["id"], action="adjust", amount=20000, reason="Apoyo nocturno confirmado por radio").json()
    enablement = body["enablement"]
    assert enablement["amount"] == 20000 and enablement["product"] == "GNV"
    assert enablement["plate"] == "ZZA199" and enablement["vehicle_code"] == "VEH199"
    assert enablement["provider"] == "terpel" and enablement["payment_method"] == "chip"


def test_confirming_the_reference_authorizes_the_request_for_two_hours(fresh):
    request = in_review(fresh, "GREEN")
    reference = decide(fresh, request["id"], action="approve").json()["enablement"]["suggested_reference"]
    response = authorize(fresh, request["id"], reference)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "authorized" and body["status_label"] == "Autorizada" and body["stage"] == "authorized"
    assert body["closed_at"] is not None and body["enablement"] is None and body["authorized_amount"] == 90000
    authorization = body["authorization"]
    assert authorization["reference"] == reference and authorization["amount"] == 90000
    assert authorization["product"] == "Gasolina Corriente" and authorization["provider"] == "terpel"
    assert authorization["provider_label"] == "Terpel" and authorization["payment_method"] == "chip"
    assert authorization["enabled_by"] == "Laura Gomez" and authorization["valid_minutes"] == 120
    assert authorization["expired"] is False and authorization["reconciled"] is False
    created = datetime.fromisoformat(authorization["created_at"])
    expires = datetime.fromisoformat(authorization["expires_at"])
    assert expires - created == timedelta(hours=2)
    assert abs((now() - created).total_seconds()) < 60
    assert body["status_history"][-1]["status"] == "authorized"
    assert body["status_history"][-1]["note"] == f"Chip habilitado por Laura Gomez, referencia {reference}"


def test_driver_receives_amount_product_reference_and_validity(fresh):
    authorized_green(fresh, "TER-261011-0001")
    last = conversation(fresh, WA["GREEN"])["messages"][-1]
    assert last["kind"] == "authorization" and last["direction"] == "outbound"
    assert plain(last["text"]) == ("Autorizado, Carlos: $90.000 de Gasolina Corriente. Referencia: TER-261011-0001. "
                                   "Vigencia: 2 horas (hasta las 11:40 a. m.). Tu chip ya está habilitado solo por ese valor.")


def test_validity_is_shown_to_the_driver_in_the_time_of_the_case(fresh):
    body = authorized_green(fresh)
    authorization = body["authorization"]
    # The request was made at 09:40 (case time): the driver reads "until 11:40", whatever the real time is.
    case_expiry = datetime.fromisoformat(authorization["expires_at_case_time"])
    assert at(today(), "11:40") <= case_expiry < at(today(), "11:41")
    assert datetime.fromisoformat(authorization["expires_at"]) > now() + timedelta(minutes=119)


def test_adjusted_authorization_tells_the_driver_the_reason(fresh):
    request = in_review(fresh, "VEH199")
    decide(fresh, request["id"], action="adjust", amount=20000, reason="Apoyo nocturno confirmado por radio.")
    authorize(fresh, request["id"], "TER-AJUSTE-7")
    last = conversation(fresh, WA["VEH199"])["messages"][-1]
    assert last["kind"] == "authorization"
    text = plain(last["text"])
    assert text.startswith("Autorizado, Wilson: $20.000 de GNV. Referencia: TER-AJUSTE-7. Vigencia: 2 horas (hasta las ")
    assert text.endswith("Tu chip ya está habilitado solo por ese valor. El técnico ajustó el valor. "
                         "Motivo: Apoyo nocturno confirmado por radio.")


def test_approval_with_reason_does_not_add_an_adjustment_note(fresh):
    request = in_review(fresh, "VEH015")
    decide(fresh, request["id"], action="approve", reason="Kilometraje corregido y confirmado")
    authorize(fresh, request["id"], "TER-015-1")
    text = conversation(fresh, WA["VEH015"])["messages"][-1]["text"]
    assert "$50.000 de Gasolina Corriente" in text and "ajustó" not in text and "Motivo" not in text


def test_request_cannot_be_enabled_twice(fresh):
    body = authorized_green(fresh, "TER-UNICA-1")
    again = authorize(fresh, body["id"], "TER-OTRA-2", headers=COORD)
    assert again.status_code == 409
    assert again.json() == {"detail": "Esta solicitud ya fue habilitada por Laura Gomez con la referencia TER-UNICA-1.",
                            "code": "already_authorized"}
    after = detail(fresh, body["id"])
    assert after["authorization"]["reference"] == "TER-UNICA-1"
    assert [m["kind"] for m in conversation(fresh, WA["GREEN"])["messages"]].count("authorization") == 1
    assert len(audit_items(fresh, "action=authorization")) == 1


def test_request_cannot_be_enabled_without_a_decision(fresh):
    request = in_review(fresh, "GREEN")
    response = authorize(fresh, request["id"], "TER-SIN-DECISION")
    assert response.status_code == 409
    assert response.json() == {"detail": "Solo se habilita una solicitud aprobada o ajustada.", "code": "not_approved"}
    assert detail(fresh, request["id"])["authorization"] is None
    assert conversation(fresh, WA["GREEN"])["messages"][-1]["kind"] == "in_review"


def test_request_still_in_conversation_cannot_be_enabled(fresh):
    request_id = play(fresh, "GREEN", steps=2)["request"]["id"]
    assert authorize(fresh, request_id, "TER-TEMPRANO").json()["code"] == "not_approved"


@pytest.mark.parametrize("body", [{}, {"reference": "ab"}, {"reference": "x" * 61},
                                  {"reference": "TER-1", "provider": "shell"}])
def test_reference_is_validated(fresh, body):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    response = fresh.post(f"/api/requests/{request['id']}/authorization", json=body, headers=TECH)
    assert response.status_code == 422 and response.json()["code"] == "validation_error"
    assert detail(fresh, request["id"])["authorization"] is None


def test_reference_made_only_of_spaces_is_not_a_reference(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    response = authorize(fresh, request["id"], "     ")
    assert response.status_code == 422 and response.json()["code"] == "reference_required"
    assert detail(fresh, request["id"])["authorization"] is None
    assert conversation(fresh, WA["GREEN"])["messages"][-1]["kind"] == "in_review"


@pytest.mark.parametrize("headers", [FINANCE, SUPPORT])
def test_finance_and_support_cannot_enable(fresh, headers):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    response = authorize(fresh, request["id"], "TER-ROL-1", headers=headers)
    assert response.status_code == 403 and response.json()["allowed_roles"] == ["technician", "coordinator"]
    assert detail(fresh, request["id"])["authorization"] is None


def test_coordinator_can_enable_what_the_technician_approved(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    body = authorize(fresh, request["id"], "TER-COORD-1", headers=COORD).json()
    assert body["authorization"]["enabled_by"] == "Andres Molina" and body["decision"]["decided_by"] == "Laura Gomez"


def test_enablement_is_recorded_in_the_audit_log(fresh):
    body = authorized_green(fresh, "TER-BITACORA-1")
    entry = audit_items(fresh, "action=authorization.enabled")[0]
    assert entry["actor"] == "Laura Gomez" and entry["role"] == "technician" and entry["request_id"] == body["id"]
    assert entry["entity"] == "authorization" and entry["entity_id"] == str(body["authorization"]["id"])
    assert entry["summary"] == ("Laura Gomez habilitó el chip en Terpel: $90.000 de Gasolina Corriente, "
                                "referencia TER-BITACORA-1, vigente 2 horas")
    assert entry["after"] == {"provider": "terpel", "reference": "TER-BITACORA-1", "product": "Gasolina Corriente",
                              "amount": 90000, "expires_at": body["authorization"]["expires_at"]}


def test_card_provider_is_written_with_the_right_gender(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    body = authorize(fresh, request["id"], "GOP-TARJETA-1", provider="gopass").json()
    assert body["authorization"]["provider"] == "gopass" and body["authorization"]["payment_method"] == "tarjeta"
    assert body["status_history"][-1]["note"] == "Tarjeta habilitada por Laura Gomez, referencia GOP-TARJETA-1"
    last = conversation(fresh, WA["GREEN"])["messages"][-1]
    assert last["text"].endswith("Tu tarjeta ya está habilitada solo por ese valor.")
    entry = audit_items(fresh, "action=authorization.enabled")[0]
    assert entry["summary"].startswith("Laura Gomez habilitó la tarjeta en GoPass: $90.000 de Gasolina Corriente")


def test_authorization_expires_two_hours_later_and_then_a_new_request_can_be_opened(fresh, clock):
    body = authorized_green(fresh, "TER-VENCE-1")
    clock.advance(hours=1, minutes=59)
    assert detail(fresh, body["id"])["authorization"]["expired"] is False
    send(fresh, case="GREEN", text="Necesito tanquear")
    assert conversation(fresh, WA["GREEN"])["messages"][-1]["kind"] == "duplicate"      # still valid: no second request

    clock.advance(minutes=2)
    assert detail(fresh, body["id"])["authorization"]["expired"] is True
    send(fresh, case="GREEN", text="Necesito tanquear")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["id"] != body["id"] and chat["request"]["status"] == "awaiting_evidence"
    assert len(queue(fresh, None)["items"]) == 2
