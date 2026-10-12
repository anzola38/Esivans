"""Decision of the technician, enablement of the payment method and audit log."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.decisions.audit import Actor, audit, audit_payload, emit, get_actor, require_roles
from app.errors import ApiError
from app.ledger import service as ledger
from app.models import AuditLog, Authorization, Decision, FuelRequest
from app.requests import conversation
from app.requests.service import (ACTION_LABELS, AUTHORIZATION_VALID_MINUTES, decision_payload, request_detail,
                                  set_status)
from app.timeutil import clock12, ddmmyyyy, fmt_cop, iso, now

router = APIRouter(tags=["decisions"])
DECISION_ROLES = ("technician", "coordinator")


class DecisionIn(BaseModel):
    action: Literal["approve", "adjust", "reject"]
    amount: int | None = Field(default=None, ge=0, description="Valor en pesos; obligatorio al ajustar")
    reason: str | None = Field(default=None, max_length=500)


class AuthorizationIn(BaseModel):
    reference: str = Field(min_length=3, max_length=60, description="Referencia que devuelve el portal del proveedor")
    provider: Literal["terpel", "gopass"] | None = None


def _already_decided(req: FuelRequest) -> ApiError:
    d = req.decision
    return ApiError(409, f"Esta solicitud ya fue decidida por {d.decided_by} ({ACTION_LABELS.get(d.action, d.action).lower()}) "
                         f"el {ddmmyyyy(d.decided_at)} a las {clock12(d.decided_at)}",
                    "already_decided", {"decision": decision_payload(req)})


@router.post("/requests/{request_id}/decision", summary="Aprobar, ajustar o rechazar (una sola decisión por solicitud)")
def decide(request_id: int, body: DecisionIn, db: Session = Depends(get_db),
           actor: Actor = Depends(require_roles(*DECISION_ROLES))) -> dict:
    req = db.scalars(select(FuelRequest).where(FuelRequest.id == request_id).with_for_update()).first()
    if req is None:
        raise ApiError(404, f"No existe la solicitud {request_id}.", "request_not_found")
    if req.decision is not None:
        raise _already_decided(req)
    if req.status != "in_review":
        raise ApiError(409, "La solicitud todavía no está en revisión: el asistente sigue reuniendo la información.",
                       "not_in_review", {"status": req.status})

    evaluation = req.evaluation
    suggested = evaluation.suggested_amount if evaluation else None
    light = evaluation.traffic_light if evaluation else "yellow"
    reason = (body.reason or "").strip() or None
    action, amount = body.action, body.amount

    if action == "approve" and amount is not None and suggested is not None and amount != suggested:
        action = "adjust"  # approving with a different amount is an adjustment
    if action in ("approve", "adjust") and req.vehicle is None:
        raise ApiError(422, "No se puede autorizar sin identificar el vehículo. Rechaza con el motivo o identifica al conductor.",
                       "vehicle_required")
    if action == "approve":
        if not suggested or suggested <= 0:
            raise ApiError(422, "No hay valor sugerido para aprobar: usa Ajustar e indica el valor y el motivo.",
                           "no_suggested_amount")
        amount = suggested
        if light != "green" and not reason:
            raise ApiError(422, "El semáforo no está en verde: para autorizar debes dejar el motivo.", "reason_required",
                           {"traffic_light": light})
    elif action == "adjust":
        if amount is None or amount <= 0:
            raise ApiError(422, "Indica el valor ajustado en pesos (mayor a cero).", "amount_required")
        if not reason:
            raise ApiError(422, "Ajustar el valor exige un motivo.", "reason_required")
        cap = (evaluation.calculation or {}).get("cap_amount") if evaluation else None
        if cap and amount > cap:
            raise ApiError(422, f"El valor supera el tope del vehículo ({fmt_cop(cap)}).", "above_cap", {"cap_amount": cap})
    else:  # reject
        amount = None
        if not reason:
            raise ApiError(422, "Rechazar exige un motivo: el conductor lo recibe en el chat.", "reason_required")

    one_click = action == "approve" and light == "green" and not reason
    decision = Decision(request_id=req.id, decided_by=actor.user, role=actor.role, action=action, amount=amount,
                        reason=reason, one_click=one_click, decided_at=now(),
                        original_calculation=dict(evaluation.calculation or {}) if evaluation else {})
    db.add(decision)
    try:
        db.flush()
    except IntegrityError as exc:  # two technicians at the same time: the second one loses
        db.rollback()
        req = db.get(FuelRequest, request_id)
        raise _already_decided(req) from exc
    req.decision = decision

    verb = {"approve": "aprobó", "adjust": "ajustó", "reject": "rechazó"}[action]
    detail = (f" por {fmt_cop(amount)}" if amount else "") + (
        f" (sugerido {fmt_cop(suggested)})" if action == "adjust" and suggested is not None else "")
    audit(db, actor, f"decision.{action}", "decision", decision.id, request_id=req.id,
          summary=f"{actor.user} {verb} la solicitud{detail}" + (f". Motivo: {reason}" if reason else " en un clic"),
          before={"suggested_amount": suggested, "traffic_light": light,
                  "points": evaluation.points if evaluation else None,
                  "rules_version": evaluation.rules_version if evaluation else None},
          after={"action": action, "amount": amount, "reason": reason, "one_click": one_click})
    emit(db, "DecisionRecorded", "request", req.id,
         {"request_id": req.id, "action": action, "amount": amount, "decided_by": actor.user,
          "traffic_light": light, "one_click": one_click})
    if action == "reject":
        set_status(db, req, "rejected", f"Rechazada por {actor.user}: {reason}")
        conversation.notify_rejected(db, req, decision)
    db.commit()
    db.refresh(req)
    return request_detail(db, req)


@router.post("/requests/{request_id}/authorization",
             summary="Confirmar la habilitación del chip o la tarjeta (la hace el técnico en el MVP)")
def confirm_authorization(request_id: int, body: AuthorizationIn, db: Session = Depends(get_db),
                          actor: Actor = Depends(require_roles(*DECISION_ROLES))) -> dict:
    req = db.scalars(select(FuelRequest).where(FuelRequest.id == request_id).with_for_update()).first()
    if req is None:
        raise ApiError(404, f"No existe la solicitud {request_id}.", "request_not_found")
    if req.authorization is not None:
        a = req.authorization
        raise ApiError(409, f"Esta solicitud ya fue habilitada por {a.enabled_by} con la referencia {a.reference}.",
                       "already_authorized")
    decision = req.decision
    if decision is None or decision.action == "reject" or req.vehicle is None:
        raise ApiError(409, "Solo se habilita una solicitud aprobada o ajustada.", "not_approved")

    reference = body.reference.strip()
    provider = body.provider or req.vehicle.provider
    current = now()
    authorization = Authorization(request_id=req.id, decision_id=decision.id, provider=provider, reference=reference,
                                  product=req.vehicle.product, amount=decision.amount, enabled_by=actor.user,
                                  created_at=current,
                                  expires_at=current + timedelta(minutes=AUTHORIZATION_VALID_MINUTES))
    db.add(authorization)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "Esta solicitud ya fue habilitada.", "already_authorized") from exc
    req.authorization = authorization
    method = ledger.PROVIDER_METHODS.get(provider, "chip")
    set_status(db, req, "authorized", f"{method.capitalize()} habilitado por {actor.user}, referencia {reference}")
    audit(db, actor, "authorization.enabled", "authorization", authorization.id, request_id=req.id,
          summary=(f"{actor.user} habilitó el {method} en {ledger.PROVIDER_LABELS.get(provider, provider)}: "
                   f"{fmt_cop(authorization.amount)} de {authorization.product}, referencia {reference}, "
                   f"vigente {AUTHORIZATION_VALID_MINUTES // 60} horas"),
          after={"provider": provider, "reference": reference, "product": authorization.product,
                 "amount": authorization.amount, "expires_at": iso(authorization.expires_at)})
    conversation.notify_authorized(db, req, authorization)
    db.commit()
    db.refresh(req)
    return request_detail(db, req)


@router.get("/audit", summary="Bitácora de solo inserción")
def list_audit(request_id: int | None = None, action: str | None = None, entity: str | None = None,
               limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db),
               actor: Actor = Depends(get_actor)) -> dict:
    query = select(AuditLog)
    if request_id is not None:
        query = query.where(AuditLog.request_id == request_id)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    if entity:
        query = query.where(AuditLog.entity == entity)
    rows = db.scalars(query.order_by(AuditLog.id.desc()).limit(limit)).all()
    return {"items": [audit_payload(r) for r in rows], "append_only": True}
