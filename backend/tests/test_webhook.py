"""WhatsApp webhook: HMAC signature over the raw body, idempotency by message ID and the payload
shapes of the Cloud API (text, photo by media_id, quick replies and status notifications)."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.integrations.whatsapp import build_webhook_payload, encode, parse_webhook, sign, verify_signature
from app.models import FuelRequest, InboundMessage, OutboundMessage
from app.timeutil import at, now, today

from .helpers import SECRET, TECH, WA, conversation, detail, kinds, post_webhook, queue

GREEN = WA["GREEN"]


def _text(text: str, wa_id: str = GREEN, message_id: str | None = None, hhmm: str = "09:40") -> dict:
    return build_webhook_payload(wa_id=wa_id, profile_name="Carlos Andrés Pérez", timestamp=at(today(), hhmm),
                                 text=text, message_id=message_id)


def _photo(media_id: str, wa_id: str = GREEN, message_id: str | None = None) -> dict:
    return build_webhook_payload(wa_id=wa_id, profile_name="Carlos Andrés Pérez", timestamp=now(), media_id=media_id,
                                 mime_type="image/svg+xml", message_id=message_id)


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ----------------------------------------------------------------------------- signature

def test_valid_signature_is_accepted_and_the_assistant_answers(fresh, db):
    response = post_webhook(fresh, _text("Hola, necesito tanquear", message_id="wamid.VALID-1"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "received": 1, "duplicates": 0, "message_ids": [1]}
    stored = db.scalars(select(InboundMessage)).one()
    assert stored.wa_message_id == "wamid.VALID-1" and stored.wa_id == GREEN and stored.type == "text"
    assert stored.text == "Hola, necesito tanquear" and stored.processed_at is not None and stored.request_id == 1
    chat = conversation(fresh, GREEN)
    assert kinds(chat) == ["privacy_notice", "greeting", "ask_service"]
    assert chat["request"]["status"] == "awaiting_evidence"


def test_signature_is_sha256_hmac_of_the_raw_body():
    body = b'{"object":"whatsapp_business_account"}'
    signature = sign(body, SECRET)
    assert signature == "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, signature, SECRET) is True
    assert verify_signature(body, signature.upper(), SECRET) is False
    assert verify_signature(body, signature[len("sha256="):], SECRET) is False     # the prefix is mandatory
    assert verify_signature(body, "", SECRET) is False and verify_signature(body, None, SECRET) is False


def test_missing_signature_is_rejected_and_nothing_is_stored(fresh, db):
    response = post_webhook(fresh, _text("Hola, necesito tanquear"), signature=None)
    assert response.status_code == 401
    assert response.json() == {"detail": "Firma inválida: el webhook no viene firmado con el secreto de la aplicación.",
                               "code": "invalid_signature"}
    assert _count(db, InboundMessage) == 0 and _count(db, FuelRequest) == 0 and _count(db, OutboundMessage) == 0


def test_invalid_signatures_are_rejected(fresh, db):
    payload = _text("Hola, necesito tanquear")
    raw = encode(payload)
    wrong_secret = sign(raw, "otro-secreto")
    for signature in ("sha256=00", "sha256=" + "0" * 64, wrong_secret, sign(raw, SECRET).removeprefix("sha256="),
                      "sha1=" + sign(raw, SECRET)[7:]):
        response = post_webhook(fresh, raw=raw, signature=signature)
        assert response.status_code == 401 and response.json()["code"] == "invalid_signature", signature
    assert _count(db, InboundMessage) == 0
    assert conversation(fresh, GREEN)["messages"] == []


def test_altered_body_is_rejected_with_the_original_signature(fresh, db):
    payload = _text("Necesito tanquear 5 galones", message_id="wamid.TAMPER-1")
    raw = encode(payload)
    signature = sign(raw, SECRET)
    tampered_amount = raw.replace("5 galones".encode(), "50 galones".encode())
    assert tampered_amount != raw
    assert post_webhook(fresh, raw=tampered_amount, signature=signature).status_code == 401
    # Even a change that keeps the JSON equivalent breaks it: the signature covers the raw bytes.
    assert post_webhook(fresh, raw=raw + b" ", signature=signature).status_code == 401
    assert post_webhook(fresh, raw=json.dumps(payload).encode(), signature=signature).status_code == 401
    assert _count(db, InboundMessage) == 0
    # The untouched body with the same signature is accepted.
    assert post_webhook(fresh, raw=raw, signature=signature).status_code == 200
    assert _count(db, InboundMessage) == 1


def test_signed_body_that_is_not_json_is_a_400(fresh):
    response = post_webhook(fresh, raw=b"esto no es json")
    assert response.status_code == 400 and response.json()["code"] == "invalid_payload"


def test_simulator_and_webhook_use_the_app_secret_of_the_environment():
    assert get_settings().whatsapp_app_secret == SECRET


# ----------------------------------------------------------------------------- idempotency

def test_duplicate_message_id_is_not_processed_again(fresh, db):
    payload = _text("Hola, necesito tanquear", message_id="wamid.DUP-1")
    first = post_webhook(fresh, payload)
    assert first.json() == {"status": "ok", "received": 1, "duplicates": 0, "message_ids": [1]}
    before = conversation(fresh, GREEN)

    again = post_webhook(fresh, payload)
    assert again.status_code == 200
    assert again.json() == {"status": "ok", "received": 0, "duplicates": 1, "message_ids": []}
    after = conversation(fresh, GREEN)
    assert [m["id"] for m in after["messages"]] == [m["id"] for m in before["messages"]]
    assert _count(db, InboundMessage) == 1 and _count(db, FuelRequest) == 1
    assert _count(db, OutboundMessage) == 3          # privacy notice, greeting and the question: sent once
    assert len(queue(fresh, None)["items"]) == 1


def test_same_message_id_with_a_different_text_is_still_a_duplicate(fresh, db):
    post_webhook(fresh, _text("Hola, necesito tanquear", message_id="wamid.DUP-2"))
    again = post_webhook(fresh, _text("Sí, es para esa ruta", message_id="wamid.DUP-2"))
    assert again.json()["duplicates"] == 1 and again.json()["received"] == 0
    assert db.scalars(select(InboundMessage.text)).all() == ["Hola, necesito tanquear"]
    assert conversation(fresh, GREEN)["request"]["step"] == "service"       # the conversation did not advance


def test_two_different_messages_are_both_processed(fresh, db):
    first = post_webhook(fresh, _text("Hola, necesito tanquear", message_id="wamid.A"))
    second = post_webhook(fresh, _text("Sí, es para esa ruta", message_id="wamid.B"))
    assert first.json()["message_ids"] == [1] and second.json()["message_ids"] == [2]
    assert _count(db, InboundMessage) == 2 and _count(db, FuelRequest) == 1
    assert conversation(fresh, GREEN)["request"]["step"] == "photo"


def test_batch_with_a_repeated_message_counts_one_received_and_one_duplicate(fresh, db):
    payload = _text("Hola, necesito tanquear", message_id="wamid.BATCH-1")
    messages = payload["entry"][0]["changes"][0]["value"]["messages"]
    messages.append(dict(messages[0]))
    response = post_webhook(fresh, payload)
    assert response.json() == {"status": "ok", "received": 1, "duplicates": 1, "message_ids": [1]}
    assert _count(db, InboundMessage) == 1


# ----------------------------------------------------------------------------- payload shapes

def test_photo_payload_by_media_id_is_downloaded_and_read(fresh, db):
    post_webhook(fresh, _text("Hola, necesito tanquear", message_id="wamid.P1"))
    post_webhook(fresh, _text("Sí, es para esa ruta", message_id="wamid.P2"))
    payload = _photo("media-veh901", message_id="wamid.P3")
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert message["type"] == "image" and message["image"]["id"] == "media-veh901" and "text" not in message
    assert post_webhook(fresh, payload).json()["received"] == 1

    stored = db.scalars(select(InboundMessage).where(InboundMessage.wa_message_id == "wamid.P3")).one()
    assert stored.type == "image" and stored.media_id == "media-veh901" and stored.text is None
    chat = conversation(fresh, GREEN)
    photo = next(m for m in chat["messages"] if m["type"] == "image")
    assert photo["media_id"] == "media-veh901" and photo["media_url"] == "/api/media/media-veh901"
    assert chat["messages"][-1]["kind"] == "confirm_reading" and "48.352 km" in chat["messages"][-1]["text"]

    evidence = detail(fresh, chat["request"]["id"], TECH)["evidence"]
    image = fresh.get("/api/media/media-veh901").content
    assert evidence["media_id"] == "media-veh901" and evidence["photo_url"] == "/api/media/media-veh901"
    assert evidence["photo_hash"] == hashlib.sha256(image).hexdigest()
    assert evidence["photo_path"] == f"media/inbound/{evidence['photo_hash']}.svg"
    assert evidence["odometer_read"] == 48352 and evidence["fuel_level"] == 0.25
    assert evidence["confidence"] == {"odometer_km": 0.97, "fuel_level": 0.92}
    assert evidence["odometer_source"] == "photo" and evidence["confirmed_by_driver"] is False


def test_photo_with_a_caption_keeps_the_text(fresh, db):
    payload = build_webhook_payload(wa_id=GREEN, profile_name="Carlos", timestamp=now(), media_id="media-veh901",
                                    text="Aquí va la foto", message_id="wamid.CAPTION")
    parsed = parse_webhook(payload)
    assert len(parsed) == 1 and parsed[0].type == "image"
    assert parsed[0].media_id == "media-veh901" and parsed[0].text == "Aquí va la foto"


def test_quick_reply_button_is_read_as_text(fresh):
    post_webhook(fresh, _text("Hola, necesito tanquear", message_id="wamid.Q1"))
    payload = _text("ignored", message_id="wamid.Q2")
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = "interactive"
    message["interactive"] = {"type": "button_reply", "button_reply": {"id": "qr_1", "title": "Sí, es para esa ruta"}}
    assert post_webhook(fresh, payload).json()["received"] == 1
    chat = conversation(fresh, GREEN)
    assert chat["messages"][-2]["text"] == "Sí, es para esa ruta" and chat["messages"][-2]["type"] == "text"
    assert chat["messages"][-1]["kind"] == "ask_photo" and chat["request"]["step"] == "photo"


def test_status_notifications_and_unsupported_types_are_ignored(fresh, db):
    statuses = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "statuses": [{"id": "wamid.X", "status": "delivered"}]}}]}]}
    assert post_webhook(fresh, statuses).json() == {"status": "ok", "received": 0, "duplicates": 0, "message_ids": []}
    audio = _text("x", message_id="wamid.AUDIO")
    message = audio["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = "audio"
    assert post_webhook(fresh, audio).json()["received"] == 0
    assert post_webhook(fresh, {}).json()["received"] == 0
    assert _count(db, InboundMessage) == 0


def test_message_timestamp_becomes_the_case_time_of_the_request(fresh):
    post_webhook(fresh, _text("Hola, necesito tanquear", hhmm="09:40", message_id="wamid.T1"))
    chat = conversation(fresh, GREEN)
    assert chat["messages"][0]["timestamp"] == at(today(), "09:40").isoformat()
    assert chat["request"]["occurred_at"] == at(today(), "09:40").isoformat()
    # The queue and the SLA use the real time, not the time of the case.
    created = datetime.fromisoformat(chat["request"]["created_at"])
    assert abs((now() - created).total_seconds()) < 60
    assert datetime.fromisoformat(chat["request"]["sla_due_at"]) - created == timedelta(minutes=10)


def test_outbound_messages_keep_the_cloud_api_request_body(fresh, db):
    post_webhook(fresh, _text("Hola, necesito tanquear", message_id="wamid.O1"))
    question = db.scalars(select(OutboundMessage).where(OutboundMessage.kind == "ask_service")).one()
    assert question.payload["messaging_product"] == "whatsapp" and question.payload["to"] == GREEN
    assert question.payload["type"] == "interactive"
    buttons = question.payload["interactive"]["action"]["buttons"]
    assert [b["reply"]["title"] for b in buttons] == ["Sí, es para esa ruta", "Es otro recorrido"]
    assert len(buttons) <= 3                         # limit of reply buttons of the Cloud API
    greeting = db.scalars(select(OutboundMessage).where(OutboundMessage.kind == "greeting")).one()
    assert greeting.payload["type"] == "text" and greeting.payload["text"]["body"] == greeting.body


# ----------------------------------------------------------------------------- verification (GET)

def test_webhook_verification_returns_the_challenge(fresh):
    response = fresh.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe",
                                                           "hub.verify_token": "test-verify-token",
                                                           "hub.challenge": "1158201444"})
    assert response.status_code == 200 and response.text == "1158201444"


def test_webhook_verification_rejects_a_wrong_token_or_mode(fresh):
    wrong = fresh.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "otro",
                                                        "hub.challenge": "1"})
    assert wrong.status_code == 403 and wrong.json()["code"] == "invalid_verify_token"
    mode = fresh.get("/api/webhooks/whatsapp", params={"hub.mode": "unsubscribe",
                                                       "hub.verify_token": "test-verify-token", "hub.challenge": "1"})
    assert mode.status_code == 403
    assert fresh.get("/api/webhooks/whatsapp").status_code == 403
