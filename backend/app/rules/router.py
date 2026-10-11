"""Rule catalog with versions. Only the coordinator changes thresholds."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.decisions.audit import Actor, get_actor, require_roles
from app.rules import repository

router = APIRouter(tags=["rules"])


class RuleUpdateIn(BaseModel):
    threshold: dict[str, float] | None = Field(default=None, description="Parámetros del umbral que cambian")
    points: int | None = Field(default=None, description="Puntos de la regla")
    reason: str | None = Field(default=None, max_length=500, description="Motivo del cambio")


@router.get("/rules", summary="Catálogo vigente, historial de versiones y precisión medida")
def list_rules(db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    return {"rules_version": repository.rules_version_label(db), "items": repository.catalog_payload(db),
            "can_edit": actor.role == "coordinator"}


@router.put("/rules/{code}", summary="Cambiar un umbral: crea una versión nueva (solo coordinador)")
def update_rule(code: str, body: RuleUpdateIn, db: Session = Depends(get_db),
                actor: Actor = Depends(require_roles("coordinator"))) -> dict:
    threshold = None
    if body.threshold is not None:
        threshold = {k: (int(v) if float(v).is_integer() else v) for k, v in body.threshold.items()}
    repository.update_rule(db, code, threshold, body.points, (body.reason or "").strip() or None, actor)
    db.commit()
    item = next(i for i in repository.catalog_payload(db) if i["code"] == code.upper())
    return {"rules_version": repository.rules_version_label(db), "rule": item}
