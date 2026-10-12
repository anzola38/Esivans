"""Cases found in the independent review of the suites: texts that contradicted what happened,
the privacy notice after a failed first message, and guards that the mutation run left alive."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select, text

from app.models import AuditLog, Authorization, Decision, InboundMessage
from app.requests import conversation as conversation_module

from .helpers import (COORD, CSV_HEADER, FINANCE, SUPPORT, TECH, WA, audit_items, authorize, conversation, csv_file, csv_row,
                      day, decide, detail, imported, in_review, kinds, play, post_webhook, queue, send)

NOT_NEEDED = "No necesita tanquear según el cálculo"
PRIVACY = ("Aviso de privacidad: usamos tu número, tu asignación y las fotos que envíes solo para gestionar el "
           "suministro de combustible (Ley 1581 de 2012).")


def _not_needed_reason(client, request_id: int) -> dict:
    reasons = [r for r in detail(client, request_id)["evaluation"]["reasons"] if r["name"] == NOT_NEEDED]
    assert len(reasons) == 1
    return reasons[0]


# ----------------------------------------------------------------------------- "no refuel needed": who asked for the review

def test_reason_does_not_say_the_driver_asked_for_a_review_before_he_answers(fresh):
    chat = play(fresh, "NO_FUEL", steps=4)
    assert chat["request"]["step"] == "not_needed"
    reason = _not_needed_reason(fresh, chat["request"]["id"])
    assert reason["explanation"] == "Con el nivel leído y la ruta pendiente, a cargar da 0 o menos."
    assert reason["code"] == "INC" and reason["points"] == 0


def test_reason_of_a_request_closed_without_refuel_does_not_say_the_driver_asked_for_a_review(fresh):
    play(fresh, "NO_FUEL", steps=4)
    send(fresh, case="NO_FUEL", text="Entendido, gracias")
    request = conversation(fresh, WA["NO_FUEL"])["request"]
    assert request["status"] == "cancelled"
    reason = _not_needed_reason(fresh, request["id"])
    assert reason["explanation"] == "Con el nivel leído y la ruta pendiente, a cargar da 0 o menos."
    assert "pidió" not in reason["explanation"]


def test_reason_says_the_driver_asked_for_a_review_only_when_he_did(fresh):
    play(fresh, "NO_FUEL", steps=4)
    send(fresh, case="NO_FUEL", text="Que lo revise el técnico")
    request = conversation(fresh, WA["NO_FUEL"])["request"]
    assert request["status"] == "in_review"
    reason = _not_needed_reason(fresh, request["id"])
    assert reason["explanation"] == ("Con el nivel leído y la ruta pendiente, a cargar da 0 o menos; "
                                     "el conductor pidió que lo revise el técnico.")
    # The rest of the evaluation is untouched: still yellow by the inconsistency, no points, nothing to approve in one click.
    after = detail(fresh, request["id"])
    assert (after["traffic_light"], after["points"], after["one_click_allowed"]) == ("yellow", 0, False)
    assert after["suggested_amount"] == 0


# ----------------------------------------------------------------------------- driver without a current assignment

def test_driver_without_a_current_assignment_is_not_reported_as_an_unregistered_number(fresh, db):
    db.execute(text("UPDATE assignment SET valid_to = now() - interval '1 day' "
                    "WHERE driver_id = (SELECT id FROM driver WHERE phone = :phone)"), {"phone": WA["VEH903"]})
    db.commit()
    send(fresh, wa_id=WA["VEH903"], text="Necesito tanquear", time="10:00")
    request = detail(fresh, conversation(fresh, WA["VEH903"])["request"]["id"])
    assert request["driver"]["name"] == "María Fernanda Lozano"
    reasons = request["evaluation"]["reasons"]
    assert [(r["code"], r["name"]) for r in reasons] == [("INC", "Conductor sin vehículo asignado")]
    assert reasons[0]["explanation"] == ("El conductor está registrado, pero no tiene un vehículo con asignación vigente; "
                                         "el técnico identifica el vehículo y decide.")
    assert request["traffic_light"] == "yellow" and request["one_click_allowed"] is False


def test_unregistered_number_keeps_its_own_reason(fresh):
    request = detail(fresh, play(fresh, "UNREGISTERED")["request"]["id"])
    reasons = request["evaluation"]["reasons"]
    assert [(r["code"], r["name"]) for r in reasons] == [("INC", "Número no registrado")]
    assert reasons[0]["explanation"] == ("El número de WhatsApp no corresponde a un conductor con asignación vigente; "
                                         "el técnico identifica al conductor y decide.")


# ----------------------------------------------------------------------------- privacy notice after a failure

def test_privacy_notice_is_not_lost_when_the_first_message_fails(fresh, db, monkeypatch):
    original = conversation_module._create_request
    calls = {"count": 0}

    def fails_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("fallo simulado al crear la solicitud")
        return original(*args, **kwargs)

    monkeypatch.setattr(conversation_module, "_create_request", fails_once)
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    chat = conversation(fresh, WA["GREEN"])
    assert kinds(chat) == ["privacy_notice", "error"]
    assert chat["messages"][1]["text"] == PRIVACY
    assert chat["messages"][-1]["text"] == ("Tuvimos un problema procesando tu mensaje. El técnico de turno ya fue avisado "
                                            "y te atiende por este medio.")
    assert chat["assistant_typing"] is False and chat["request"] is None
    failures = audit_items(fresh, "action=message.failed")
    assert len(failures) == 1 and failures[0]["actor"] == "sistema"

    # The driver writes again: the flow starts normally and the notice is not repeated.
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    chat = conversation(fresh, WA["GREEN"])
    assert kinds(chat) == ["privacy_notice", "error", "greeting", "ask_service"]
    assert chat["request"]["status"] == "awaiting_evidence"


# ----------------------------------------------------------------------------- guards behind the database constraints

def test_second_decision_never_reaches_the_database_constraint(fresh, db):
    """The 409 comes from the check made with the row locked, with the request untouched: no second
    Decision is even attempted (a failed INSERT would roll back the transaction and burn an id)."""
    request = in_review(fresh, "GREEN")
    assert decide(fresh, request["id"], action="approve").status_code == 200
    again = decide(fresh, request["id"], action="adjust", amount=50000, reason="Otro criterio", headers=COORD)
    assert again.status_code == 409 and again.json()["code"] == "already_decided"
    # A third decision in a NEW request gets the next id: the rejected attempt did not consume one.
    other = in_review(fresh, "VEH015")
    third = decide(fresh, other["id"], action="reject", reason="Prueba de secuencia")
    assert third.status_code == 200 and third.json()["decision"]["id"] == 2
    assert db.scalar(select(func.count()).select_from(Decision)) == 2


def test_second_enablement_never_reaches_the_database_constraint(fresh, db):
    first = in_review(fresh, "GREEN")
    assert decide(fresh, first["id"], action="approve").status_code == 200
    assert authorize(fresh, first["id"], "TER-UNO-1").status_code == 200
    again = authorize(fresh, first["id"], "TER-DOS-2")
    assert again.status_code == 409
    assert again.json()["detail"] == "Esta solicitud ya fue habilitada por Laura Gomez con la referencia TER-UNO-1."
    other = in_review(fresh, "VEH199")
    assert decide(fresh, other["id"], action="adjust", amount=20000, reason="Apoyo nocturno").status_code == 200
    second = authorize(fresh, other["id"], "TER-TRES-3")
    assert second.status_code == 200 and second.json()["authorization"]["id"] == 2
    assert db.scalar(select(func.count()).select_from(Authorization)) == 2


def test_repeated_webhook_message_does_not_consume_an_inbound_id(fresh, db):
    def payload(message_id: str, body: str) -> dict:
        return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
            "messages": [{"from": WA["GREEN"], "id": message_id, "timestamp": "1791729600", "type": "text",
                          "text": {"body": body}}]}}]}]}

    assert post_webhook(fresh, payload("wamid.A", "Hola, necesito tanquear")).json()["message_ids"] == [1]
    repeated = post_webhook(fresh, payload("wamid.A", "Hola, necesito tanquear")).json()
    assert (repeated["received"], repeated["duplicates"], repeated["message_ids"]) == (0, 1, [])
    assert post_webhook(fresh, payload("wamid.B", "Sí, es para esa ruta")).json()["message_ids"] == [2]
    assert db.scalar(select(func.count()).select_from(InboundMessage)) == 2


# ----------------------------------------------------------------------------- roles: every write, every forbidden role

@pytest.mark.parametrize("headers, role_label", [(FINANCE, "Administración y finanzas"), (SUPPORT, "Soporte")])
def test_forbidden_decision_changes_nothing_and_names_the_allowed_roles(fresh, db, headers, role_label):
    request = in_review(fresh, "GREEN")
    response = decide(fresh, request["id"], headers=headers, action="reject", reason="Sin permiso")
    assert response.status_code == 403
    assert response.json() == {
        "detail": (f"Tu rol ({role_label}) no puede hacer esta acción. Roles permitidos: "
                   "Técnico de Control y Monitoreo, Coordinador."),
        "code": "forbidden", "allowed_roles": ["technician", "coordinator"]}
    assert db.scalar(select(func.count()).select_from(Decision)) == 0
    assert detail(fresh, request["id"])["status"] == "in_review"
    assert queue(fresh)["counts"]["in_review"] == 1
    denied = db.scalars(select(AuditLog).where(AuditLog.action == "access.denied")).all()
    assert [(d.actor, d.role, d.after["path"]) for d in denied] == [
        (headers["X-Demo-User"], headers["X-Demo-Role"], f"/api/requests/{request['id']}/decision")]
    assert TECH["X-Demo-User"] not in [d.actor for d in denied]


# ----------------------------------------------------------------------------- queue order (longest wait first)

def test_queue_is_ordered_from_the_longest_wait_to_the_shortest(fresh, clock):
    in_review(fresh, "VEH015")
    clock.advance(minutes=3)
    in_review(fresh, "GREEN")
    clock.advance(minutes=1)
    in_review(fresh, "VEH199")
    items = queue(fresh, "open")["items"]
    # Arrival order, not id nor the simulated hour of each case (14:20, 09:40 and 23:14).
    assert [i["vehicle"]["code"] for i in items] == ["VEH015", "VEH901", "VEH199"]
    waits = [i["wait_seconds"] for i in items]
    assert waits[0] >= 240 and 60 <= waits[1] < 240 and waits[2] < 60
    remaining = [i["sla_remaining_seconds"] for i in items]
    assert remaining == sorted(remaining) and remaining[0] <= 360      # the oldest one is the closest to its SLA

    # A decided request keeps its place by wait; a closed one leaves the open block.
    assert decide(fresh, items[0]["id"], action="reject", reason="Prueba de orden").status_code == 200
    after = queue(fresh, None)["items"]
    assert [i["vehicle"]["code"] for i in after] == ["VEH901", "VEH199", "VEH015"]
    assert [i["status"] for i in after] == ["in_review", "in_review", "rejected"]


# ----------------------------------------------------------------------------- GoPass vehicle: card and its own reference

def test_gopass_vehicle_gets_the_card_and_a_gopass_reference_in_the_enablement_panel(fresh, clock):
    send(fresh, wa_id="573005550160", text="Necesito tanquear", time="10:00")
    clock.advance(minutes=11)                                   # incomplete: the 10-minute SLA hands it over
    items = queue(fresh)["items"]
    assert [(i["vehicle"]["code"], i["status"]) for i in items] == [("VEH160", "in_review")]
    request_id = items[0]["id"]
    product = fresh.get("/api/vehicles/VEH160/ledger", headers=TECH).json()["vehicle"]["product"]

    decided = decide(fresh, request_id, action="adjust", amount=50000, reason="Sin foto: valor acordado por radio")
    assert decided.status_code == 200, decided.text
    created = datetime.fromisoformat(items[0]["created_at"])
    assert decided.json()["enablement"] == {
        "provider": "gopass", "provider_label": "GoPass", "payment_method": "tarjeta",
        "plate": "ZZA160", "vehicle_code": "VEH160", "product": product,
        "amount": 50000, "valid_minutes": 120,
        "suggested_reference": f"GOP-{created:%y%m%d}-{request_id:04d}",
    }
    enabled = authorize(fresh, request_id, decided.json()["enablement"]["suggested_reference"])
    assert enabled.status_code == 200
    assert enabled.json()["authorization"]["provider"] == "gopass"
    assert enabled.json()["authorization"]["payment_method"] == "tarjeta"
    last = conversation(fresh, "573005550160")["messages"][-1]
    assert last["kind"] == "authorization" and f"$50.000 de {product}" in last["text"]
    assert last["text"].endswith("Tu tarjeta ya está habilitada solo por ese valor. "
                                 "El técnico ajustó el valor. Motivo: Sin foto: valor acordado por radio.")


# ----------------------------------------------------------------------------- provider file with es-CO numbers

def test_file_with_semicolons_reads_numbers_written_with_thousands_dot_and_decimal_comma(fresh):
    row = ";".join(["TER-FMT-0001", f"{day()} 10:15:00", "VEH901", "ZZA901", "EDS Cereté Norte", "NORTE",
                    "Gasolina Corriente", "5,000", "gal", "16.000,00", "80.000,00", "50000", "En línea"])
    result = imported(fresh, "\n".join([CSV_HEADER.replace(",", ";"), row, ""]))
    assert (result["rows"], result["imported"], result["rejected"], result["alerts_created"]) == (1, 1, 0, 0)
    entries = fresh.get("/api/vehicles/VEH901/ledger", headers=FINANCE).json()["entries"]
    entry = next(e for e in entries if e["external_id"] == "TER-FMT-0001")
    assert (entry["quantity"], entry["unit_price"], entry["amount"], entry["odometer"]) == (5.0, 16000.0, 80000, 50000)
    assert entry["source"] == "import" and entry["provider"] == "terpel"


# ----------------------------------------------------------------------------- clock of the case

def test_clock_of_the_case_advances_with_the_real_time_that_passes(fresh, clock):
    send(fresh, case="VEH199", text="Necesito tanquear 6,7 m3 de gas")           # the case starts at 23:14
    clock.advance(minutes=5)
    send(fresh, case="VEH199", text="Apoyo a otra zona")
    messages = conversation(fresh, WA["VEH199"])["messages"]
    started = datetime.fromisoformat(messages[0]["timestamp"])
    assert (started.hour, started.minute) == (23, 14)
    # Both the driver's second message and the assistant's answer happen 5 minutes later in the case.
    for message in messages[-2:]:
        elapsed = (datetime.fromisoformat(message["timestamp"]) - started).total_seconds()
        assert 300 <= elapsed < 360, (message["kind"], message["timestamp"])
    assert [m["direction"] for m in messages[-2:]] == ["inbound", "outbound"]


# ----------------------------------------------------------------------------- what identifies a transaction (its hash)

HASH_ROW = dict(external_id="TER-HASH-1", vehicle="VEH901", amount=80000, hour="10:15:00", product="Gasolina Corriente",
                quantity=5.0, unit_price=16000, station="EDS Cereté Norte", odometer=50000, sale_type="En línea")


@pytest.mark.parametrize("change", [
    {"external_id": "TER-HASH-2"},
    {"vehicle": "VEH903"},
    {"hour": "10:15:01"},
    {"product": "Gasolina Extra"},
    {"quantity": 5.001},
    {"amount": 80001},
], ids=lambda change: next(iter(change)))
def test_changing_any_field_of_the_hash_makes_a_new_transaction(fresh, change):
    first = imported(fresh, csv_file(csv_row(**HASH_ROW)))
    assert (first["imported"], first["duplicates"]) == (1, 0)
    second = imported(fresh, csv_file(csv_row(**{**HASH_ROW, **change})))
    assert (second["imported"], second["duplicates"]) == (1, 0), second["lines"]


@pytest.mark.parametrize("change", [
    {"station": "EDS Montería Centro"},
    {"odometer": 50999},
    {"sale_type": "Fuera de línea"},
    {"unit_price": 16001},
], ids=lambda change: next(iter(change)))
def test_fields_outside_the_hash_do_not_make_a_new_transaction(fresh, change):
    imported(fresh, csv_file(csv_row(**HASH_ROW)))
    second = imported(fresh, csv_file(csv_row(**{**HASH_ROW, **change})))
    assert (second["imported"], second["duplicates"], second["alerts_created"]) == (0, 1, 0)
    assert second["lines"][0]["message"] == "Ya estaba en el libro único (mismo hash de transacción)"
