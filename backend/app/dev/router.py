"""Demo routes: reset the seed and the driver simulator (WhatsApp with the real contract).

Only available with DEMO_MODE=true.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.decisions.audit import Actor, audit, get_actor
from app.errors import ApiError
from app.integrations import media
from app.integrations.whatsapp import SIGNATURE_HEADER, build_webhook_payload, encode, sign
from app.ledger import service as ledger
from app.models import (Assignment, Authorization, Driver, FuelRequest, InboundMessage, OutboundMessage, OutboxEvent,
                        ProviderTransaction, Vehicle)
from app.requests import conversation
from app.requests.router import handle_webhook
from app.requests.service import (OPEN_STATUSES, authorization_payload, decision_payload, request_summary,
                                  status_history)
from app.seed import data as seed
from app.seed import loader
from app.timeutil import at, iso, now, parse_iso, to_local, today


def demo_only() -> None:
    if not get_settings().demo_mode:
        raise ApiError(404, "Las rutas de demo están desactivadas (DEMO_MODE=false).", "demo_disabled")


router = APIRouter(prefix="/dev", tags=["demo"], dependencies=[Depends(demo_only)])


class SimulatedMessageIn(BaseModel):
    wa_id: str | None = Field(default=None, description="Número del conductor; si falta se toma del caso")
    case_code: str | None = Field(default=None, description="Caso de demo (GREEN, VEH015, VEH199, NO_FUEL, UNREGISTERED)")
    type: Literal["text", "image"] = "text"
    text: str | None = None
    media_id: str | None = None
    simulated_time: str | None = Field(default=None, description="Hora del caso: 'HH:MM' de hoy o fecha ISO 8601")

    @model_validator(mode="after")
    def _check(self) -> "SimulatedMessageIn":
        if self.type == "text" and not (self.text or "").strip():
            raise ValueError("text es obligatorio en un mensaje de texto")
        if self.type == "image" and not self.media_id:
            raise ValueError("media_id es obligatorio en un mensaje con foto")
        if not self.wa_id and not self.case_code:
            raise ValueError("indica wa_id o case_code")
        return self


def _case(code: str) -> dict:
    for case in seed.DEMO_CASES:
        if case["code"] == code.upper():
            return case
    raise ApiError(404, f"No existe el caso de demo {code}.", "case_not_found",
                   {"allowed": [c["code"] for c in seed.DEMO_CASES]})


def _case_payload(db: Session, case: dict) -> dict:
    vehicle = db.scalars(select(Vehicle).where(Vehicle.code == case["vehicle"])).first() if case["vehicle"] else None
    driver = None
    if vehicle:
        assignment = db.scalars(select(Assignment).where(Assignment.vehicle_id == vehicle.id)).first()
        driver = assignment.driver if assignment else None
    wa_id = driver.phone if driver else case.get("wa_id")
    photo = None
    if case.get("media"):
        path = media.media_path(case["media"])
        photo = {"media_id": case["media"], "url": media.media_url(case["media"]),
                 "mime_type": media.mime_of(path) if path else None,
                 "label": "Foto de ejemplo del tablero"}
    return {
        "code": case["code"],
        "title": case["title"],
        "description": case["description"],
        "driver": {"id": driver.id, "name": driver.name, "phone": driver.phone} if driver
                  else {"id": None, "name": case.get("driver_name", "Sin registrar"), "phone": wa_id},
        "wa_id": wa_id,
        "vehicle": ledger.vehicle_payload(vehicle) if vehicle else None,
        "plate": vehicle.plate if vehicle else None,
        "case_time": case["time"],
        "case_datetime": iso(at(today(), case["time"])),
        "script": case["script"],
        "photo": photo,
        "expected": case["expected"],
    }


@router.post("/reset", summary="Reiniciar demo: vuelve a cargar la semilla")
def reset_demo(db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    summary = loader.reset_and_load(db)
    audit(db, actor, "demo.reset", "seed", summary["seed_date"], summary=f"{actor.user} reinició la demo")
    db.commit()
    return {"status": "ok", "message": "Demo reiniciada: semilla cargada de nuevo.", **summary}


@router.get("/simulator/cases", summary="Casos de demo del simulador del conductor")
def simulator_cases(db: Session = Depends(get_db)) -> dict:
    current = loader.seed_date(db)
    return {"seed_date": current, "seed_is_stale": current != today().isoformat(),
            "ai_provider": get_settings().ai_provider,
            "items": [_case_payload(db, case) for case in seed.DEMO_CASES]}


def _simulated_moment(value: str | None, case: dict | None, wa_id: str, db: Session) -> datetime:
    """Case clock: the first message fixes the time; the following ones advance with real time."""
    if value:
        text = value.strip()
        base = at(today(), text) if len(text) <= 5 and ":" in text else parse_iso(text)
    elif case:
        base = at(today(), case["time"])
    else:
        return now()
    open_request = db.scalars(select(FuelRequest).where(FuelRequest.wa_id == wa_id, FuelRequest.status.in_(OPEN_STATUSES))
                              .order_by(FuelRequest.id.desc())).first()
    if open_request is not None:
        return conversation.case_now(open_request)
    return base


@router.post("/simulator/messages", summary="Enviar un mensaje como el conductor (texto o foto por media_id)")
def simulator_message(body: SimulatedMessageIn, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    case = _case(body.case_code) if body.case_code else None
    wa_id = body.wa_id
    if not wa_id and case:
        wa_id = _case_payload(db, case)["wa_id"]
    wa_id = "".join(ch for ch in (wa_id or "") if ch.isdigit())
    if not wa_id:
        raise ApiError(422, "No se pudo determinar el número del conductor.", "wa_id_required")
    driver = db.scalars(select(Driver).where(Driver.phone == wa_id)).first()

    mime_type, digest = None, None
    if body.type == "image":
        path = media.media_path(body.media_id or "")
        if path is None:
            raise ApiError(404, f"No existe la foto {body.media_id} en el almacenamiento de ejemplo.", "media_not_found")
        mime_type = media.mime_of(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()

    moment = _simulated_moment(body.simulated_time, case, wa_id, db)
    payload = build_webhook_payload(wa_id=wa_id, profile_name=driver.name if driver else "Sin registrar",
                                    timestamp=moment, text=(body.text or "").strip() or None,
                                    media_id=body.media_id if body.type == "image" else None,
                                    mime_type=mime_type, sha256=digest)
    raw = encode(payload)
    signature = sign(raw, get_settings().whatsapp_app_secret)
    # Same handler as POST /api/webhooks/whatsapp: signature, idempotency, storage and 200.
    result = handle_webhook(db, raw, signature, background)
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    return {"status": "accepted", "wa_id": wa_id, "wa_message_id": message["id"], "case_time": iso(moment),
            "webhook": {"path": "/api/webhooks/whatsapp", "signature_header": SIGNATURE_HEADER,
                        "signed": True, "result": result},
            "payload": payload}


@router.get("/simulator/conversations/{wa_id}", summary="Conversación del conductor y su solicitud")
def simulator_conversation(wa_id: str, db: Session = Depends(get_db)) -> dict:
    conversation.escalate_overdue(db)
    inbound = db.scalars(select(InboundMessage).where(InboundMessage.wa_id == wa_id)).all()
    outbound = db.scalars(select(OutboundMessage).where(OutboundMessage.wa_id == wa_id)).all()
    messages = []
    for m in inbound:
        messages.append({"id": f"in-{m.id}", "direction": "inbound", "type": m.type, "text": m.text,
                         "media_id": m.media_id, "media_url": media.media_url(m.media_id), "quick_replies": [],
                         "kind": "driver", "timestamp": iso(m.case_time), "created_at": iso(m.created_at),
                         "request_id": m.request_id, "_order": (to_local(m.created_at), 0, m.id)})
    for m in outbound:
        messages.append({"id": f"out-{m.id}", "direction": "outbound", "type": "text", "text": m.body,
                         "media_id": None, "media_url": None, "quick_replies": m.quick_replies or [],
                         "kind": m.kind, "timestamp": iso(m.case_time), "created_at": iso(m.created_at),
                         "request_id": m.request_id, "_order": (to_local(m.created_at), 1, m.id)})
    messages.sort(key=lambda item: item.pop("_order"))
    pending = any(m.processed_at is None for m in inbound)

    req = db.scalars(select(FuelRequest).where(FuelRequest.wa_id == wa_id).order_by(FuelRequest.id.desc())).first()
    request_payload = None
    if req is not None:
        request_payload = {**request_summary(req), "step": req.step, "is_open": req.status in OPEN_STATUSES,
                           "status_history": status_history(req), "decision": decision_payload(req),
                           "authorization": authorization_payload(req)}
    driver = db.scalars(select(Driver).where(Driver.phone == wa_id)).first()
    last_out = next((m for m in reversed(messages) if m["direction"] == "outbound"), None)
    last_is_out = bool(messages) and messages[-1]["direction"] == "outbound"
    return {
        "wa_id": wa_id,
        "driver": {"id": driver.id, "name": driver.name, "phone": driver.phone} if driver else None,
        "assistant_typing": pending,
        "quick_replies": (last_out["quick_replies"] if last_out and last_is_out else []),
        "messages": messages,
        "request": request_payload,
    }


@router.get("/samples/terpel", response_class=PlainTextResponse, summary="CSV de ejemplo de Terpel para la conciliación")
def sample_terpel(db: Session = Depends(get_db)) -> PlainTextResponse:
    """Dates are rendered relative to today; one extra row is added per authorization issued in the
    demo with Terpel, so the reconciliation "authorized vs. recorded" has something to match."""
    template = (get_settings().samples_dir / "terpel_ejemplo.csv").read_text(encoding="utf-8")
    day = today()
    for offset in range(0, 4):
        template = template.replace("{{D%d}}" % offset, (day - timedelta(days=offset)).isoformat())
    lines = [template.rstrip("\n")]
    rows = db.execute(select(Authorization, FuelRequest).join(FuelRequest, FuelRequest.id == Authorization.request_id)
                      .where(Authorization.provider == "terpel", Authorization.reconciled_transaction_id.is_(None),
                             Authorization.created_at >= now() - timedelta(hours=36)).order_by(Authorization.id)).all()
    for authorization, req in rows:
        vehicle = req.vehicle
        last = db.scalars(select(ProviderTransaction).where(ProviderTransaction.vehicle_id == vehicle.id)
                          .order_by(ProviderTransaction.timestamp.desc())).first()
        station = last.station if last else "EDS Cereté Norte"
        price = ledger.reference_price(authorization.product)
        quantity = round(authorization.amount / price, 3)
        odometer = req.evidence.odometer_km if req.evidence and req.evidence.odometer_km else ""
        moment = to_local(authorization.created_at) + timedelta(minutes=12)
        lines.append(",".join(str(v) for v in [
            f"TER-AUT{authorization.id:04d}", moment.strftime("%Y-%m-%d %H:%M:%S"), vehicle.code, vehicle.plate, station,
            "NORTE", authorization.product, f"{quantity:.3f}", vehicle.unit, int(price), authorization.amount, odometer,
            "En línea"]))
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'inline; filename="terpel_ejemplo.csv"'})


@router.get("/outbox", summary="Eventos de dominio registrados en la outbox")
def outbox(limit: int = 100, db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(OutboxEvent).order_by(OutboxEvent.id.desc()).limit(limit)).all()
    return {"items": [{"id": r.id, "event_type": r.event_type, "aggregate": r.aggregate, "aggregate_id": r.aggregate_id,
                       "payload": r.payload, "created_at": iso(r.created_at), "published_at": iso(r.published_at)}
                      for r in rows]}
