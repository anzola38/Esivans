"""Request lifecycle helpers: states, evaluation (rules + recommended amount) and JSON payloads."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.decisions.audit import ROLE_LABELS, SYSTEM, audit, audit_payload
from app.integrations.media import media_url
from app.ledger import service as ledger
from app.models import AuditLog, Evaluation, FuelRequest, RequestStatusLog
from app.rules import odometer as odo
from app.rules.amount import compute_amount
from app.rules.catalog import TRAFFIC_LIGHT_LABELS, traffic_light
from app.rules.engine import evaluate_request, summarize
from app.rules.repository import current_rules, rules_version_label
from app.timeutil import fmt_cop, hhmm, iso, now, seconds_between, to_local

SLA_MINUTES = 10
AUTHORIZATION_VALID_MINUTES = 120

OPEN_STATUSES = ("received", "identified", "awaiting_evidence", "ready", "in_review")
CLOSED_STATUSES = ("authorized", "rejected", "cancelled")
STATUS_LABELS = {
    "received": "Recibida",
    "identified": "Identificada",
    "awaiting_evidence": "Esperando evidencia",
    "ready": "Lista",
    "in_review": "En revisión",
    "authorized": "Autorizada",
    "rejected": "Rechazada",
    "cancelled": "Cerrada sin tanqueo",
}
MISSING_LABELS = {
    "driver": "Conductor no identificado",
    "vehicle": "Vehículo sin asignación vigente",
    "service": "Servicio o justificación",
    "photo": "Foto del tablero",
    "confirmation": "Confirmación del kilometraje",
}
ACTION_LABELS = {"approve": "Aprobada", "adjust": "Ajustada", "reject": "Rechazada"}
NOT_NEEDED_NAME = "No necesita tanquear según el cálculo"
NOT_NEEDED_EXPLANATION = "Con el nivel leído y la ruta pendiente, a cargar da 0 o menos"
NOT_NEEDED_REVIEW = "; el conductor pidió que lo revise el técnico."


def set_status(db: Session, req: FuelRequest, status: str, note: str | None = None) -> None:
    req.status = status
    if status in CLOSED_STATUSES:
        req.closed_at = now()
    db.add(RequestStatusLog(request_id=req.id, status=status, note=note))
    db.flush()


def case_now(req: FuelRequest) -> datetime:
    """Clock of the case: the simulated time of the request plus the real time elapsed since."""
    return to_local(req.occurred_at) + (now() - to_local(req.created_at))


def _inconsistency(name: str, explanation: str) -> dict:
    return {"code": "INC", "name": name, "points": 0, "rule_points": 0, "triggered": True, "evaluated": True,
            "explanation": explanation, "treatment": "review", "treatment_label": "Revisión",
            "kind": "inconsistency", "version": None, "threshold": None}


def evaluate(db: Session, req: FuelRequest) -> Evaluation:
    """Joins last refuel, km, efficiency and services; computes traffic light and amount.

    The context used is stored in JSONB with the rules version, so the recommendation can be
    reproduced in an audit.
    """
    rules = current_rules(db)
    version = rules_version_label(db)
    vehicle, evidence = req.vehicle, req.evidence
    extras: list[dict] = []
    checks: list[dict] = []
    calculation: dict = {"computable": False, "steps": [], "amount": None, "quantity": None, "cross_check": None,
                         "note": "Sin vehículo identificado: el técnico define el valor."}
    context: dict = {"occurred_at": iso(req.occurred_at), "rules_version": version,
                     "rule_versions": {code: rule.version for code, rule in rules.items()}}

    if vehicle is not None:
        tank = ledger.tank_of(vehicle.product)
        odometer = evidence.odometer_km if evidence else None
        book = ledger.refuel_context(db, vehicle, req.occurred_at, odometer, tank)
        services = ledger.services_context(db, vehicle, req.occurred_at,
                                           int(rules["R08"].params["window_h"]), int(rules["R09"].params["window_h"]))
        efficiency = ledger.efficiency_summary(vehicle, rules)
        used_efficiency = vehicle.reference_efficiency or efficiency["group_median"]
        price = ledger.reference_price(vehicle.product)
        calculation = compute_amount(
            level=evidence.fuel_level if evidence else None, capacity=vehicle.tank_capacity,
            largest_loads=book["largest_loads"], pending_services=services["pending_count"],
            km_per_service=services["km_per_service"], efficiency=used_efficiency, price=price,
            unit=vehicle.unit, efficiency_unit=vehicle.efficiency_unit,
            last_load=book["last_load_same"], km_since_last=book["km_last_same"])
        calculation["product"] = vehicle.product
        calculation["efficiency_used"] = used_efficiency
        calculation["efficiency_source"] = ("rendimiento del vehículo" if vehicle.reference_efficiency
                                            else "mediana de su grupo (rendimiento no concluyente)")
        suggested_quantity = calculation["quantity"] if calculation.get("needs_refuel") else None
        load = req.requested_quantity or suggested_quantity
        local = to_local(req.occurred_at)
        # What was reported: the reading of the photo or, if the driver typed the km, the typed value.
        reported = None
        if evidence:
            reported = evidence.odometer_km if evidence.odometer_source == "driver" else evidence.odometer_read
        rule_ctx = {
            "odometer": odometer,
            "odometer_reported": reported,
            "odometer_error": evidence.error_type if evidence else None,
            "odometer_proposed": evidence.proposed_odometer if evidence else None,
            "last_valid_odometer": book["last_valid_odometer"],
            "km_since_prev": book["km_since_prev"],
            "hours_since_prev": book["hours_since_prev"],
            "tank": tank,
            "unit": vehicle.unit,
            "load": load,
            "load_source": "requested" if req.requested_quantity else "suggested",
            "km_last_same": book["km_last_same"],
            "median_load": book["median_load"],
            "largest_loads": book["largest_loads"],
            "loads_24h": book["loads_24h"],
            "frozen_odometer": "V04" in (vehicle.flags or []),
            "vehicle_in_eom": services["vehicle_in_eom"],
            "services_24h": services["services_24h"],
            "services_3h": services["services_3h"],
            "hour": local.hour,
            "time_text": hhmm(local),
        }
        checks = evaluate_request(rule_ctx, rules)
        cross = calculation.get("cross_check")
        if cross and not cross["consistent"]:
            extras.append(_inconsistency("Inconsistencia entre fuentes", cross["explanation"]))
        if calculation.get("needs_refuel") is False:
            # Evaluated before the driver answers: who asked for the review is added later, only if he did.
            extras.append(_inconsistency(NOT_NEEDED_NAME, NOT_NEEDED_EXPLANATION + "."))
        context.update({
            "vehicle": ledger.vehicle_payload(vehicle, rules),
            "ledger": book,
            "services": services,
            "efficiency": efficiency,
            "vehicle_flags": ledger.vehicle_flags(vehicle, rules),
            "rule_inputs": rule_ctx,
            "reference_price": price,
            "requested_quantity": req.requested_quantity,
            "service_note": req.service_note,
        })
    elif req.driver_id is not None:  # known driver whose assignment is not current: not an unknown number
        extras.append(_inconsistency("Conductor sin vehículo asignado",
                                     "El conductor está registrado, pero no tiene un vehículo con asignación vigente; "
                                     "el técnico identifica el vehículo y decide."))
    else:
        extras.append(_inconsistency("Número no registrado",
                                     "El número de WhatsApp no corresponde a un conductor con asignación vigente; "
                                     "el técnico identifica al conductor y decide."))

    missing = [m for m in (req.missing or []) if m in ("service", "photo", "confirmation")]
    if missing:
        labels = ", ".join(MISSING_LABELS[m].lower() for m in missing)
        extras.append(_inconsistency("Solicitud incompleta",
                                     f"Pasó al técnico al cumplirse los {SLA_MINUTES} minutos sin: {labels}."))

    for check in checks:
        check["kind"] = "rule"
    points, reasons = summarize(checks)
    reasons = reasons + extras
    light = traffic_light(points, bool(extras))

    evaluation = req.evaluation or Evaluation(request_id=req.id)
    evaluation.context = context
    evaluation.rules_version = version
    evaluation.traffic_light = light
    evaluation.points = points
    evaluation.reasons = reasons
    evaluation.checks = checks
    evaluation.calculation = calculation
    evaluation.suggested_amount = calculation.get("amount")
    evaluation.suggested_quantity = calculation.get("quantity")
    evaluation.created_at = now()
    db.add(evaluation)
    req.evaluation = evaluation
    db.flush()
    codes = ", ".join(r["code"] for r in reasons if r.get("kind") == "rule") or "sin reglas"
    audit(db, SYSTEM, "request.evaluated", "evaluation", evaluation.id, request_id=req.id,
          summary=(f"Semáforo {TRAFFIC_LIGHT_LABELS[light].lower()} con {points} {"punto" if points == 1 else "puntos"} ({codes}); "
                   f"valor sugerido {fmt_cop(calculation.get('amount')) if calculation.get('amount') is not None else 'sin calcular'}; reglas {version}"),
          after={"traffic_light": light, "points": points, "rules": [r["code"] for r in reasons],
                 "suggested_amount": calculation.get("amount"), "rules_version": version})
    return evaluation


def mark_review_requested(req: FuelRequest) -> None:
    """The calculation said no refuel is needed and the driver asked for a review: the reason says so."""
    evaluation = req.evaluation
    if evaluation is None:
        return
    evaluation.reasons = [
        {**reason, "explanation": NOT_NEEDED_EXPLANATION + NOT_NEEDED_REVIEW} if reason.get("name") == NOT_NEEDED_NAME
        else reason for reason in (evaluation.reasons or [])]


def missing_items(req: FuelRequest) -> list[str]:
    data = req.data or {}
    items = []
    if req.driver_id is None:
        return ["driver"]
    if not data.get("service_resolved"):
        items.append("service")
    if req.evidence is None or (req.evidence.odometer_read is None and req.evidence.odometer_km is None):
        items.append("photo")
    elif not req.evidence.confirmed:
        items.append("confirmation")
    return items


# --------------------------------------------------------------------------- payloads

def _driver_payload(req: FuelRequest) -> dict | None:
    if req.driver is None:
        return None
    return {"id": req.driver.id, "name": req.driver.name, "phone": req.driver.phone}


def decision_payload(req: FuelRequest) -> dict | None:
    d = req.decision
    if d is None:
        return None
    return {
        "id": d.id, "action": d.action, "action_label": ACTION_LABELS.get(d.action, d.action),
        "amount": d.amount, "reason": d.reason, "one_click": d.one_click,
        "decided_by": d.decided_by, "role": d.role, "role_label": ROLE_LABELS.get(d.role, d.role),
        "decided_at": iso(d.decided_at),
        "original_amount": (d.original_calculation or {}).get("amount"),
        "original_calculation": d.original_calculation,
    }


def authorization_payload(req: FuelRequest) -> dict | None:
    a = req.authorization
    if a is None:
        return None
    case_expiry = to_local(req.occurred_at) + (to_local(a.expires_at) - to_local(req.created_at))
    return {
        "id": a.id, "provider": a.provider, "provider_label": ledger.PROVIDER_LABELS.get(a.provider, a.provider),
        "payment_method": ledger.PROVIDER_METHODS.get(a.provider, "chip"),
        "reference": a.reference, "product": a.product, "amount": a.amount,
        "enabled_by": a.enabled_by, "created_at": iso(a.created_at), "expires_at": iso(a.expires_at),
        "expires_at_case_time": iso(case_expiry), "valid_minutes": AUTHORIZATION_VALID_MINUTES,
        "expired": to_local(a.expires_at) < now(),
        "reconciled": a.reconciled_transaction_id is not None,
        "reconciled_difference": a.reconciled_difference,
    }


def enablement_payload(req: FuelRequest) -> dict | None:
    """Prefilled values to enable the chip or card in the provider's portal (the technician does it in the MVP)."""
    d, vehicle = req.decision, req.vehicle
    if d is None or d.action == "reject" or req.authorization is not None or vehicle is None:
        return None
    prefix = {"terpel": "TER", "gopass": "GOP"}.get(vehicle.provider, "REF")
    return {
        "provider": vehicle.provider,
        "provider_label": ledger.PROVIDER_LABELS.get(vehicle.provider, vehicle.provider),
        "payment_method": ledger.PROVIDER_METHODS.get(vehicle.provider, "chip"),
        "plate": vehicle.plate,
        "vehicle_code": vehicle.code,
        "product": vehicle.product,
        "amount": d.amount,
        "valid_minutes": AUTHORIZATION_VALID_MINUTES,
        "suggested_reference": f"{prefix}-{to_local(req.created_at):%y%m%d}-{req.id:04d}",
    }


def request_summary(req: FuelRequest) -> dict:
    """Row of the technician's queue."""
    current = now()
    ev = req.evaluation
    open_ = req.status in OPEN_STATUSES
    end = current if open_ else (req.closed_at or current)
    decided = req.decision is not None
    waiting_decision = open_ and not decided
    remaining = seconds_between(current, req.sla_due_at)
    reasons = (ev.reasons if ev else []) or []
    return {
        "id": req.id,
        "public_id": req.public_id,
        "status": req.status,
        "status_label": STATUS_LABELS.get(req.status, req.status),
        "stage": ("pending_enablement" if open_ and decided else req.status),
        "stage_label": ("Por habilitar" if open_ and decided else STATUS_LABELS.get(req.status, req.status)),
        "traffic_light": ev.traffic_light if ev else None,
        "traffic_light_label": TRAFFIC_LIGHT_LABELS.get(ev.traffic_light) if ev else None,
        "points": ev.points if ev else None,
        "rule_codes": [r["code"] for r in reasons if r.get("kind") == "rule"],
        "has_inconsistency": any(r.get("kind") == "inconsistency" for r in reasons),
        # One click needs a suggested amount to approve: without it the decision endpoint answers 422.
        "one_click_allowed": bool(ev and ev.traffic_light == "green" and req.status == "in_review" and not decided
                                  and (ev.suggested_amount or 0) > 0),
        "suggested_amount": ev.suggested_amount if ev else None,
        "requested_quantity": req.requested_quantity,
        "driver": _driver_payload(req),
        "wa_id": req.wa_id,
        "vehicle": ({"id": req.vehicle.id, "code": req.vehicle.code, "plate": req.vehicle.plate,
                     "fuel_type": req.vehicle.fuel_type,
                     "fuel_type_label": ledger.FUEL_TYPE_LABELS.get(req.vehicle.fuel_type),
                     "product": req.vehicle.product, "unit": req.vehicle.unit} if req.vehicle else None),
        "occurred_at": iso(req.occurred_at),
        "created_at": iso(req.created_at),
        "ready_at": iso(req.ready_at),
        "closed_at": iso(req.closed_at),
        "wait_seconds": max(seconds_between(req.created_at, end), 0),
        "sla_due_at": iso(req.sla_due_at),
        "sla_remaining_seconds": remaining if waiting_decision else None,
        "sla_breached": bool(waiting_decision and remaining < 0),
        "missing": [{"key": m, "label": MISSING_LABELS.get(m, m)} for m in (req.missing or [])],
        "decision_action": req.decision.action if req.decision else None,
        "decided_by": req.decision.decided_by if req.decision else None,
        "authorized_amount": req.authorization.amount if req.authorization else None,
    }


def status_history(req: FuelRequest) -> list[dict]:
    return [{"status": log.status, "status_label": STATUS_LABELS.get(log.status, log.status),
             "note": log.note, "at": iso(log.created_at)} for log in req.status_log]


def evidence_payload(req: FuelRequest) -> dict | None:
    e = req.evidence
    if e is None:
        return None
    return {
        "media_id": e.media_id,
        "photo_url": media_url(e.media_id),
        "photo_hash": e.photo_hash,
        "photo_path": e.photo_path,
        "odometer_read": e.odometer_read,
        "odometer_km": e.odometer_km,
        "odometer_source": e.odometer_source,
        "odometer_source_label": {"photo": "Foto del tablero", "driver": "Digitado por el conductor"}.get(e.odometer_source),
        "fuel_level": e.fuel_level,
        "confidence": e.confidence or {},
        "error_type": e.error_type,
        "error_label": odo.ERROR_LABELS.get(e.error_type) if e.error_type else None,
        "proposed_odometer": e.proposed_odometer,
        "confirmed_by_driver": e.confirmed,
        "received_at": iso(e.created_at),
    }


def request_detail(db: Session, req: FuelRequest) -> dict:
    """Everything the technician needs in one place."""
    ev = req.evaluation
    ctx = (ev.context if ev else {}) or {}
    book = ctx.get("ledger") or {}
    log = db.scalars(select(AuditLog).where(AuditLog.request_id == req.id).order_by(AuditLog.id)).all()
    chosen = req.chosen_service
    return {
        **request_summary(req),
        "step": req.step,
        "service": {
            "chosen": ledger.service_payload(chosen, req.occurred_at) if chosen else None,
            "note": req.service_note,
        },
        "evidence": evidence_payload(req),
        "context": {
            "last_refuel": book.get("last_refuel"),
            "last_refuel_same_fuel": book.get("last_refuel_same_fuel"),
            "km_since_last_refuel": book.get("km_since_prev"),
            "km_since_last_same_fuel": book.get("km_last_same"),
            "last_valid_odometer": book.get("last_valid_odometer"),
            "typical_load": book.get("median_load"),
            "largest_loads": book.get("largest_loads"),
            "loads_24h": book.get("loads_24h"),
            "providers": book.get("providers", []),
            "efficiency": ctx.get("efficiency"),
            "services": ctx.get("services"),
            "vehicle_flags": ctx.get("vehicle_flags", []),
            "vehicle": ctx.get("vehicle"),
        } if ev else None,
        "evaluation": {
            "traffic_light": ev.traffic_light,
            "traffic_light_label": TRAFFIC_LIGHT_LABELS.get(ev.traffic_light),
            "points": ev.points,
            "rules_version": ev.rules_version,
            "reasons": ev.reasons,
            "checks": ev.checks,
            "evaluated_at": iso(ev.created_at),
        } if ev else None,
        "calculation": ev.calculation if ev else None,
        "decision": decision_payload(req),
        "enablement": enablement_payload(req),
        "authorization": authorization_payload(req),
        "status_history": status_history(req),
        "audit": [audit_payload(row) for row in log],
    }


def sla_due(created_at: datetime) -> datetime:
    return created_at + timedelta(minutes=SLA_MINUTES)
