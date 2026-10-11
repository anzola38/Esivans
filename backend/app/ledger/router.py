"""Single refuel ledger per vehicle (Terpel + GoPass + EOM)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.decisions.audit import Actor, get_actor
from app.ledger import service
from app.models import Vehicle
from app.rules.repository import current_rules

router = APIRouter(tags=["ledger"])


@router.get("/vehicles", summary="Vehículos del piloto con su ficha técnica y reglas por vehículo")
def list_vehicles(db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    rules = current_rules(db)
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.code)).all()
    return {"items": [{**service.vehicle_payload(v, rules), "efficiency": service.efficiency_summary(v, rules)}
                      for v in vehicles]}


@router.get("/vehicles/{vehicle_ref}/ledger", summary="Libro único de tanqueos del vehículo")
def vehicle_ledger(vehicle_ref: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    vehicle = service.vehicle_by_ref(db, vehicle_ref)
    return service.ledger_payload(db, vehicle, current_rules(db))
