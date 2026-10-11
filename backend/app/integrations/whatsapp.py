"""WhatsApp Cloud API contract, simulated: signature, webhook payload and outbound messages.

The payload has the real shape of the Cloud API webhook and is signed with HMAC-SHA256 using
the app secret (header `X-Hub-Signature-256: sha256=<hex>`), verified over the raw body.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import OutboundMessage
from app.timeutil import to_local

PHONE_NUMBER_ID = "100000000000001"
DISPLAY_PHONE_NUMBER = "573000000000"
BUSINESS_ACCOUNT_ID = "200000000000002"
SIGNATURE_HEADER = "X-Hub-Signature-256"


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, header: str | None, secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(sign(body, secret), header.strip())


def new_message_id() -> str:
    return "wamid." + uuid.uuid4().hex.upper()


def build_webhook_payload(*, wa_id: str, profile_name: str, timestamp: datetime, text: str | None = None,
                          media_id: str | None = None, mime_type: str | None = None,
                          sha256: str | None = None, message_id: str | None = None) -> dict:
    """Same shape Meta sends to the webhook for a text or an image message."""
    message: dict = {"from": wa_id, "id": message_id or new_message_id(),
                     "timestamp": str(int(timestamp.timestamp()))}
    if media_id:
        message["type"] = "image"
        message["image"] = {"id": media_id, "mime_type": mime_type or "image/jpeg", "sha256": sha256 or ""}
        if text:
            message["image"]["caption"] = text
    else:
        message["type"] = "text"
        message["text"] = {"body": text or ""}
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": BUSINESS_ACCOUNT_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": DISPLAY_PHONE_NUMBER, "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": profile_name}, "wa_id": wa_id}],
                    "messages": [message],
                },
            }],
        }],
    }


def encode(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class IncomingMessage:
    wa_message_id: str
    wa_id: str
    type: str
    text: str | None
    media_id: str | None
    timestamp: datetime
    raw: dict


def parse_webhook(payload: dict) -> list[IncomingMessage]:
    """Extracts the messages; status notifications and unsupported types are ignored."""
    messages: list[IncomingMessage] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for message in value.get("messages", []) or []:
                kind = message.get("type")
                text, media_id = None, None
                if kind == "text":
                    text = (message.get("text") or {}).get("body")
                elif kind == "image":
                    image = message.get("image") or {}
                    media_id, text = image.get("id"), image.get("caption")
                elif kind == "interactive":  # quick reply button
                    interactive = message.get("interactive") or {}
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    text, kind = reply.get("title"), "text"
                elif kind == "button":
                    text, kind = (message.get("button") or {}).get("text"), "text"
                else:
                    continue
                try:
                    moment = datetime.fromtimestamp(int(message.get("timestamp")), tz=timezone.utc)
                except (TypeError, ValueError):
                    moment = datetime.now(timezone.utc)
                if not message.get("id") or not message.get("from"):
                    continue
                messages.append(IncomingMessage(message["id"], str(message["from"]), kind, text, media_id,
                                                to_local(moment), message))
    return messages


def send_message(db: Session, *, wa_id: str, body: str, case_time: datetime, kind: str = "text",
                 quick_replies: list[str] | None = None, request_id: int | None = None) -> OutboundMessage:
    """Simulates POST /{phone-number-id}/messages: the request body is stored instead of sent."""
    replies = [r for r in (quick_replies or [])][:3]  # the Cloud API allows up to 3 reply buttons
    if replies:
        payload = {
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": wa_id, "type": "interactive",
            "interactive": {"type": "button", "body": {"text": body}, "action": {"buttons": [
                {"type": "reply", "reply": {"id": f"qr_{i + 1}", "title": title}} for i, title in enumerate(replies)]}},
        }
    else:
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": wa_id,
                   "type": "text", "text": {"preview_url": False, "body": body}}
    message = OutboundMessage(wa_message_id=new_message_id(), wa_id=wa_id, request_id=request_id, kind=kind,
                              body=body, quick_replies=replies, payload=payload, case_time=case_time)
    db.add(message)
    db.flush()
    return message
