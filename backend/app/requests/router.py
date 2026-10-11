"""Webhook of WhatsApp and the technician's queue."""
from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.decisions.audit import Actor, get_actor
from app.errors import ApiError
from app.integrations.whatsapp import SIGNATURE_HEADER, parse_webhook, verify_signature
from app.models import FuelRequest, InboundMessage
from app.requests import conversation
from app.requests.service import CLOSED_STATUSES, OPEN_STATUSES, STATUS_LABELS, request_detail, request_summary

router = APIRouter(tags=["requests"])


def _process_in_background(inbound_id: int) -> None:
    with SessionLocal() as db:
        conversation.process_inbound(db, inbound_id)


def handle_webhook(db: Session, raw_body: bytes, signature: str | None, background: BackgroundTasks) -> dict:
    """Single entry for real webhooks and for the simulator: verify, deduplicate, store, answer 200.

    The conversation runs after the response (BackgroundTasks), so WhatsApp never waits for the AI
    nor for an integration. In the MVP that work goes to Celery workers.
    """
    if not verify_signature(raw_body, signature, get_settings().whatsapp_app_secret):
        raise ApiError(401, "Firma inválida: el webhook no viene firmado con el secreto de la aplicación.",
                       "invalid_signature")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "El cuerpo del webhook no es JSON válido.", "invalid_payload") from exc

    received, duplicates, ids = 0, 0, []
    for incoming in parse_webhook(payload):
        exists = db.scalar(select(InboundMessage.id).where(InboundMessage.wa_message_id == incoming.wa_message_id))
        if exists:
            duplicates += 1
            continue
        row = InboundMessage(wa_message_id=incoming.wa_message_id, wa_id=incoming.wa_id, type=incoming.type,
                             text=incoming.text, media_id=incoming.media_id, case_time=incoming.timestamp,
                             payload=incoming.raw)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # the same message arrived twice at the same time
            db.rollback()
            duplicates += 1
            continue
        received += 1
        ids.append(row.id)
        background.add_task(_process_in_background, row.id)
    return {"status": "ok", "received": received, "duplicates": duplicates, "message_ids": ids}


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse, summary="Verificación del webhook (hub.challenge)")
def verify_webhook(hub_mode: str | None = Query(default=None, alias="hub.mode"),
                   hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
                   hub_challenge: str | None = Query(default=None, alias="hub.challenge")) -> str:
    if hub_mode == "subscribe" and hub_verify_token == get_settings().whatsapp_verify_token:
        return hub_challenge or ""
    raise ApiError(403, "Token de verificación inválido.", "invalid_verify_token")


@router.post("/webhooks/whatsapp", summary="Webhook de la WhatsApp Cloud API (firma X-Hub-Signature-256)")
async def whatsapp_webhook(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    raw = await request.body()
    return handle_webhook(db, raw, request.headers.get(SIGNATURE_HEADER), background)


@router.get("/requests", summary="Cola de solicitudes con semáforo, espera y SLA")
def list_requests(status: str | None = Query(default=None, description="Estado, lista separada por comas, 'open' o 'closed'"),
                  db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    conversation.escalate_overdue(db)
    query = select(FuelRequest)
    if status:
        wanted: list[str] = []
        for value in (s.strip().lower() for s in status.split(",") if s.strip()):
            if value == "open":
                wanted += OPEN_STATUSES
            elif value == "closed":
                wanted += CLOSED_STATUSES
            elif value in STATUS_LABELS:
                wanted.append(value)
            else:
                raise ApiError(422, f"Estado desconocido: {value}.", "unknown_status",
                               {"allowed": list(STATUS_LABELS) + ["open", "closed"]})
        query = query.where(FuelRequest.status.in_(wanted))
    rows = db.scalars(query.order_by(FuelRequest.created_at, FuelRequest.id)).all()
    items = [request_summary(r) for r in rows]
    items.sort(key=lambda i: (i["status"] in CLOSED_STATUSES, -i["wait_seconds"] if i["status"] in OPEN_STATUSES else 0,
                              i["id"] if i["status"] in OPEN_STATUSES else -i["id"]))
    counts = {"total": len(items), "in_review": 0, "green": 0, "yellow": 0, "red": 0, "sla_breached": 0}
    for item in items:
        if item["status"] == "in_review":
            counts["in_review"] += 1
            if item["traffic_light"] in counts and item["decision_action"] is None:
                counts[item["traffic_light"]] += 1
        counts["sla_breached"] += 1 if item["sla_breached"] else 0
    return {"items": items, "counts": counts}


@router.get("/requests/{request_id}", summary="Detalle completo de una solicitud")
def get_request(request_id: int, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    req = db.get(FuelRequest, request_id)
    if req is None:
        raise ApiError(404, f"No existe la solicitud {request_id}.", "request_not_found")
    return request_detail(db, req)
