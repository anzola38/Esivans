"""Health, demo reset, media, the routes of the driver simulator and the outbox of domain events."""
from __future__ import annotations

import hashlib
from datetime import datetime

import pytest
from sqlalchemy import text

from app.integrations.whatsapp import encode, sign, verify_signature
from app.timeutil import at, now, today

from .helpers import (COORD, SECRET, TECH, WA, alerts, audit_items, authorized_green, conversation, decide, detail,
                      imported, in_review, kinds, outbox, play, put_rule, queue, review, sample_csv, send,
                      vehicle_alert)

CASES = ["GREEN", "VEH015", "VEH199", "NO_FUEL", "UNREGISTERED"]


def _cases(client) -> dict:
    response = client.get("/api/dev/simulator/cases")
    assert response.status_code == 200
    return response.json()


def _alert_snapshot(client) -> list[dict]:
    """Alerts without the fields that move with the clock."""
    return [{k: v for k, v in a.items() if k != "hours_to_due"} for a in alerts(client)["items"]]


# ----------------------------------------------------------------------------- health

def test_health_reports_service_database_and_configuration(fresh):
    response = fresh.get("/api/health")
    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "ok" and health["database"] == "ok"
    assert health["service"] == "esivans-combustible-backend" and health["timezone"] == "America/Bogota"
    assert health["ai_provider"] == "mock" and health["demo_mode"] is True
    assert health["seed_date"] == today().isoformat() and health["rules_version"] == "v1"
    assert health["roles"] == [
        {"key": "technician", "label": "Técnico de Control y Monitoreo"},
        {"key": "coordinator", "label": "Coordinador"},
        {"key": "finance", "label": "Administración y finanzas"},
        {"key": "support", "label": "Soporte"}]
    reported = datetime.fromisoformat(health["time"])
    assert reported.utcoffset().total_seconds() == -5 * 3600 and abs((now() - reported).total_seconds()) < 60


def test_health_needs_no_role_headers_and_openapi_is_published(fresh):
    assert fresh.get("/api/health", headers={"X-Demo-Role": "nadie"}).status_code == 200
    schema = fresh.get("/openapi.json").json()
    for path in ("/api/health", "/api/webhooks/whatsapp", "/api/requests", "/api/requests/{request_id}/decision",
                 "/api/requests/{request_id}/authorization", "/api/audit", "/api/alerts", "/api/alerts/{alert_id}",
                 "/api/rules", "/api/rules/{code}", "/api/integrations/{provider}/imports", "/api/dashboard",
                 "/api/vehicles/{vehicle_ref}/ledger", "/api/dev/reset", "/api/media/{media_id}"):
        assert path in schema["paths"], path
    assert fresh.get("/docs").status_code == 200


# ----------------------------------------------------------------------------- reset

def test_reset_answers_with_the_counts_of_the_seed(fresh):
    response = fresh.post("/api/dev/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Demo reiniciada: semilla cargada de nuevo.",
                               "seed_date": today().isoformat(), "vehicles": 24, "drivers": 24, "transactions": 878,
                               "eom_services": 1534, "alerts": 19, "rules": 25}


def test_reset_restores_the_exact_initial_state_after_a_full_demo(fresh, db):
    initial_alerts = _alert_snapshot(fresh)
    initial_rules = fresh.get("/api/rules", headers=COORD).json()
    initial_veh023 = fresh.get("/api/vehicles/VEH023/ledger", headers=TECH).json()["summary"]
    initial_board = fresh.get("/api/dashboard", headers=COORD).json()["activity"]
    tables = ("request", "request_status_log", "evidence", "evaluation", "decision", "\"authorization\"",
              "inbound_message", "outbound_message", "outbox", "import_batch")

    # A whole demo: three requests, decisions, an authorization, the provider file, a review and a threshold.
    authorized_green(fresh)
    decide(fresh, in_review(fresh, "VEH015")["id"], action="approve", reason="Kilometraje corregido")
    decide(fresh, in_review(fresh, "VEH199")["id"], action="reject", reason="Sin soporte")
    play(fresh, "UNREGISTERED")
    imported(fresh, sample_csv(fresh))
    review(fresh, vehicle_alert(fresh, "VEH129")["id"], "confirmed", "Se envía a revisión mecánica.")
    put_rule(fresh, "R05", threshold={"min_km": 25}, reason="Ajuste del comité")
    assert len(queue(fresh, None)["items"]) == 4 and alerts(fresh)["counts"]["total"] == 24
    assert fresh.get("/api/health").json()["rules_version"] == "v2"

    assert fresh.post("/api/dev/reset").status_code == 200

    listing = queue(fresh, None)
    assert listing == {"items": [], "counts": {"total": 0, "in_review": 0, "green": 0, "yellow": 0, "red": 0,
                                              "sla_breached": 0}}
    for table in tables:
        assert db.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table
    assert _alert_snapshot(fresh) == initial_alerts
    rules_after = fresh.get("/api/rules", headers=COORD).json()
    assert rules_after["rules_version"] == "v1"
    assert [{k: v for k, v in r.items() if k not in ("valid_from", "history")} for r in rules_after["items"]] == [
        {k: v for k, v in r.items() if k not in ("valid_from", "history")} for r in initial_rules["items"]]
    assert all(len(r["history"]) == 1 for r in rules_after["items"])
    assert fresh.get("/api/vehicles/VEH023/ledger", headers=TECH).json()["summary"] == initial_veh023
    assert db.scalar(text("SELECT count(*) FROM provider_transaction")) == 878
    assert db.scalar(text("SELECT count(*) FROM provider_transaction WHERE source = 'import'")) == 0
    assert fresh.get("/api/dashboard", headers=COORD).json()["activity"] == initial_board
    assert outbox(fresh) == []
    for wa_id in WA.values():
        assert conversation(fresh, wa_id) == {"wa_id": wa_id, "driver": conversation(fresh, wa_id)["driver"],
                                              "assistant_typing": False, "quick_replies": [], "messages": [],
                                              "request": None}
    assert [a["action"] for a in audit_items(fresh)] == ["demo.reset", "seed.loaded"]


def test_ids_restart_after_the_reset_so_the_demo_always_looks_the_same(fresh):
    first = in_review(fresh, "GREEN")
    assert fresh.post("/api/dev/reset").status_code == 200
    second = in_review(fresh, "GREEN")
    assert first["id"] == second["id"] == 1
    assert decide(fresh, second["id"], action="approve").json()["enablement"]["suggested_reference"].endswith("-0001")
    assert first["public_id"] != second["public_id"]


def test_reset_records_who_did_it(fresh):
    fresh.post("/api/dev/reset", headers={"X-Demo-Role": "coordinator", "X-Demo-User": "Andres Molina"})
    entry = audit_items(fresh)[0]
    assert entry["action"] == "demo.reset" and entry["actor"] == "Andres Molina" and entry["role"] == "coordinator"
    assert entry["summary"] == "Andres Molina reinició la demo" and entry["entity_id"] == today().isoformat()


# ----------------------------------------------------------------------------- media

@pytest.mark.parametrize("media_id", ["media-veh901", "media-veh015", "media-veh199", "media-veh902"])
def test_media_serves_the_sample_photo_of_each_case(fresh, media_id):
    response = fresh.get(f"/api/media/{media_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == "no-cache"
    assert response.content.lstrip().startswith(b"<svg") and len(response.content) > 1000


def test_each_case_has_a_different_photo(fresh):
    digests = {hashlib.sha256(fresh.get(f"/api/media/{m}").content).hexdigest()
               for m in ("media-veh901", "media-veh015", "media-veh199", "media-veh902")}
    assert len(digests) == 4


@pytest.mark.parametrize("media_id", ["media-no-existe", "media-", "media-..%2F..%2Fconfig", "veh901.json", "media-veh901.json"])
def test_unknown_or_unsafe_media_is_a_404(fresh, media_id):
    response = fresh.get(f"/api/media/{media_id}")
    assert response.status_code == 404
    assert response.json()["code"] in ("media_not_found", "http_error")      # http_error: the path did not even match


# ----------------------------------------------------------------------------- simulator: cases

def test_simulator_lists_the_five_cases_with_script_photo_and_expected_result(fresh):
    body = _cases(fresh)
    assert body["seed_date"] == today().isoformat() and body["seed_is_stale"] is False and body["ai_provider"] == "mock"
    items = {c["code"]: c for c in body["items"]}
    assert list(items) == CASES
    assert {code: (c["plate"], c["wa_id"], c["case_time"]) for code, c in items.items()} == {
        "GREEN": ("ZZA901", "573005550901", "09:40"), "VEH015": ("ZZA015", "573005550015", "14:20"),
        "VEH199": ("ZZA199", "573005550199", "23:14"), "NO_FUEL": ("ZZA902", "573005550902", "11:05"),
        "UNREGISTERED": (None, "573009990000", "08:15")}
    assert {code: c["driver"]["name"] for code, c in items.items()} == {
        "GREEN": "Carlos Andrés Pérez", "VEH015": "Jorge Iván Castaño", "VEH199": "Wilson Darío Hoyos",
        "NO_FUEL": "Luis Fernando Ortega", "UNREGISTERED": "Número no registrado"}
    green = items["GREEN"]
    assert green["case_datetime"] == at(today(), "09:40").isoformat()
    assert green["photo"] == {"media_id": "media-veh901", "url": "/api/media/media-veh901",
                              "mime_type": "image/svg+xml", "label": "Foto de ejemplo del tablero"}
    assert green["script"] == [{"type": "text", "text": "Hola, necesito tanquear"},
                               {"type": "text", "text": "Sí, es para esa ruta"},
                               {"type": "image", "media_id": "media-veh901"},
                               {"type": "text", "text": "Sí, es correcto"}]
    assert green["vehicle"]["code"] == "VEH901" and green["vehicle"]["tank_capacity"] == 12.0
    assert green["vehicle"]["reference_efficiency"] == 40.5 and green["vehicle"]["product"] == "Gasolina Corriente"
    unregistered = items["UNREGISTERED"]
    assert unregistered["vehicle"] is None and unregistered["photo"] is None and unregistered["driver"]["id"] is None
    assert items["VEH199"]["script"][0]["text"] == "Necesito tanquear 6,7 m3 de gas"


@pytest.mark.parametrize("code", CASES)
def test_each_case_ends_exactly_as_its_expected_result_says(fresh, code):
    expected = next(c for c in _cases(fresh)["items"] if c["code"] == code)["expected"]
    request = detail(fresh, play(fresh, code)["request"]["id"])
    assert request["points"] == expected["points"]
    assert request["rule_codes"] == expected["rules"]
    assert request["suggested_amount"] == expected["suggested_amount"]
    if expected["traffic_light"] is not None:
        assert request["traffic_light"] == expected["traffic_light"] and request["status"] == "in_review"
    else:
        assert request["status"] == "cancelled"          # NO_FUEL: closed without reaching the technician


def test_cases_warn_when_the_seed_is_from_another_day(fresh, clock):
    clock.advance(days=1)
    body = _cases(fresh)
    assert body["seed_is_stale"] is True and body["seed_date"] != today().isoformat()
    assert fresh.post("/api/dev/reset").status_code == 200
    assert _cases(fresh)["seed_is_stale"] is False


# ----------------------------------------------------------------------------- simulator: messages

def test_simulator_message_goes_through_the_signed_webhook_contract(fresh):
    body = send(fresh, case="GREEN", text="Hola, necesito tanquear")
    assert body["status"] == "accepted" and body["wa_id"] == "573005550901"
    assert body["case_time"] == at(today(), "09:40").isoformat()
    assert body["webhook"] == {"path": "/api/webhooks/whatsapp", "signature_header": "X-Hub-Signature-256",
                               "signed": True, "result": {"status": "ok", "received": 1, "duplicates": 0,
                                                          "message_ids": [1]}}
    payload = body["payload"]
    assert payload["object"] == "whatsapp_business_account"
    value = payload["entry"][0]["changes"][0]["value"]
    assert payload["entry"][0]["changes"][0]["field"] == "messages" and value["messaging_product"] == "whatsapp"
    assert value["contacts"] == [{"profile": {"name": "Carlos Andrés Pérez"}, "wa_id": "573005550901"}]
    message = value["messages"][0]
    assert message["from"] == "573005550901" and message["id"] == body["wa_message_id"]
    assert message["id"].startswith("wamid.") and message["type"] == "text"
    assert message["text"] == {"body": "Hola, necesito tanquear"}
    assert message["timestamp"] == str(int(at(today(), "09:40").timestamp()))
    # The payload returned is the one that was signed: replaying it against the real webhook is a duplicate.
    raw = encode(payload)
    assert verify_signature(raw, sign(raw, SECRET), SECRET)
    replay = fresh.post("/api/webhooks/whatsapp", content=raw,
                        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sign(raw, SECRET)})
    assert replay.json() == {"status": "ok", "received": 0, "duplicates": 1, "message_ids": []}


def test_simulator_photo_message_carries_the_media_id_and_its_hash(fresh):
    play(fresh, "GREEN", steps=2)
    body = send(fresh, case="GREEN", media_id="media-veh901")
    message = body["payload"]["entry"][0]["changes"][0]["value"]["messages"][0]
    image = fresh.get("/api/media/media-veh901").content
    assert message["type"] == "image"
    assert message["image"] == {"id": "media-veh901", "mime_type": "image/svg+xml",
                                "sha256": hashlib.sha256(image).hexdigest()}


def test_simulated_time_is_fixed_by_the_first_message(fresh):
    first = send(fresh, wa_id=WA["GREEN"], text="Hola, necesito tanquear", time="06:15")
    assert first["case_time"] == at(today(), "06:15").isoformat()
    second = send(fresh, wa_id=WA["GREEN"], text="Sí, es para esa ruta", time="18:00")       # ignored: already running
    assert second["case_time"][:16] == at(today(), "06:15").isoformat()[:16]
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["occurred_at"] == at(today(), "06:15").isoformat()
    assert {m["timestamp"][11:16] for m in chat["messages"]} == {"06:15"}


def test_simulated_time_accepts_an_iso_date(fresh):
    moment = at(today(), "07:45").isoformat()
    assert send(fresh, wa_id=WA["GREEN"], text="Hola, necesito tanquear", time=moment)["case_time"] == moment


def test_simulator_strips_symbols_from_the_number(fresh):
    body = send(fresh, wa_id="+57 300 555-0901", text="Hola, necesito tanquear")
    assert body["wa_id"] == "573005550901"
    assert conversation(fresh, "573005550901")["driver"]["name"] == "Carlos Andrés Pérez"


@pytest.mark.parametrize("body, status, code", [
    ({"case_code": "GREEN", "type": "text"}, 422, "validation_error"),
    ({"case_code": "GREEN", "type": "text", "text": "   "}, 422, "validation_error"),
    ({"case_code": "GREEN", "type": "image"}, 422, "validation_error"),
    ({"type": "text", "text": "Hola"}, 422, "validation_error"),
    ({"case_code": "GREEN", "type": "audio", "text": "Hola"}, 422, "validation_error"),
    ({"case_code": "NADIE", "type": "text", "text": "Hola"}, 404, "case_not_found"),
    ({"case_code": "GREEN", "type": "image", "media_id": "media-no-existe"}, 404, "media_not_found"),
    ({"wa_id": "sin numeros", "type": "text", "text": "Hola"}, 422, "wa_id_required"),
])
def test_simulator_rejects_invalid_messages(fresh, body, status, code):
    response = fresh.post("/api/dev/simulator/messages", json=body)
    assert response.status_code == status and response.json()["code"] == code
    assert queue(fresh, None)["items"] == []


def test_case_code_is_case_insensitive(fresh):
    assert send(fresh, case="green", text="Hola, necesito tanquear")["wa_id"] == WA["GREEN"]


# ----------------------------------------------------------------------------- simulator: conversation

def test_conversation_of_an_unknown_number_is_empty(fresh):
    assert conversation(fresh, "573001112233") == {"wa_id": "573001112233", "driver": None, "assistant_typing": False,
                                                   "quick_replies": [], "messages": [], "request": None}


def test_conversation_payload_has_the_documented_shape(fresh):
    chat = play(fresh, "GREEN", steps=3)
    assert set(chat) == {"wa_id", "driver", "assistant_typing", "quick_replies", "messages", "request"}
    assert [m["direction"] for m in chat["messages"]] == ["inbound", "outbound", "outbound", "outbound", "inbound",
                                                          "outbound", "inbound", "outbound"]
    for message in chat["messages"]:
        assert set(message) == {"id", "direction", "type", "text", "media_id", "media_url", "quick_replies", "kind",
                                "timestamp", "created_at", "request_id", "ai"}
        assert message["id"].startswith("in-" if message["direction"] == "inbound" else "out-")
    inbound = [m for m in chat["messages"] if m["direction"] == "inbound"]
    assert all(m["kind"] == "driver" and m["quick_replies"] == [] for m in inbound)
    assert [m["type"] for m in inbound] == ["text", "text", "image"]
    assert chat["messages"][1]["kind"] == "privacy_notice" and chat["messages"][1]["request_id"] is None
    request = chat["request"]
    assert request["step"] == "confirm" and request["is_open"] is True
    assert request["decision"] is None and request["authorization"] is None
    assert [h["status_label"] for h in request["status_history"]] == ["Recibida", "Identificada", "Esperando evidencia"]
    # Quick replies of the root are the ones of the last message, and only while it is the assistant's.
    assert chat["quick_replies"] == chat["messages"][-1]["quick_replies"] == ["Sí, es correcto", "No, corregir"]


def test_conversation_shows_decision_and_authorization_once_they_exist(fresh):
    body = authorized_green(fresh, "TER-CHAT-1")
    request = conversation(fresh, WA["GREEN"])["request"]
    assert request["status"] == "authorized" and request["is_open"] is False
    assert request["decision"]["action"] == "approve" and request["decision"]["amount"] == 90000
    assert request["authorization"]["reference"] == "TER-CHAT-1"
    assert request["authorization"] == body["authorization"]
    assert kinds(conversation(fresh, WA["GREEN"]))[-1] == "authorization"


# ----------------------------------------------------------------------------- outbox

def test_outbox_starts_empty_and_records_request_received(fresh):
    assert outbox(fresh) == []
    chat = play(fresh, "GREEN", steps=1)
    events = outbox(fresh)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "RequestReceived" and event["aggregate"] == "request"
    assert event["aggregate_id"] == str(chat["request"]["id"]) and event["published_at"] is None
    assert event["payload"] == {"request_id": chat["request"]["id"], "wa_id": WA["GREEN"], "vehicle": "VEH901",
                                "occurred_at": at(today(), "09:40").isoformat()}
    assert abs((now() - datetime.fromisoformat(event["created_at"])).total_seconds()) < 60


def test_outbox_has_one_request_received_per_request_even_for_an_unregistered_number(fresh):
    play(fresh, "GREEN")
    play(fresh, "UNREGISTERED")
    send(fresh, case="GREEN", text="Necesito tanquear")           # duplicate: no new event
    events = list(reversed(outbox(fresh)))
    assert [e["event_type"] for e in events] == ["RequestReceived", "RequestReceived"]
    assert events[1]["payload"] == {"request_id": 2, "wa_id": WA["UNREGISTERED"], "vehicle": None}


def test_outbox_of_a_full_demo_has_the_four_event_types_in_order(fresh):
    body = authorized_green(fresh)
    rejected = in_review(fresh, "VEH199")
    decide(fresh, rejected["id"], action="reject", reason="Sin soporte")
    imported(fresh, sample_csv(fresh))
    events = list(reversed(outbox(fresh)))
    assert [e["event_type"] for e in events] == (["RequestReceived", "DecisionRecorded", "RequestReceived",
                                                  "DecisionRecorded"] + ["DeviationDetected"] * 5
                                                 + ["TransactionImported"])
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    assert events[1]["payload"]["request_id"] == body["id"] and events[1]["payload"]["one_click"] is True
    assert events[3]["payload"] == {"request_id": rejected["id"], "action": "reject", "amount": None,
                                    "decided_by": "Laura Gomez", "traffic_light": "red", "one_click": False}


def test_outbox_limit(fresh):
    play(fresh, "GREEN")
    play(fresh, "VEH015")
    play(fresh, "VEH199")
    assert len(fresh.get("/api/dev/outbox?limit=2").json()["items"]) == 2
    assert len(outbox(fresh)) == 3
