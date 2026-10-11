"""Roles (simulated with headers), audit log (insert-only) and domain events (outbox).

In production the login is SSO (OIDC) with MFA; in the prototype the role selector of the
interface sends `X-Demo-Role` and `X-Demo-User`.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.errors import ApiError
from app.models import AuditLog, OutboxEvent
from app.timeutil import iso

ROLES = ("technician", "coordinator", "finance", "support")
ROLE_LABELS = {
    "technician": "Técnico de Control y Monitoreo",
    "coordinator": "Coordinador",
    "finance": "Administración y finanzas",
    "support": "Soporte",
}
DEFAULT_USERS = {
    "technician": "Laura Gómez",
    "coordinator": "Andrés Molina",
    "finance": "Paola Ruiz",
    "support": "Soporte TI",
}
SYSTEM = "sistema"
ASSISTANT = "asistente"


@dataclass(frozen=True)
class Actor:
    user: str
    role: str

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


def get_actor(x_demo_role: str | None = Header(default=None),
              x_demo_user: str | None = Header(default=None)) -> Actor:
    role = (x_demo_role or "technician").strip().lower()
    if role not in ROLES:
        raise ApiError(400, f"Rol desconocido: {role}. Usa technician, coordinator, finance o support.", "unknown_role")
    user = unquote(x_demo_user).strip() if x_demo_user else DEFAULT_USERS[role]
    return Actor(user=user or DEFAULT_USERS[role], role=role)


def audit(db: Session, actor: Actor | str, action: str, entity: str, entity_id: object = None, *,
          summary: str | None = None, before: dict | None = None, after: dict | None = None,
          request_id: int | None = None) -> AuditLog:
    if isinstance(actor, Actor):
        name, role = actor.user, actor.role
    else:
        name, role = actor, None
    row = AuditLog(actor=name, role=role, action=action, entity=entity,
                   entity_id=None if entity_id is None else str(entity_id),
                   summary=summary, before=before, after=after, request_id=request_id)
    db.add(row)
    return row


def emit(db: Session, event_type: str, aggregate: str, aggregate_id: object, payload: dict) -> None:
    """Domain event in the transactional outbox. The prototype only records it (no worker)."""
    db.add(OutboxEvent(event_type=event_type, aggregate=aggregate, aggregate_id=str(aggregate_id), payload=payload))


def require_roles(*allowed: str):
    """Dependency: 403 for any other role, and the attempt stays in the audit log."""

    def dependency(request: Request, actor: Actor = Depends(get_actor)) -> Actor:
        if actor.role in allowed:
            return actor
        with SessionLocal() as session:  # own transaction: the attempt is recorded even though the call fails
            audit(session, actor, "access.denied", "endpoint", None,
                  summary=f"{actor.role_label} intentó {request.method} {request.url.path} sin permiso",
                  after={"method": request.method, "path": request.url.path, "allowed_roles": list(allowed)})
            session.commit()
        labels = ", ".join(ROLE_LABELS[r] for r in allowed)
        raise ApiError(403, f"Tu rol ({actor.role_label}) no puede hacer esta acción. Roles permitidos: {labels}.",
                       "forbidden", {"allowed_roles": list(allowed)})

    return dependency


def audit_payload(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "actor": row.actor,
        "role": row.role,
        "role_label": ROLE_LABELS.get(row.role, None) if row.role else None,
        "action": row.action,
        "entity": row.entity,
        "entity_id": row.entity_id,
        "request_id": row.request_id,
        "summary": row.summary,
        "before": row.before,
        "after": row.after,
        "created_at": iso(row.created_at),
    }


__all__ = ["Actor", "ROLES", "ROLE_LABELS", "SYSTEM", "ASSISTANT", "get_actor", "audit", "emit",
           "require_roles", "audit_payload", "get_db"]
