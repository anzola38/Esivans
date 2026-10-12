"""Conversation orchestrator: turns WhatsApp messages into a complete request.

Slot filling: the assistant asks exactly for what is missing (service or justification, photo
of the dashboard, confirmation of what was read) and then hands the request to the rules
engine. The AI adapter only extracts data; every decision is taken here or by the technician.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.decisions.audit import ASSISTANT, SYSTEM, audit, emit
from app.integrations import media
from app.integrations.ai import get_ai_provider
from app.integrations.ai.base import MIN_CONFIDENCE, ExtractedRequest
from app.integrations.whatsapp import send_message
from app.ledger import service as ledger
from app.models import (Assignment, Authorization, Decision, Driver, Evidence, FuelRequest, InboundMessage,
                        OutboundMessage, Vehicle)
from app.requests import service as requests_service
from app.requests.service import (AUTHORIZATION_VALID_MINUTES, OPEN_STATUSES, case_now, evaluate, missing_items,
                                  set_status, sla_due)
from app.rules import odometer as odo
from app.rules.repository import current_rules
from app.timeutil import clock12, fmt_cop, fmt_int, fmt_num, fmt_pct, fmt_unit, now, parse_iso, to_local

log = logging.getLogger(__name__)

PRIVACY_NOTICE = ("Aviso de privacidad: usamos tu número, tu asignación y las fotos que envíes solo para gestionar "
                  "el suministro de combustible (Ley 1581 de 2012).")
LEVEL_FRACTIONS = {0: "vacío", 1: "⅛", 2: "¼", 3: "⅜", 4: "½", 5: "⅝", 6: "¾", 7: "⅞", 8: "lleno"}


def level_text(level: float | None) -> str:
    if level is None:
        return "sin lectura"
    eighths = max(0, min(8, round(level * 8)))
    label = LEVEL_FRACTIONS[eighths]
    return f"{label} ({fmt_pct(level)})" if eighths in (0, 8) else f"{label} de tanque ({fmt_pct(level)})"


def first_name(driver: Driver | None) -> str:
    return driver.name.split()[0] if driver else ""


# --------------------------------------------------------------------------- outbound helpers

def _say(db: Session, req: FuelRequest | None, wa_id: str, body: str, *, kind: str = "text",
         quick_replies: list[str] | None = None, case_time: datetime | None = None) -> OutboundMessage:
    moment = case_time or (case_now(req) if req else now())
    return send_message(db, wa_id=wa_id, body=body, case_time=moment, kind=kind,
                        quick_replies=quick_replies, request_id=req.id if req else None)


def notify_authorized(db: Session, req: FuelRequest, authorization: Authorization) -> None:
    expiry = to_local(req.occurred_at) + (to_local(authorization.expires_at) - to_local(req.created_at))
    hours = AUTHORIZATION_VALID_MINUTES // 60
    method = ledger.PROVIDER_METHODS.get(authorization.provider, "chip")
    enabled = "habilitada" if method == "tarjeta" else "habilitado"      # "tu tarjeta" (GoPass) is feminine
    body = (f"Autorizado, {first_name(req.driver)}: {fmt_cop(authorization.amount)} de {authorization.product}. "
            f"Referencia: {authorization.reference}. Vigencia: {hours} horas (hasta las {clock12(expiry)}). "
            f"Tu {method} ya está {enabled} solo por ese valor.")
    decision = req.decision
    if decision is not None and decision.action == "adjust" and decision.reason:
        body += f" El técnico ajustó el valor. Motivo: {decision.reason.rstrip('. ')}."
    _say(db, req, req.wa_id, body, kind="authorization")


def notify_rejected(db: Session, req: FuelRequest, decision: Decision) -> None:
    body = (f"{first_name(req.driver) or 'Hola'}, tu solicitud no fue autorizada. Motivo: {decision.reason.rstrip('. ')}. "
            "Si necesitas ayuda, responde este mensaje y te atiende el técnico de turno.")
    _say(db, req, req.wa_id, body, kind="rejection")


# --------------------------------------------------------------------------- lookups

def _open_request(db: Session, *, vehicle_id: int | None = None, wa_id: str | None = None) -> FuelRequest | None:
    query = select(FuelRequest).where(FuelRequest.status.in_(OPEN_STATUSES)).order_by(FuelRequest.id.desc())
    if vehicle_id is not None:
        query = query.where(FuelRequest.vehicle_id == vehicle_id)
    else:
        query = query.where(FuelRequest.wa_id == wa_id, FuelRequest.vehicle_id.is_(None))
    return db.scalars(query).first()


def _current_vehicle(db: Session, driver: Driver) -> Vehicle | None:
    current = now()
    assignment = db.scalars(select(Assignment).where(
        Assignment.driver_id == driver.id, Assignment.valid_from <= current,
        (Assignment.valid_to.is_(None)) | (Assignment.valid_to >= current)).order_by(Assignment.valid_from.desc())).first()
    return assignment.vehicle if assignment else None


def _active_authorization(db: Session, vehicle_id: int) -> tuple[FuelRequest, Authorization] | None:
    row = db.execute(select(FuelRequest, Authorization).join(Authorization, Authorization.request_id == FuelRequest.id)
                     .where(FuelRequest.vehicle_id == vehicle_id, Authorization.expires_at > now())
                     .order_by(Authorization.id.desc())).first()
    return (row[0], row[1]) if row else None


# --------------------------------------------------------------------------- entry point

def process_inbound(db: Session, inbound_id: int) -> None:
    message = db.get(InboundMessage, inbound_id)
    if message is None or message.processed_at is not None:
        return
    try:
        _process(db, message)
        message.processed_at = now()
        db.commit()
    except Exception:  # noqa: BLE001 - never lose a message silently
        db.rollback()
        log.exception("Error procesando el mensaje %s", inbound_id)
        message = db.get(InboundMessage, inbound_id)
        message.processed_at = now()
        # The privacy notice of a first contact was rolled back with the failed transaction: send it again here,
        # because the error message below makes the next message look like a second contact.
        if db.scalars(select(OutboundMessage.id).where(OutboundMessage.wa_id == message.wa_id).limit(1)).first() is None:
            send_message(db, wa_id=message.wa_id, body=PRIVACY_NOTICE, case_time=message.case_time, kind="privacy_notice")
        send_message(db, wa_id=message.wa_id, case_time=message.case_time, kind="error",
                     body="Tuvimos un problema procesando tu mensaje. El técnico de turno ya fue avisado y te atiende por este medio.")
        audit(db, SYSTEM, "message.failed", "inbound_message", inbound_id,
              summary="Error al procesar un mensaje entrante; se avisó al conductor")
        db.commit()


def _process(db: Session, message: InboundMessage) -> None:
    wa_id = message.wa_id
    first_contact = db.scalars(select(OutboundMessage.id).where(OutboundMessage.wa_id == wa_id).limit(1)).first() is None
    if first_contact:
        send_message(db, wa_id=wa_id, body=PRIVACY_NOTICE, case_time=message.case_time, kind="privacy_notice")

    driver = db.scalars(select(Driver).where(Driver.phone == wa_id)).first()
    vehicle = _current_vehicle(db, driver) if driver else None
    if driver is None or vehicle is None:
        _handle_unidentified(db, message, driver)
        return

    text = (message.text or "").strip()
    req = _open_request(db, vehicle_id=vehicle.id)
    ai = get_ai_provider()
    extracted = (ai.extract_request(text, {"last_question": req.step if req else None, "plate": vehicle.plate})
                 if text else ExtractedRequest())

    created = False
    if req is None:
        active = _active_authorization(db, vehicle.id)
        if active:
            _, authorization = active
            _say(db, None, wa_id, case_time=message.case_time, kind="duplicate",
                 body=(f"{first_name(driver)}, ya tienes una autorización vigente para {vehicle.plate}: "
                       f"{fmt_cop(authorization.amount)} de {authorization.product}, referencia {authorization.reference}. "
                       "No se autoriza dos veces la misma solicitud."))
            return
        if extracted.intent == "status" and message.type == "text":
            _say(db, None, wa_id, case_time=message.case_time, kind="status",
                 body=(f"Hola, {first_name(driver)}. No tienes solicitudes abiertas para {vehicle.plate}. "
                       "Si necesitas combustible, escríbeme \"Necesito tanquear\"."))
            return
        req = _create_request(db, message, driver, vehicle)
        created = True
    else:
        message.request_id = req.id
        waiting_technician = req.status == "in_review" or (req.status == "ready" and req.step != "not_needed")
        if waiting_technician:
            _reply_status(db, req, duplicate=extracted.intent != "status")
            return
        if extracted.intent == "status" and message.type == "text" and extracted.confirmation is None:
            _reply_status(db, req)
            return

    _apply(db, req, message, extracted, created)
    _advance(db, req)


# --------------------------------------------------------------------------- steps

def _create_request(db: Session, message: InboundMessage, driver: Driver, vehicle: Vehicle) -> FuelRequest:
    created_at = now()
    req = FuelRequest(wa_id=message.wa_id, driver_id=driver.id, vehicle_id=vehicle.id, status="received",
                      data={}, missing=[], occurred_at=message.case_time, created_at=created_at,
                      sla_due_at=sla_due(created_at))
    db.add(req)
    db.flush()
    req.driver, req.vehicle = driver, vehicle
    message.request_id = req.id
    set_status(db, req, "received", "Primer mensaje del conductor por WhatsApp")
    emit(db, "RequestReceived", "request", req.id,
         {"request_id": req.id, "wa_id": req.wa_id, "vehicle": vehicle.code, "occurred_at": to_local(req.occurred_at).isoformat()})
    audit(db, ASSISTANT, "request.received", "request", req.id, request_id=req.id,
          summary=f"Solicitud de {driver.name} para {vehicle.code} ({vehicle.plate}) recibida por WhatsApp")
    set_status(db, req, "identified", f"Conductor {driver.name} y vehículo {vehicle.plate} identificados por el número")
    _say(db, req, req.wa_id, kind="greeting",
         body=(f"Hola, {first_name(driver)}. Soy el asistente de combustible de Esivans. "
               f"Te tengo con el vehículo de placa {vehicle.plate}."))
    return req


def _handle_unidentified(db: Session, message: InboundMessage, driver: Driver | None) -> None:
    """Unknown number (or driver without a current assignment): a person takes the case."""
    wa_id = message.wa_id
    existing = _open_request(db, wa_id=wa_id)
    if existing:
        message.request_id = existing.id
        _say(db, existing, wa_id, kind="status",
             body="Tu caso ya está con el técnico de Control y Monitoreo. Te responde por este mismo chat.")
        return
    reason = "driver" if driver is None else "vehicle"
    created_at = now()
    req = FuelRequest(wa_id=wa_id, driver_id=driver.id if driver else None, vehicle_id=None, status="received",
                      data={"first_message": message.text}, missing=[reason], occurred_at=message.case_time,
                      created_at=created_at, sla_due_at=sla_due(created_at))
    db.add(req)
    db.flush()
    message.request_id = req.id
    set_status(db, req, "received", "Primer mensaje por WhatsApp")
    emit(db, "RequestReceived", "request", req.id, {"request_id": req.id, "wa_id": wa_id, "vehicle": None})
    note = ("Número no registrado: pasa al técnico para identificar al conductor" if driver is None
            else "Conductor sin vehículo asignado: pasa al técnico")
    audit(db, ASSISTANT, "request.received", "request", req.id, request_id=req.id, summary=note)
    evaluate(db, req)
    req.ready_at = now()
    set_status(db, req, "in_review", note)
    _say(db, req, wa_id, kind="handoff",
         body=("No encuentro este número entre los conductores registrados. Ya pasé tu caso al técnico de Control y "
               "Monitoreo, que te escribe por este mismo chat. Ten a la mano la placa del vehículo."
               if driver is None else
               f"{first_name(driver)}, no veo un vehículo asignado a tu nombre hoy. Ya pasé tu caso al técnico de "
               "Control y Monitoreo, que te escribe por este mismo chat."))


def _apply(db: Session, req: FuelRequest, message: InboundMessage, extracted: ExtractedRequest, created: bool) -> None:
    data = dict(req.data or {})
    text = (message.text or "").strip()
    vehicle_unit = req.vehicle.unit if req.vehicle else None
    if extracted.quantity and (extracted.quantity_unit in (None, vehicle_unit)):
        req.requested_quantity = extracted.quantity

    if message.type == "image":
        _take_photo(db, req, message, data)
    elif not created:
        step = req.step
        if step == "service":
            if data.get("proposed_service_id") and extracted.confirmation is True:
                req.chosen_service_id = data["proposed_service_id"]
                data["service_resolved"] = True
            elif text:
                req.service_note = text
                data["service_resolved"] = True
        elif step == "confirm" and req.evidence is not None:
            evidence = req.evidence
            if extracted.confirmation is True:
                evidence.odometer_km = evidence.proposed_odometer or evidence.odometer_read
                evidence.confirmed = True
            elif extracted.odometer_km:
                _manual_km(db, req, extracted.odometer_km)
            elif extracted.confirmation is False:
                data["ask_manual"] = True
        elif step == "manual_km":
            if extracted.odometer_km:
                _manual_km(db, req, extracted.odometer_km)
                data["ask_manual"] = False
        elif step == "not_needed":
            wants_review = any(word in text.lower() for word in ("revis", "técnico", "tecnico", "igual"))
            data["not_needed_answer"] = "review" if wants_review else "accept"
    req.data = data
    db.flush()


def _last_reading(db: Session, req: FuelRequest) -> tuple[int | None, float | None]:
    book = ledger.refuel_context(db, req.vehicle, req.occurred_at, None, ledger.tank_of(req.vehicle.product))
    return book["last_valid_odometer"], book["hours_since_last_reading"]


def _validate_odometer(db: Session, req: FuelRequest, value: int | None) -> dict:
    rules = current_rules(db)
    last_valid, hours = _last_reading(db, req)
    result = odo.check_reading(value, last_valid, hours,
                               rollback_km=rules["R03"].params["rollback_km"],
                               max_km_per_day=rules["R03"].params["max_km_per_day"],
                               typo_tolerance_km=rules["R02"].params["typo_tolerance_km"])
    result["last_valid"] = last_valid
    return result


def _take_photo(db: Session, req: FuelRequest, message: InboundMessage, data: dict) -> None:
    downloaded = media.download(message.media_id or "")
    evidence = req.evidence or Evidence(request_id=req.id)
    if downloaded is None:
        data["photo_unreadable"] = True
        return
    reading = get_ai_provider().read_dashboard(downloaded["content"], downloaded["mime_type"])
    evidence.media_id = message.media_id
    evidence.photo_path = downloaded["path"]
    evidence.photo_hash = downloaded["sha256"]
    evidence.confidence = reading.confidence.model_dump()
    evidence.fuel_level = reading.fuel_level if reading.confidence.fuel_level >= MIN_CONFIDENCE else None
    readable = reading.odometer_km is not None and reading.confidence.odometer_km >= MIN_CONFIDENCE
    evidence.odometer_read = reading.odometer_km if readable else None
    evidence.odometer_km = None
    evidence.odometer_source = "photo"
    evidence.confirmed = False
    evidence.error_type = None
    evidence.proposed_odometer = None
    if readable:
        check = _validate_odometer(db, req, reading.odometer_km)
        if check["status"] == "atypical":
            evidence.error_type = check["error_type"]
            evidence.proposed_odometer = check["proposed"]
    data["photo_unreadable"] = not readable
    data["ask_manual"] = not readable
    data["last_valid_odometer"] = _last_reading(db, req)[0]
    db.add(evidence)
    req.evidence = evidence
    db.flush()
    audit(db, ASSISTANT, "evidence.read", "evidence", evidence.id, request_id=req.id,
          summary=(f"Foto del tablero leída: {fmt_int(evidence.odometer_read)} km, nivel {level_text(evidence.fuel_level)}"
                   if readable else "Foto del tablero ilegible: se pide el kilometraje al conductor"),
          after={"odometer_read": evidence.odometer_read, "fuel_level": evidence.fuel_level,
                 "confidence": evidence.confidence, "error_type": evidence.error_type,
                 "proposed_odometer": evidence.proposed_odometer, "photo_hash": evidence.photo_hash})


def _manual_km(db: Session, req: FuelRequest, value: int) -> None:
    evidence = req.evidence or Evidence(request_id=req.id, confidence={})
    check = _validate_odometer(db, req, value)
    evidence.odometer_km = value
    evidence.odometer_source = "driver"
    evidence.confirmed = True
    if evidence.odometer_read is None:
        evidence.odometer_read = value
    evidence.error_type = check["error_type"] if check["status"] == "atypical" else None
    evidence.proposed_odometer = check["proposed"] if check["status"] == "atypical" else None
    db.add(evidence)
    req.evidence = evidence
    db.flush()
    audit(db, ASSISTANT, "evidence.typed", "evidence", evidence.id, request_id=req.id,
          summary=f"El conductor digitó el kilometraje: {fmt_int(value)} km")


def _advance(db: Session, req: FuelRequest) -> None:
    """Asks for the first missing item or, when the request is complete, sends it to the engine."""
    data = dict(req.data or {})
    name = first_name(req.driver)
    evidence = req.evidence

    if req.step == "not_needed" and data.get("not_needed_answer"):
        if data["not_needed_answer"] == "review":
            req.step = None
            requests_service.mark_review_requested(req)
            set_status(db, req, "in_review", "El cálculo dice que no necesita tanquear; el conductor pidió revisión")
            _say(db, req, req.wa_id, kind="in_review",
                 body=f"Listo, {name}. Le pasé tu solicitud al técnico de Control y Monitoreo para que la revise.")
        else:
            req.step = None
            req.close_reason = "not_needed"
            set_status(db, req, "cancelled", "No necesita tanquear ahora; el conductor quedó informado")
            audit(db, ASSISTANT, "request.closed", "request", req.id, request_id=req.id,
                  summary="Solicitud cerrada sin tanqueo: a cargar es 0 o menos")
            _say(db, req, req.wa_id, kind="closed",
                 body=f"De acuerdo, {name}. Cuando bajes de ½ tanque me escribes y lo gestionamos de una.")
        return

    if req.status == "identified":
        set_status(db, req, "awaiting_evidence", "El asistente pide lo que falta")

    if not data.get("service_resolved"):
        services = ledger.services_context(db, req.vehicle, req.occurred_at)
        nxt = services["next_service"]
        if nxt:
            data["proposed_service_id"] = nxt["id"]
            others = services["pending_count"] - 1
            pending_word = "pendiente" if others == 1 else "pendientes"
            extra = f" y tienes {others} más {pending_word} hoy" if others > 0 else ""
            body = (f"Tu próximo servicio en EOM es a las {clock12(parse_iso(nxt['start']))} ({nxt['origin']} → {nxt['destination']})"
                    f"{extra}. ¿El tanqueo es para esa ruta?")
            replies = ["Sí, es para esa ruta", "Es otro recorrido"]
        else:
            body = ("No veo servicios tuyos pendientes en EOM. ¿Para qué recorrido necesitas el combustible? "
                    "Tu respuesta le llega al técnico.")
            replies = ["Traslado no programado", "Apoyo a otra zona", "No tengo servicio asignado"]
        req.step, req.data = "service", data
        _say(db, req, req.wa_id, body, kind="ask_service", quick_replies=replies)
        return

    has_reading = evidence is not None and (evidence.odometer_read is not None or evidence.odometer_km is not None)
    if not has_reading:
        if data.get("photo_unreadable"):
            req.step = "manual_km"
            body = ("No logro leer bien el kilometraje en la foto. Escríbeme el número que marca el odómetro "
                    "(el técnico verá la foto).")
        else:
            req.step = "photo"
            required = " En tu vehículo la foto es obligatoria." if "V04" in (req.vehicle.flags or []) else ""
            body = ("Perfecto. Envíame una foto del tablero donde se vean el kilometraje y el nivel de combustible."
                    + required)
        req.data = data
        _say(db, req, req.wa_id, body, kind="ask_photo")
        return

    if not evidence.confirmed:
        if data.get("ask_manual"):
            req.step, req.data = "manual_km", data
            _say(db, req, req.wa_id, "Escríbeme el kilometraje que marca el odómetro, solo el número.", kind="ask_km")
            return
        req.step, req.data = "confirm", data
        # Without a readable level the message says so instead of "nivel de sin lectura".
        level = (f"nivel de {level_text(evidence.fuel_level)}" if evidence.fuel_level is not None
                 else "no pude leer el nivel de combustible")
        if evidence.error_type in odo.TYPO_TYPES and evidence.proposed_odometer:
            fix = odo.describe_fix(evidence.odometer_read, evidence.proposed_odometer, evidence.error_type)
            body = (f"En la foto leí {fmt_int(evidence.odometer_read)} km y {level}. Tu último registro es de "
                    f"{fmt_int(data.get('last_valid_odometer'))} km, así que parece un error de un dígito ({fix}). "
                    f"¿El kilometraje correcto es {fmt_int(evidence.proposed_odometer)} km?")
            replies = [f"Sí, es {fmt_int(evidence.proposed_odometer)}", "No, corregir"]
            kind = "confirm_correction"
        else:
            body = f"Leí en la foto {fmt_int(evidence.odometer_read)} km y {level}. ¿Es correcto?"
            replies = ["Sí, es correcto", "No, corregir"]
            kind = "confirm_reading"
        _say(db, req, req.wa_id, body, kind=kind, quick_replies=replies)
        return

    _finalize(db, req, data)


def _finalize(db: Session, req: FuelRequest, data: dict) -> None:
    name = first_name(req.driver)
    req.data = data
    req.missing = []
    req.ready_at = now()
    set_status(db, req, "ready", "Solicitud completa: servicio, foto y kilometraje confirmado")
    evaluation = evaluate(db, req)
    calculation = evaluation.calculation or {}
    if calculation.get("needs_refuel") is False:
        unit = fmt_unit(req.vehicle.unit)
        available = next((s["display"] for s in calculation.get("steps", []) if s["key"] == "available"), "")
        req.step = "not_needed"
        _say(db, req, req.wa_id, kind="not_needed", quick_replies=["Entendido, gracias", "Que lo revise el técnico"],
             body=(f"{name}, con el nivel que leí ({available}) te alcanza para tu ruta pendiente y la reserva de ½ tanque: "
                   f"por ahora no necesitas tanquear ({fmt_num(calculation.get('quantity'), 1)} {unit} a cargar). "
                   "¿Lo dejamos así?"))
        return
    req.step = None
    set_status(db, req, "in_review", "En la cola del técnico de Control y Monitoreo")
    _say(db, req, req.wa_id, kind="in_review",
         body=(f"Gracias, {name}. Tu solicitud está en revisión con el técnico de Control y Monitoreo. "
               "Te aviso por aquí apenas haya respuesta."))


def _reply_status(db: Session, req: FuelRequest, duplicate: bool = False) -> None:
    name = first_name(req.driver)
    prefix = f"{name}, ya tienes una solicitud abierta para {req.vehicle.plate}. " if duplicate else f"{name}, "
    if req.status in ("in_review", "ready"):
        if req.decision is not None and req.decision.action != "reject":
            body = prefix + ("tu solicitud ya fue aprobada y el técnico está habilitando el medio de pago. "
                             "En un momento te llega el valor y la referencia.")
        else:
            body = prefix + "está en revisión con el técnico de Control y Monitoreo. Te aviso apenas haya respuesta."
    else:
        labels = {"service": "que me confirmes el servicio o el motivo", "photo": "la foto del tablero",
                  "confirmation": "que confirmes el kilometraje"}
        pending = [labels[m] for m in missing_items(req) if m in labels]
        body = prefix + ("para continuar me falta " + " y ".join(pending) + "." if pending
                         else "estoy terminando de armar tu solicitud.")
    if duplicate:  # the prefix ends with a period: the next sentence starts in upper case
        body = prefix + body[len(prefix):len(prefix) + 1].upper() + body[len(prefix) + 1:]
    _say(db, req, req.wa_id, body, kind="duplicate" if duplicate else "status")


# --------------------------------------------------------------------------- SLA

def escalate_overdue(db: Session) -> int:
    """SLA of 10 minutes: an incomplete request goes to the technician with whatever it has."""
    overdue = db.scalars(select(FuelRequest).where(
        FuelRequest.status.in_(("received", "identified", "awaiting_evidence")), FuelRequest.sla_due_at < now())).all()
    for req in overdue:
        if req.vehicle is None:
            continue
        req.missing = missing_items(req)
        evidence = req.evidence
        if evidence is not None and evidence.odometer_km is None:
            evidence.odometer_km = evidence.proposed_odometer or evidence.odometer_read
        req.step = None
        req.ready_at = now()
        evaluate(db, req)
        labels = ", ".join(requests_service.MISSING_LABELS[m].lower() for m in req.missing) or "nada"
        set_status(db, req, "in_review", f"Pasó al técnico por SLA de {requests_service.SLA_MINUTES} min. Faltó: {labels}")
        audit(db, SYSTEM, "request.escalated", "request", req.id, request_id=req.id,
              summary=f"SLA de {requests_service.SLA_MINUTES} minutos cumplido: pasa al técnico. Faltó: {labels}",
              after={"missing": req.missing})
        _say(db, req, req.wa_id, kind="handoff",
             body=(f"{first_name(req.driver)}, pasé tu solicitud al técnico de Control y Monitoreo con lo que hay "
                   "para no hacerte esperar. Te aviso apenas haya respuesta."))
    if overdue:
        db.commit()
    return len(overdue)
