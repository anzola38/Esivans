"""Webhook signature and full flows through the API (database `<db>_test`)."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.integrations.whatsapp import build_webhook_payload, encode, sign, verify_signature
from app.timeutil import now

TECH = {"X-Demo-Role": "technician", "X-Demo-User": "Laura Gomez"}
COORD = {"X-Demo-Role": "coordinator", "X-Demo-User": "Andres Molina"}
FINANCE = {"X-Demo-Role": "finance", "X-Demo-User": "Paola Ruiz"}


def _play(client, case_code: str) -> dict:
    """Sends the suggested script of a demo case and returns the driver's conversation."""
    case = next(c for c in client.get("/api/dev/simulator/cases").json()["items"] if c["code"] == case_code)
    for message in case["script"]:
        response = client.post("/api/dev/simulator/messages", json={"case_code": case_code, **message})
        assert response.status_code == 200, response.text
    return client.get(f"/api/dev/simulator/conversations/{case['wa_id']}").json()


# ----------------------------------------------------------------------------- webhook signature

def test_signature_helpers():
    body = b'{"object":"whatsapp_business_account"}'
    good = sign(body, "test-secret")
    assert good.startswith("sha256=") and len(good) == 71
    assert verify_signature(body, good, "test-secret")
    assert not verify_signature(body + b" ", good, "test-secret")     # computed over the raw body
    assert not verify_signature(body, good, "another-secret")
    assert not verify_signature(body, None, "test-secret")
    assert not verify_signature(body, good.removeprefix("sha256="), "test-secret")


def test_webhook_rejects_bad_signature_and_deduplicates(fresh):
    payload = build_webhook_payload(wa_id="573005550903", profile_name="Prueba", timestamp=now(),
                                    text="¿Cómo va mi solicitud?", message_id="wamid.TEST-0001")
    raw = encode(payload)
    headers = {"Content-Type": "application/json"}

    bad = fresh.post("/api/webhooks/whatsapp", content=raw, headers={**headers, "X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 401 and bad.json()["code"] == "invalid_signature"
    assert fresh.post("/api/webhooks/whatsapp", content=raw, headers=headers).status_code == 401

    signed = {**headers, "X-Hub-Signature-256": sign(raw, "test-secret")}
    first = fresh.post("/api/webhooks/whatsapp", content=raw, headers=signed)
    assert first.status_code == 200 and first.json()["received"] == 1
    again = fresh.post("/api/webhooks/whatsapp", content=raw, headers=signed)
    assert again.status_code == 200 and again.json() == {"status": "ok", "received": 0, "duplicates": 1, "message_ids": []}

    tampered = json.dumps({**payload, "object": "other"}).encode()
    assert fresh.post("/api/webhooks/whatsapp", content=tampered, headers=signed).status_code == 401


# ----------------------------------------------------------------------------- green case, end to end

def test_green_case_full_flow(fresh):
    chat = _play(fresh, "GREEN")
    kinds = [m["kind"] for m in chat["messages"] if m["direction"] == "outbound"]
    assert kinds == ["privacy_notice", "greeting", "ask_service", "ask_photo", "confirm_reading", "in_review"]
    assert chat["messages"][1]["text"].startswith("Aviso de privacidad")
    assert "Carlos" in chat["messages"][2]["text"] and "ZZA901" in chat["messages"][2]["text"]
    assert [h["status"] for h in chat["request"]["status_history"]] == [
        "received", "identified", "awaiting_evidence", "ready", "in_review"]

    queue = fresh.get("/api/requests?status=in_review", headers=TECH).json()
    assert queue["counts"]["green"] == 1
    item = queue["items"][0]
    assert item["traffic_light"] == "green" and item["points"] == 0 and item["one_click_allowed"] is True
    assert item["suggested_amount"] == 90000 and item["vehicle"]["code"] == "VEH901"

    detail = fresh.get(f"/api/requests/{item['id']}", headers=TECH).json()
    assert detail["evidence"]["odometer_km"] == 48352 and detail["evidence"]["fuel_level"] == 0.25
    assert detail["context"]["km_since_last_refuel"] == 142
    assert detail["context"]["services"]["pending_count"] == 6
    assert detail["calculation"]["steps"][-1]["result"] == 90000
    assert all(not c["triggered"] for c in detail["evaluation"]["checks"])

    # A role without permission cannot decide, and the attempt stays in the audit log.
    denied = fresh.post(f"/api/requests/{item['id']}/decision", json={"action": "approve"}, headers=FINANCE)
    assert denied.status_code == 403

    decided = fresh.post(f"/api/requests/{item['id']}/decision", json={"action": "approve"}, headers=TECH)
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["decision"]["one_click"] is True and body["decision"]["amount"] == 90000
    assert body["stage"] == "pending_enablement" and body["enablement"]["product"] == "Gasolina Corriente"

    # One decision per request.
    second = fresh.post(f"/api/requests/{item['id']}/decision", json={"action": "reject", "reason": "x"}, headers=COORD)
    assert second.status_code == 409 and "Laura Gomez" in second.json()["detail"]

    reference = body["enablement"]["suggested_reference"]
    enabled = fresh.post(f"/api/requests/{item['id']}/authorization", json={"reference": reference}, headers=TECH)
    assert enabled.status_code == 200, enabled.text
    authorization = enabled.json()["authorization"]
    assert enabled.json()["status"] == "authorized"
    assert authorization["amount"] == 90000 and authorization["valid_minutes"] == 120
    assert fresh.post(f"/api/requests/{item['id']}/authorization", json={"reference": "X-1"}, headers=TECH).status_code == 409

    chat = fresh.get(f"/api/dev/simulator/conversations/{chat['wa_id']}").json()
    last = chat["messages"][-1]
    assert last["kind"] == "authorization"
    for expected in ("$90.000", "Gasolina Corriente", reference, "2 horas"):
        assert expected in last["text"]

    actions = [a["action"] for a in fresh.get(f"/api/audit?request_id={item['id']}", headers=TECH).json()["items"]]
    for expected in ("request.received", "evidence.read", "request.evaluated", "decision.approve", "authorization.enabled"):
        assert expected in actions
    assert any(a["action"] == "access.denied" for a in fresh.get("/api/audit", headers=TECH).json()["items"])
    events = [e["event_type"] for e in fresh.get("/api/dev/outbox").json()["items"]]
    assert "RequestReceived" in events and "DecisionRecorded" in events

    # Duplicate: a new message while the authorization is valid never opens a second request.
    fresh.post("/api/dev/simulator/messages", json={"case_code": "GREEN", "text": "Necesito tanquear"})
    chat = fresh.get(f"/api/dev/simulator/conversations/{chat['wa_id']}").json()
    assert chat["messages"][-1]["kind"] == "duplicate"
    assert len(fresh.get("/api/requests", headers=TECH).json()["items"]) == 1


# ----------------------------------------------------------------------------- VEH015 and VEH199 through the API

def test_veh015_proposes_corrected_odometer(fresh):
    chat = _play(fresh, "VEH015")
    proposal = next(m for m in chat["messages"] if m["kind"] == "confirm_correction")
    assert "24.086" in proposal["text"] and "34.086" in proposal["text"] and "el 3 quedó como 2" in proposal["text"]
    detail = fresh.get(f"/api/requests/{chat['request']['id']}", headers=TECH).json()
    assert detail["evidence"]["odometer_read"] == 24086 and detail["evidence"]["odometer_km"] == 34086
    assert detail["traffic_light"] == "yellow" and detail["points"] == 1 and detail["rule_codes"] == ["R02"]
    # R02: no one-click approval, but the technician can always authorize leaving the reason.
    no_reason = fresh.post(f"/api/requests/{detail['id']}/decision", json={"action": "approve"}, headers=TECH)
    assert no_reason.status_code == 422 and no_reason.json()["code"] == "reason_required"
    ok = fresh.post(f"/api/requests/{detail['id']}/decision",
                    json={"action": "approve", "reason": "Kilometraje corregido y confirmado"}, headers=TECH)
    assert ok.status_code == 200 and ok.json()["decision"]["one_click"] is False


def test_veh199_is_red_with_7_points(fresh):
    chat = _play(fresh, "VEH199")
    detail = fresh.get(f"/api/requests/{chat['request']['id']}", headers=TECH).json()
    assert detail["traffic_light"] == "red" and detail["points"] == 7
    assert detail["rule_codes"] == ["R05", "R08", "R09"]
    reasons = {r["code"]: r["explanation"] for r in detail["evaluation"]["reasons"]}
    assert reasons["R05"] == "cargó 6,7 m³ de GNV con 22 km desde su carga anterior (típica 9,7 m³)"
    assert reasons["R09"] == "tanqueo a las 23:14 sin servicios cercanos"
    assert detail["context"]["services"]["services_24h"] == 0
    assert detail["occurred_at"][11:16] == "23:14"

    missing_reason = fresh.post(f"/api/requests/{detail['id']}/decision", json={"action": "adjust", "amount": 20000}, headers=TECH)
    assert missing_reason.status_code == 422
    adjusted = fresh.post(f"/api/requests/{detail['id']}/decision",
                          json={"action": "adjust", "amount": 20000, "reason": "Apoyo nocturno confirmado por radio"},
                          headers=TECH).json()
    assert adjusted["decision"]["action"] == "adjust" and adjusted["decision"]["original_amount"] == 10000


def test_no_fuel_needed_and_unregistered_number(fresh):
    chat = _play(fresh, "NO_FUEL")
    assert any(m["kind"] == "not_needed" for m in chat["messages"])
    assert chat["request"]["status"] == "cancelled"

    chat = _play(fresh, "UNREGISTERED")
    assert chat["messages"][-1]["kind"] == "handoff"
    assert chat["request"]["status"] == "in_review" and chat["request"]["missing"][0]["key"] == "driver"


# ----------------------------------------------------------------------------- reconciliation, alerts, rules

def test_import_is_idempotent_and_finds_veh023(fresh):
    csv_text = fresh.get("/api/dev/samples/terpel").text
    first = fresh.post("/api/integrations/terpel/imports", content=csv_text.encode(),
                       headers={**FINANCE, "Content-Type": "text/csv"})
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["imported"] == 10 and result["duplicates"] == 0 and result["rejected"] == 0
    assert result["overpaid_by_product"] == 27783
    veh023 = next(d for d in result["deviations"] if d["vehicle"]["code"] == "VEH023")
    assert veh023["rule_codes"] == ["C01"]
    difference = veh023["evidence"]["product_difference"]
    assert difference["corriente_price"] == 16330 and difference["sold_price"] == 21250
    assert difference["gallons"] == 5.647 and difference["overpaid"] == 27783
    assert "$27.783" in veh023["reason"]
    fired = sorted({code for d in result["deviations"] for code in d["rule_codes"]})
    assert fired == ["C01", "R01", "R11", "R12", "R13", "R14"]

    again = fresh.post("/api/integrations/terpel/imports", json={"filename": "terpel.csv", "content": csv_text},
                       headers=FINANCE).json()
    assert again["imported"] == 0 and again["duplicates"] == 10 and again["alerts_created"] == 0
    events = [e["event_type"] for e in fresh.get("/api/dev/outbox").json()["items"]]
    assert "TransactionImported" in events and "DeviationDetected" in events


def test_seed_alerts_and_review(fresh):
    alerts = fresh.get("/api/alerts", headers=COORD).json()
    by_vehicle = {a["vehicle"]["code"]: a for a in alerts["items"] if a["kind"] == "vehicle"}
    veh129 = by_vehicle["VEH129"]
    assert veh129["rule_codes"] == ["V01", "V05", "V08"] and veh129["points"] == 8 and veh129["priority"] == "high"
    assert "20,3" in veh129["reason"] and "102 tanqueos por $4,1 M" in veh129["reason"]
    assert by_vehicle["VEH215"]["rule_codes"] == ["V01"] and "31,4" in by_vehicle["VEH215"]["reason"]
    priorities = [a["priority"] for a in alerts["items"] if a["status"] == "open"]
    assert priorities == sorted(priorities, key=["high", "medium", "low"].index)

    reviewed = fresh.patch(f"/api/alerts/{veh129['id']}",
                           json={"review_result": "Confirmado", "comment": "Se envía a revisión mecánica."}, headers=COORD)
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["status"] == "reviewed" and body["review_result"] == "confirmed" and body["reviewed_by"] == "Andres Molina"
    assert fresh.patch(f"/api/alerts/{veh129['id']}", json={"review_result": "confirmed", "comment": "x y z"},
                       headers=FINANCE).status_code == 403


def test_veh160_ledger_comparison(fresh):
    ledger = fresh.get("/api/vehicles/VEH160/ledger", headers=TECH).json()
    comparison = ledger["comparison"]
    assert comparison["km"] == 4803 and comparison["gopass_only"]["gallons"] == 6.135
    assert round(comparison["gopass_only"]["efficiency"]) == 783
    assert comparison["hidden_cng_loads"] == 34 and comparison["single_ledger"]["cng_m3"] == 313.6
    assert {p["provider"] for p in ledger["summary"]["providers"]} == {"terpel", "gopass"}


def test_only_the_coordinator_changes_thresholds(fresh):
    denied = fresh.put("/api/rules/R05", json={"threshold": {"min_km": 25}, "reason": "Prueba"}, headers=TECH)
    assert denied.status_code == 403
    changed = fresh.put("/api/rules/R05", json={"threshold": {"min_km": 25}, "reason": "Ajuste del comité"}, headers=COORD)
    assert changed.status_code == 200, changed.text
    rule = changed.json()["rule"]
    assert rule["version"] == 2 and rule["threshold"]["min_km"] == 25 and len(rule["history"]) == 2
    assert rule["history"][1]["threshold"]["min_km"] == 30          # the previous version is kept
    assert changed.json()["rules_version"] == "v2"
    audit = fresh.get("/api/audit", headers=COORD).json()["items"]
    assert any(a["action"] == "access.denied" and a["actor"] == "Laura Gomez" for a in audit)
    assert any(a["action"] == "rule.updated" for a in audit)


def test_audit_log_is_append_only(fresh, db):
    with pytest.raises(Exception) as update_error:
        db.execute(text("UPDATE audit_log SET actor = 'otro'"))
    db.rollback()
    assert "solo insercion" in str(update_error.value)
    with pytest.raises(Exception):
        db.execute(text("DELETE FROM audit_log"))
    db.rollback()


def test_dashboard_and_health(fresh):
    health = fresh.get("/api/health").json()
    assert health["status"] == "ok" and health["ai_provider"] == "mock"
    board = fresh.get("/api/dashboard", headers=COORD).json()
    assert len(board["indicators"]) == 9
    assert {i["source"] for i in board["indicators"]} <= {"demo", "illustrative"}
    assert board["context"]["hours_today"] == 66.7 and board["context"]["hours_target"] == 10
    assert [o["key"] for o in board["decision"]["options"]] == ["expand", "adjust", "stop"]
