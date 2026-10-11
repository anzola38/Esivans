"""Alerts for the coordinator: refuels, vehicles and reconciliation differences."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.decisions.audit import Actor, get_actor, require_roles
from app.errors import ApiError
from app.reconciliation import service

router = APIRouter(tags=["alerts"])

RESULT_ALIASES = {"confirmado": "confirmed", "justificado": "justified", "error de dato": "data_error",
                  "error_de_dato": "data_error"}


class AlertReviewIn(BaseModel):
    review_result: str = Field(description="confirmed | justified | data_error (también Confirmado, Justificado o Error de dato)")
    comment: str = Field(min_length=3, max_length=500)


@router.get("/alerts", summary="Alertas ordenadas por prioridad y puntos")
def list_alerts(status: Literal["open", "reviewed"] | None = None,
                kind: Literal["refuel", "vehicle", "reconciliation"] | None = None,
                priority: Literal["high", "medium", "low"] | None = None,
                db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    items = [service.alert_payload(a) for a in service.list_alerts(db, status=status, kind=kind, priority_level=priority)]
    open_items = [i for i in items if i["status"] == "open"]
    reviewed = [i for i in items if i["status"] == "reviewed"]
    confirmed = sum(1 for i in reviewed if i["review_result"] == "confirmed")
    return {
        "items": items,
        "counts": {
            "total": len(items),
            "open": len(open_items),
            "reviewed": len(reviewed),
            "open_high": sum(1 for i in open_items if i["priority"] == "high"),
            "open_medium": sum(1 for i in open_items if i["priority"] == "medium"),
            "open_low": sum(1 for i in open_items if i["priority"] == "low"),
            "overdue": sum(1 for i in open_items if i["overdue"]),
            "confirmed": confirmed,
            "precision": round(confirmed / len(reviewed), 3) if reviewed else None,
        },
    }


@router.patch("/alerts/{alert_id}", summary="Registrar el resultado de la revisión (con comentario, autor y fecha)")
def review_alert(alert_id: int, body: AlertReviewIn, db: Session = Depends(get_db),
                 actor: Actor = Depends(require_roles("coordinator", "technician"))) -> dict:
    result = body.review_result.strip().lower()
    result = RESULT_ALIASES.get(result, result)
    if result not in service.REVIEW_RESULTS:
        raise ApiError(422, "El resultado debe ser Confirmado, Justificado o Error de dato.", "invalid_review_result",
                       {"allowed": list(service.REVIEW_RESULTS)})
    alert = service.review_alert(db, alert_id, result, body.comment.strip(), actor)
    db.commit()
    return service.alert_payload(alert)
