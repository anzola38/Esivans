"""Conversation with the driver and request states: every demo case message by message, duplicates,
status queries, "nothing to load", unreadable photos, V04, the privacy notice and the 10-minute SLA."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, text

from app.integrations.ai.base import DashboardReading
from app.integrations.ai.mock import MockProvider
from app.integrations.whatsapp import build_webhook_payload
from app.models import FuelRequest
from app.timeutil import at, now, today

from .helpers import (TECH, WA, audit_items, authorize, conversation, decide, detail, kinds, outbound, outbox, plain,
                      play, post_webhook, queue, send)

GREEN, VEH015, VEH199, NO_FUEL, UNREGISTERED = (WA[k] for k in ("GREEN", "VEH015", "VEH199", "NO_FUEL", "UNREGISTERED"))
PRIVACY = ("Aviso de privacidad: usamos tu número, tu asignación y las fotos que envíes solo para gestionar el "
           "suministro de combustible (Ley 1581 de 2012).")
IN_REVIEW = ("Gracias, {name}. Tu solicitud está en revisión con el técnico de Control y Monitoreo. "
             "Te aviso por aquí apenas haya respuesta.")
UNREADABLE = ("No logro leer bien el kilometraje en la foto. Escríbeme el número que marca el odómetro "
              "(el técnico verá la foto).")


def _statuses(chat: dict) -> list[str]:
    return [h["status"] for h in chat["request"]["status_history"]]


def _requests(db) -> int:
    return db.scalar(select(func.count()).select_from(FuelRequest))


# ----------------------------------------------------------------------------- green case, state by state

def test_green_first_message_identifies_driver_and_vehicle_and_proposes_the_service(fresh):
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    chat = conversation(fresh, GREEN)
    assert chat["driver"] == {"id": 1, "name": "Carlos Andrés Pérez", "phone": GREEN}
    assert kinds(chat) == ["privacy_notice", "greeting", "ask_service"]
    texts = [plain(m["text"]) for m in outbound(chat)]
    assert texts[0] == PRIVACY
    assert texts[1] == "Hola, Carlos. Soy el asistente de combustible de Esivans. Te tengo con el vehículo de placa ZZA901."
    assert texts[2] == ("Tu próximo servicio en EOM es a las 10:30 a. m. (Montería → Planeta Rica) y tienes 5 más "
                        "pendientes hoy. ¿El tanqueo es para esa ruta?")
    assert chat["quick_replies"] == ["Sí, es para esa ruta", "Es otro recorrido"]
    request = chat["request"]
    assert request["status"] == "awaiting_evidence" and request["step"] == "service" and request["is_open"] is True
    assert _statuses(chat) == ["received", "identified", "awaiting_evidence"]
    assert request["vehicle"]["code"] == "VEH901" and request["vehicle"]["plate"] == "ZZA901"
    assert request["traffic_light"] is None and request["points"] is None and request["suggested_amount"] is None
    assert request["one_click_allowed"] is False
    # Nothing has been evaluated yet.
    pending = detail(fresh, request["id"])
    assert pending["evaluation"] is None and pending["calculation"] is None and pending["context"] is None
    assert pending["evidence"] is None and pending["decision"] is None and pending["authorization"] is None


def test_green_second_message_confirms_the_service_and_asks_for_the_photo(fresh):
    chat = play(fresh, "GREEN", steps=2)
    assert kinds(chat)[-1] == "ask_photo"
    assert chat["messages"][-1]["text"] == ("Perfecto. Envíame una foto del tablero donde se vean el kilometraje y el "
                                            "nivel de combustible.")
    assert chat["quick_replies"] == []
    assert chat["request"]["status"] == "awaiting_evidence" and chat["request"]["step"] == "photo"
    service = detail(fresh, chat["request"]["id"])["service"]
    assert service["note"] is None
    assert service["chosen"]["start"] == at(today(), "10:30").isoformat()
    assert (service["chosen"]["origin"], service["chosen"]["destination"]) == ("Montería", "Planeta Rica")
    assert service["chosen"]["status"] == "pending" and service["chosen"]["km"] == 18.0


def test_green_photo_is_read_and_the_driver_only_confirms(fresh):
    chat = play(fresh, "GREEN", steps=3)
    assert kinds(chat)[-1] == "confirm_reading"
    assert plain(chat["messages"][-1]["text"]) == "Leí en la foto 48.352 km y nivel de ¼ de tanque (25 %). ¿Es correcto?"
    assert chat["quick_replies"] == ["Sí, es correcto", "No, corregir"]
    assert chat["request"]["status"] == "awaiting_evidence" and chat["request"]["step"] == "confirm"
    evidence = detail(fresh, chat["request"]["id"])["evidence"]
    assert evidence["odometer_read"] == 48352 and evidence["odometer_km"] is None
    assert evidence["confirmed_by_driver"] is False and evidence["error_type"] is None


def test_green_confirmation_sends_the_request_to_the_technician(fresh):
    chat = play(fresh, "GREEN")
    assert kinds(chat) == ["privacy_notice", "greeting", "ask_service", "ask_photo", "confirm_reading", "in_review"]
    assert chat["messages"][-1]["text"] == IN_REVIEW.format(name="Carlos")
    assert chat["quick_replies"] == [] and chat["assistant_typing"] is False
    assert _statuses(chat) == ["received", "identified", "awaiting_evidence", "ready", "in_review"]
    request = detail(fresh, chat["request"]["id"])
    assert request["status"] == "in_review" and request["status_label"] == "En revisión" and request["step"] is None
    assert request["traffic_light"] == "green" and request["traffic_light_label"] == "Verde"
    assert request["points"] == 0 and request["rule_codes"] == [] and request["has_inconsistency"] is False
    assert request["one_click_allowed"] is True and request["suggested_amount"] == 90000
    assert request["missing"] == [] and request["evaluation"]["reasons"] == []
    assert request["evaluation"]["rules_version"] == "v1"
    assert request["evidence"]["odometer_km"] == 48352 and request["evidence"]["confirmed_by_driver"] is True
    assert request["evidence"]["odometer_source_label"] == "Foto del tablero"
    assert [h["note"] for h in request["status_history"]] == [
        "Primer mensaje del conductor por WhatsApp",
        "Conductor Carlos Andrés Pérez y vehículo ZZA901 identificados por el número",
        "El asistente pide lo que falta",
        "Solicitud completa: servicio, foto y kilometraje confirmado",
        "En la cola del técnico de Control y Monitoreo"]


def test_green_context_joins_last_refuel_km_and_services(fresh):
    context = detail(fresh, play(fresh, "GREEN")["request"]["id"])["context"]
    last = context["last_refuel"]
    assert last["odometer"] == 48210 and last["amount"] == 80000 and last["provider"] == "terpel"
    assert last["timestamp"] == at(today() - timedelta(days=1), "17:30").isoformat() and last["hours_ago"] == 16.2
    assert context["km_since_last_refuel"] == 142 and context["km_since_last_same_fuel"] == 142
    assert context["last_valid_odometer"] == 48210 and context["loads_24h"] == 2
    assert context["typical_load"] == 5.0 and context["largest_loads"] == 5.62
    services = context["services"]
    assert services["vehicle_in_eom"] is True and services["today_count"] == 9 and services["pending_count"] == 6
    assert services["next_service"]["start"] == at(today(), "10:30").isoformat()
    assert context["efficiency"]["value"] == 40.5 and context["efficiency"]["status"] == "normal"
    assert context["vehicle_flags"] == [] and context["providers"] == ["terpel"]


def test_messages_show_the_time_of_the_case_not_the_real_time(fresh):
    chat = play(fresh, "GREEN")
    assert {m["timestamp"][:16] for m in chat["messages"]} == {at(today(), "09:40").isoformat()[:16]}
    assert chat["request"]["occurred_at"] == at(today(), "09:40").isoformat()
    real = datetime.fromisoformat(chat["messages"][0]["created_at"])
    assert abs((now() - real).total_seconds()) < 60


def test_another_route_is_kept_as_the_justification_for_the_technician(fresh):
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="Es otro recorrido")
    chat = conversation(fresh, GREEN)
    assert kinds(chat)[-1] == "ask_photo" and chat["request"]["step"] == "photo"
    service = detail(fresh, chat["request"]["id"])["service"]
    assert service == {"chosen": None, "note": "Es otro recorrido"}


def test_driver_can_type_another_km_at_the_confirmation(fresh):
    play(fresh, "GREEN", steps=3)
    send(fresh, case="GREEN", text="No, es 48.360")
    request = detail(fresh, conversation(fresh, GREEN)["request"]["id"])
    assert request["status"] == "in_review"
    evidence = request["evidence"]
    assert evidence["odometer_read"] == 48352 and evidence["odometer_km"] == 48360
    assert evidence["odometer_source"] == "driver" and evidence["odometer_source_label"] == "Digitado por el conductor"
    assert request["context"]["km_since_last_refuel"] == 150
    assert any(a["action"] == "evidence.typed" and a["summary"] == "El conductor digitó el kilometraje: 48.360 km"
               for a in request["audit"])


# ----------------------------------------------------------------------------- VEH015

def test_veh015_proposes_34086_and_the_driver_confirms(fresh):
    chat = play(fresh, "VEH015", steps=3)
    proposal = chat["messages"][-1]
    assert proposal["kind"] == "confirm_correction"
    assert plain(proposal["text"]) == (
        "En la foto leí 24.086 km y nivel de ¼ de tanque (25 %). Tu último registro es de 33.948 km, así que parece "
        "un error de un dígito (el 3 quedó como 2). ¿El kilometraje correcto es 34.086 km?")
    assert chat["quick_replies"] == ["Sí, es 34.086", "No, corregir"]
    pending = detail(fresh, chat["request"]["id"])["evidence"]
    assert pending["odometer_read"] == 24086 and pending["proposed_odometer"] == 34086
    assert pending["error_type"] == "changed_digit" and pending["error_label"] == "dígito cambiado"
    assert pending["odometer_km"] is None and pending["confirmed_by_driver"] is False

    send(fresh, case="VEH015", text="Sí, es 34.086")
    request = detail(fresh, conversation(fresh, VEH015)["request"]["id"])
    assert request["status"] == "in_review"
    assert request["traffic_light"] == "yellow" and request["points"] == 1 and request["rule_codes"] == ["R02"]
    assert request["one_click_allowed"] is False and request["suggested_amount"] == 50000
    evidence = request["evidence"]
    assert evidence["odometer_read"] == 24086 and evidence["odometer_km"] == 34086
    assert evidence["odometer_source"] == "photo" and evidence["confirmed_by_driver"] is True
    reason = request["evaluation"]["reasons"][0]
    assert reason["code"] == "R02" and reason["points"] == 1 and reason["treatment"] == "automatic"
    assert reason["explanation"] == ("leyó 24.086 km (dígito cambiado); última lectura válida: 33.948 km; "
                                     "valor corregido: 34.086 km")
    assert request["context"]["last_valid_odometer"] == 33948 and request["context"]["km_since_last_refuel"] == 138


def test_veh015_has_no_eom_services_so_the_assistant_asks_for_the_justification(fresh):
    chat = play(fresh, "VEH015", steps=1)
    question = chat["messages"][-1]
    assert question["kind"] == "ask_service"
    assert question["text"] == ("No veo servicios tuyos pendientes en EOM. ¿Para qué recorrido necesitas el combustible? "
                                "Tu respuesta le llega al técnico.")
    assert chat["quick_replies"] == ["Traslado no programado", "Apoyo a otra zona", "No tengo servicio asignado"]
    send(fresh, case="VEH015", text="Traslado no programado")
    request = detail(fresh, conversation(fresh, VEH015)["request"]["id"])
    assert request["service"] == {"chosen": None, "note": "Traslado no programado"}


def test_veh015_no_corregir_lets_the_driver_type_the_km(fresh):
    play(fresh, "VEH015", steps=3)
    send(fresh, case="VEH015", text="No, corregir")
    chat = conversation(fresh, VEH015)
    assert chat["messages"][-1]["kind"] == "ask_km"
    assert chat["messages"][-1]["text"] == "Escríbeme el kilometraje que marca el odómetro, solo el número."
    assert chat["request"]["status"] == "awaiting_evidence" and chat["request"]["step"] == "manual_km"

    send(fresh, case="VEH015", text="34086")
    chat = conversation(fresh, VEH015)
    assert chat["messages"][-1]["kind"] == "in_review"
    request = detail(fresh, chat["request"]["id"])
    assert request["status"] == "in_review" and request["suggested_amount"] == 50000
    evidence = request["evidence"]
    assert evidence["odometer_km"] == 34086 and evidence["odometer_read"] == 24086      # the photo reading is kept
    assert evidence["odometer_source"] == "driver" and evidence["confirmed_by_driver"] is True
    assert evidence["error_type"] is None and evidence["proposed_odometer"] is None
    assert evidence["photo_url"] == "/api/media/media-veh015"                            # the technician still sees it
    assert request["context"]["km_since_last_refuel"] == 138
    assert request["calculation"]["cross_check"]["km_since_last"] == 138
    actions = [a["action"] for a in request["audit"]]
    assert actions == ["request.received", "evidence.read", "evidence.typed", "request.evaluated"]


def test_veh015_typed_km_that_no_digit_explains_goes_to_the_technician_in_red(fresh):
    play(fresh, "VEH015", steps=3)
    send(fresh, case="VEH015", text="No, corregir")
    send(fresh, case="VEH015", text="El km es 51777")
    request = detail(fresh, conversation(fresh, VEH015)["request"]["id"])
    assert request["status"] == "in_review" and request["evidence"]["odometer_km"] == 51777
    assert request["evidence"]["error_type"] == "inconsistent" and request["evidence"]["error_label"] == "inconsistente"
    assert request["rule_codes"] == ["R03", "R04"] and request["points"] == 4 and request["traffic_light"] == "red"
    assert request["has_inconsistency"] is True and request["one_click_allowed"] is False
    reasons = {r["code"]: r["explanation"] for r in request["evaluation"]["reasons"]}
    # The reason quotes what the driver reported, not the earlier reading of the photo.
    assert reasons["R03"] == "reportó 51.777 km; última lectura válida: 33.948 km"
    assert reasons["R04"] == "17.829 km en 0,9 días: posible tanqueo no registrado en estos proveedores"
    assert reasons["INC"].startswith("El nivel leído (3,0 gal) es mayor de lo posible: con 17.829 km recorridos")


def test_manual_km_step_keeps_asking_until_there_is_a_number(fresh):
    play(fresh, "VEH015", steps=3)
    send(fresh, case="VEH015", text="No, corregir")
    send(fresh, case="VEH015", text="no me acuerdo")
    chat = conversation(fresh, VEH015)
    assert kinds(chat)[-2:] == ["ask_km", "ask_km"]
    assert chat["request"]["step"] == "manual_km" and chat["request"]["status"] == "awaiting_evidence"


# ----------------------------------------------------------------------------- VEH199

def test_veh199_with_the_quantity_in_the_message_is_red_with_7_points(fresh):
    chat = play(fresh, "VEH199")
    assert kinds(chat) == ["privacy_notice", "greeting", "ask_service", "ask_photo", "confirm_reading", "in_review"]
    assert plain(outbound(chat)[4]["text"]) == "Leí en la foto 195.406 km y nivel de ¼ de tanque (25 %). ¿Es correcto?"
    request = detail(fresh, chat["request"]["id"])
    assert request["occurred_at"] == at(today(), "23:14").isoformat()
    assert request["requested_quantity"] == 6.7
    assert request["traffic_light"] == "red" and request["traffic_light_label"] == "Rojo" and request["points"] == 7
    assert request["rule_codes"] == ["R05", "R08", "R09"] and request["one_click_allowed"] is False
    assert [(r["code"], r["points"], r["explanation"]) for r in request["evaluation"]["reasons"]] == [
        ("R05", 3, "cargó 6,7 m³ de GNV con 22 km desde su carga anterior (típica 9,7 m³)"),
        ("R08", 2, "sin servicios con desplazamiento 24 h antes ni después"),
        ("R09", 2, "tanqueo a las 23:14 sin servicios cercanos")]
    context = request["context"]
    assert context["last_refuel"]["odometer"] == 195384 and context["km_since_last_same_fuel"] == 22
    assert context["typical_load"] == 9.7 and context["largest_loads"] == 11.8
    assert context["services"]["vehicle_in_eom"] is True and context["services"]["services_24h"] == 0
    assert request["service"] == {"chosen": None, "note": "No tengo servicio asignado"}
    assert request["suggested_amount"] == 10000


def test_veh199_without_the_quantity_uses_the_suggested_load_and_r05_does_not_fire(fresh):
    send(fresh, case="VEH199", text="Necesito tanquear")
    send(fresh, case="VEH199", text="No tengo servicio asignado")
    send(fresh, case="VEH199", media_id="media-veh199")
    send(fresh, case="VEH199", text="Sí, es correcto")
    request = detail(fresh, conversation(fresh, VEH199)["request"]["id"])
    assert request["requested_quantity"] is None
    # The suggested 3.5 m3 is below half of its typical 9.7 m3: R05 has nothing to say.
    assert request["calculation"]["quantity"] == 3.5
    assert request["rule_codes"] == ["R08", "R09"] and request["points"] == 4 and request["traffic_light"] == "red"
    r05 = next(c for c in request["evaluation"]["checks"] if c["code"] == "R05")
    assert r05["triggered"] is False and r05["explanation"] == "22 km desde su carga anterior del mismo combustible"
    assert request["suggested_amount"] == 10000


def test_quantity_in_another_unit_is_not_taken_as_the_requested_load(fresh):
    send(fresh, case="VEH199", text="Necesito tanquear 6,7 galones")       # a gas vehicle loads cubic meters
    assert conversation(fresh, VEH199)["request"]["requested_quantity"] is None


# ----------------------------------------------------------------------------- unregistered number

def test_unregistered_number_goes_straight_to_the_technician(fresh):
    chat = play(fresh, "UNREGISTERED")
    assert chat["driver"] is None
    assert kinds(chat) == ["privacy_notice", "handoff"]
    assert chat["messages"][-1]["text"] == (
        "No encuentro este número entre los conductores registrados. Ya pasé tu caso al técnico de Control y "
        "Monitoreo, que te escribe por este mismo chat. Ten a la mano la placa del vehículo.")
    assert _statuses(chat) == ["received", "in_review"]
    request = detail(fresh, chat["request"]["id"])
    assert request["driver"] is None and request["vehicle"] is None and request["wa_id"] == UNREGISTERED
    assert request["missing"] == [{"key": "driver", "label": "Conductor no identificado"}]
    assert request["traffic_light"] == "yellow" and request["points"] == 0 and request["rule_codes"] == []
    assert request["has_inconsistency"] is True and request["one_click_allowed"] is False
    reason = request["evaluation"]["reasons"][0]
    assert reason["code"] == "INC" and reason["name"] == "Número no registrado" and reason["points"] == 0
    assert request["calculation"]["computable"] is False and request["suggested_amount"] is None
    assert request["calculation"]["note"] == "Sin vehículo identificado: el técnico define el valor."
    assert request["status_history"][-1]["note"] == "Número no registrado: pasa al técnico para identificar al conductor"


def test_unregistered_number_writing_again_does_not_open_another_request(fresh, db):
    play(fresh, "UNREGISTERED")
    send(fresh, case="UNREGISTERED", text="¿Hola? Necesito combustible")
    chat = conversation(fresh, UNREGISTERED)
    assert chat["messages"][-1]["kind"] == "status"
    assert chat["messages"][-1]["text"] == "Tu caso ya está con el técnico de Control y Monitoreo. Te responde por este mismo chat."
    assert kinds(chat).count("privacy_notice") == 1 and _requests(db) == 1


def test_driver_without_a_current_assignment_goes_to_the_technician(fresh, db):
    db.execute(text("UPDATE assignment SET valid_to = now() - interval '1 day' "
                    "WHERE driver_id = (SELECT id FROM driver WHERE phone = :phone)"), {"phone": WA["VEH903"]})
    db.commit()
    send(fresh, wa_id=WA["VEH903"], text="Necesito tanquear", time="10:00")
    chat = conversation(fresh, WA["VEH903"])
    assert kinds(chat) == ["privacy_notice", "handoff"]
    assert chat["messages"][-1]["text"] == ("María, no veo un vehículo asignado a tu nombre hoy. Ya pasé tu caso al "
                                            "técnico de Control y Monitoreo, que te escribe por este mismo chat.")
    request = chat["request"]
    assert request["status"] == "in_review" and request["vehicle"] is None
    assert request["driver"]["name"] == "María Fernanda Lozano"
    assert request["missing"] == [{"key": "vehicle", "label": "Vehículo sin asignación vigente"}]


# ----------------------------------------------------------------------------- duplicates

def test_second_request_while_in_review_gets_the_status_and_no_new_request(fresh, db):
    request_id = play(fresh, "GREEN")["request"]["id"]
    send(fresh, case="GREEN", text="Necesito tanquear")
    chat = conversation(fresh, GREEN)
    assert chat["messages"][-1]["kind"] == "duplicate"
    assert chat["messages"][-1]["text"] == ("Carlos, ya tienes una solicitud abierta para ZZA901. Está en revisión con el "
                                            "técnico de Control y Monitoreo. Te aviso apenas haya respuesta.")
    assert chat["request"]["id"] == request_id and _requests(db) == 1
    assert len(queue(fresh, None)["items"]) == 1
    assert [e["event_type"] for e in outbox(fresh)] == ["RequestReceived"]


def test_repeating_the_request_while_the_assistant_waits_for_the_photo_keeps_one_request(fresh, db):
    play(fresh, "GREEN", steps=2)
    send(fresh, case="GREEN", text="Necesito tanquear")
    send(fresh, case="GREEN", text="Hola, necesito tanquear ya")
    chat = conversation(fresh, GREEN)
    assert _requests(db) == 1 and chat["request"]["step"] == "photo"
    assert kinds(chat)[-1] == "ask_photo"
    assert kinds(chat).count("greeting") == 1


def test_second_request_with_a_valid_authorization_is_answered_with_it(fresh, db):
    request_id = play(fresh, "GREEN")["request"]["id"]
    decide(fresh, request_id, action="approve")
    authorize(fresh, request_id, "TER-DUP-0001")
    send(fresh, case="GREEN", text="Necesito tanquear")
    last = conversation(fresh, GREEN)["messages"][-1]
    assert last["kind"] == "duplicate"
    assert last["text"] == ("Carlos, ya tienes una autorización vigente para ZZA901: $90.000 de Gasolina Corriente, "
                            "referencia TER-DUP-0001. No se autoriza dos veces la misma solicitud.")
    assert _requests(db) == 1


def test_only_one_open_request_per_vehicle_across_the_whole_flow(fresh, db):
    play(fresh, "GREEN", steps=1)
    script = [("Sí, es para esa ruta", None), (None, "media-veh901"), ("Sí, es correcto", None)]
    for message, media_id in script:
        send(fresh, case="GREEN", text="Necesito tanquear")        # insists before every step
        send(fresh, case="GREEN", text=message, media_id=media_id)
    open_requests = db.scalar(select(func.count()).select_from(FuelRequest).where(
        FuelRequest.status.in_(("received", "identified", "awaiting_evidence", "ready", "in_review"))))
    assert open_requests == 1 and _requests(db) == 1


def test_after_a_closed_request_the_driver_can_open_a_new_one(fresh, db):
    play(fresh, "NO_FUEL")
    send(fresh, case="NO_FUEL", text="Necesito tanquear")
    chat = conversation(fresh, NO_FUEL)
    assert _requests(db) == 2 and chat["request"]["id"] == 2 and chat["request"]["status"] == "awaiting_evidence"
    assert kinds(chat)[-2:] == ["greeting", "ask_service"]


# ----------------------------------------------------------------------------- status queries

def test_status_query_without_a_request_does_not_open_one(fresh, db):
    send(fresh, case="GREEN", text="¿Cómo va mi solicitud?")
    chat = conversation(fresh, GREEN)
    assert kinds(chat) == ["privacy_notice", "status"]
    assert chat["messages"][-1]["text"] == ('Hola, Carlos. No tienes solicitudes abiertas para ZZA901. '
                                            'Si necesitas combustible, escríbeme "Necesito tanquear".')
    assert chat["request"] is None and _requests(db) == 0


def test_status_query_says_exactly_what_is_missing_at_each_step(fresh):
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="¿Cómo va mi solicitud?")
    assert conversation(fresh, GREEN)["messages"][-1]["text"] == (
        "Carlos, para continuar me falta que me confirmes el servicio o el motivo y la foto del tablero.")
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    send(fresh, case="GREEN", text="¿Cómo va mi solicitud?")
    assert conversation(fresh, GREEN)["messages"][-1]["text"] == "Carlos, para continuar me falta la foto del tablero."
    send(fresh, case="GREEN", media_id="media-veh901")
    send(fresh, case="GREEN", text="¿Cómo va mi solicitud?")
    chat = conversation(fresh, GREEN)
    assert chat["messages"][-1]["text"] == "Carlos, para continuar me falta que confirmes el kilometraje."
    assert chat["messages"][-1]["kind"] == "status"
    assert chat["request"]["step"] == "confirm" and chat["request"]["status"] == "awaiting_evidence"


def test_status_query_while_in_review_and_after_the_decision(fresh):
    request_id = play(fresh, "GREEN")["request"]["id"]
    send(fresh, case="GREEN", text="¿Cómo va mi solicitud?")
    last = conversation(fresh, GREEN)["messages"][-1]
    assert last["kind"] == "status"
    assert last["text"] == "Carlos, está en revisión con el técnico de Control y Monitoreo. Te aviso apenas haya respuesta."

    decide(fresh, request_id, action="approve")
    send(fresh, case="GREEN", text="¿Ya me autorizaron?")        # also understood as a status query
    last = conversation(fresh, GREEN)["messages"][-1]
    assert last["kind"] == "status"
    assert last["text"] == ("Carlos, tu solicitud ya fue aprobada y el técnico está habilitando el medio de pago. "
                            "En un momento te llega el valor y la referencia.")


# ----------------------------------------------------------------------------- to load <= 0

def test_no_fuel_needed_is_explained_and_closed_when_the_driver_accepts(fresh):
    chat = play(fresh, "NO_FUEL", steps=4)
    assert chat["messages"][-1]["kind"] == "not_needed"
    assert chat["quick_replies"] == ["Entendido, gracias", "Que lo revise el técnico"]
    assert chat["request"]["status"] == "ready" and chat["request"]["step"] == "not_needed"
    assert chat["request"]["suggested_amount"] == 0
    assert queue(fresh, "in_review")["items"] == []          # it never reaches the technician's queue

    send(fresh, case="NO_FUEL", text="Entendido, gracias")
    chat = conversation(fresh, NO_FUEL)
    assert chat["messages"][-1]["kind"] == "closed"
    assert chat["messages"][-1]["text"] == "De acuerdo, Luis. Cuando bajes de ½ tanque me escribes y lo gestionamos de una."
    assert _statuses(chat) == ["received", "identified", "awaiting_evidence", "ready", "cancelled"]
    request = detail(fresh, chat["request"]["id"])
    assert request["status"] == "cancelled" and request["status_label"] == "Cerrada sin tanqueo"
    assert request["closed_at"] is not None
    assert chat["request"]["is_open"] is False and request["decision"] is None and request["authorization"] is None
    assert request["status_history"][-1]["note"] == "No necesita tanquear ahora; el conductor quedó informado"
    closing = request["audit"][-1]
    assert closing["action"] == "request.closed" and closing["actor"] == "asistente"
    assert closing["summary"] == "Solicitud cerrada sin tanqueo: a cargar es 0 o menos"
    assert queue(fresh, "closed")["items"][0]["id"] == request["id"]


def test_no_fuel_needed_goes_to_the_technician_if_the_driver_insists(fresh):
    play(fresh, "NO_FUEL", steps=4)
    send(fresh, case="NO_FUEL", text="Que lo revise el técnico")
    chat = conversation(fresh, NO_FUEL)
    assert chat["messages"][-1]["kind"] == "in_review"
    assert chat["messages"][-1]["text"] == "Listo, Luis. Le pasé tu solicitud al técnico de Control y Monitoreo para que la revise."
    request = detail(fresh, chat["request"]["id"])
    assert request["status"] == "in_review" and request["traffic_light"] == "yellow" and request["points"] == 0
    assert request["has_inconsistency"] is True and request["one_click_allowed"] is False
    assert request["evaluation"]["reasons"][0]["name"] == "No necesita tanquear según el cálculo"
    assert request["status_history"][-1]["note"] == "El cálculo dice que no necesita tanquear; el conductor pidió revisión"
    # Nothing to approve: the technician sets the amount with a reason, or rejects.
    assert decide(fresh, request["id"], action="approve", reason="Lo pidió").json()["code"] == "no_suggested_amount"
    adjusted = decide(fresh, request["id"], action="adjust", amount=30000, reason="Ruta extra confirmada por radio")
    assert adjusted.status_code == 200 and adjusted.json()["decision"]["amount"] == 30000


# ----------------------------------------------------------------------------- unreadable photo, low confidence

def _photo_through_webhook(client, media_id: str) -> None:
    payload = build_webhook_payload(wa_id=GREEN, profile_name="Carlos Andrés Pérez", timestamp=now(),
                                    media_id=media_id, mime_type="image/jpeg")
    assert post_webhook(client, payload).json()["received"] == 1


def _low_confidence(monkeypatch, odometer: float, level: float = 0.9) -> None:
    monkeypatch.setattr(MockProvider, "read_dashboard", lambda self, image, mime_type="image/svg+xml": DashboardReading(
        odometer_km=48352, fuel_level=0.25, confidence={"odometer_km": odometer, "fuel_level": level}))


def test_photo_that_cannot_be_downloaded_asks_the_driver_to_type_the_km(fresh):
    play(fresh, "GREEN", steps=2)
    _photo_through_webhook(fresh, "media-no-existe")
    chat = conversation(fresh, GREEN)
    assert chat["messages"][-1]["text"] == UNREADABLE
    assert chat["request"]["step"] == "manual_km" and chat["request"]["status"] == "awaiting_evidence"

    send(fresh, case="GREEN", text="48352")
    request = detail(fresh, conversation(fresh, GREEN)["request"]["id"])
    assert request["status"] == "in_review"
    evidence = request["evidence"]
    assert evidence["odometer_km"] == 48352 and evidence["odometer_source"] == "driver"
    assert evidence["fuel_level"] is None and evidence["photo_url"] is None
    # Without the level there is no amount: the technician defines it, never in one click.
    assert request["calculation"]["computable"] is False and request["suggested_amount"] is None
    assert request["calculation"]["note"] == "No se puede calcular el valor: falta el nivel de combustible. El técnico lo define."
    assert request["one_click_allowed"] is False
    assert decide(fresh, request["id"], action="approve").json()["code"] == "no_suggested_amount"
    adjusted = decide(fresh, request["id"], action="adjust", amount=80000, reason="Nivel confirmado por llamada")
    assert adjusted.status_code == 200 and adjusted.json()["enablement"]["amount"] == 80000


def test_low_confidence_reading_is_not_shown_and_the_driver_types_the_km(fresh, monkeypatch):
    _low_confidence(monkeypatch, odometer=0.59)
    chat = play(fresh, "GREEN", steps=3)
    assert chat["messages"][-1]["text"] == UNREADABLE
    assert "48.352" not in chat["messages"][-1]["text"]
    assert chat["request"]["step"] == "manual_km"
    pending = detail(fresh, chat["request"]["id"])
    assert pending["evidence"]["odometer_read"] is None and pending["evidence"]["odometer_km"] is None
    assert pending["evidence"]["confidence"] == {"odometer_km": 0.59, "fuel_level": 0.9}
    assert pending["evidence"]["photo_url"] == "/api/media/media-veh901"          # the photo is kept for the technician
    assert pending["audit"][-1]["summary"] == "Foto del tablero ilegible: se pide el kilometraje al conductor"

    send(fresh, case="GREEN", text="48352")
    request = detail(fresh, conversation(fresh, GREEN)["request"]["id"])
    assert request["status"] == "in_review" and request["traffic_light"] == "green"
    assert request["evidence"]["odometer_km"] == 48352 and request["evidence"]["odometer_source"] == "driver"
    assert request["evidence"]["fuel_level"] == 0.25 and request["suggested_amount"] == 90000


def test_typed_km_that_does_not_match_the_expected_one_is_decided_by_the_technician(fresh, monkeypatch):
    _low_confidence(monkeypatch, odometer=0.3)
    play(fresh, "GREEN", steps=3)
    send(fresh, case="GREEN", text="58352")                 # 10,142 km in 16 hours: a 5 instead of a 4
    request = detail(fresh, conversation(fresh, GREEN)["request"]["id"])
    assert request["status"] == "in_review" and request["traffic_light"] == "yellow"
    assert request["rule_codes"] == ["R02", "R04"] and request["points"] == 3
    assert request["has_inconsistency"] is True and request["one_click_allowed"] is False
    assert request["evidence"]["error_type"] == "changed_digit" and request["evidence"]["proposed_odometer"] == 48352
    assert request["evidence"]["photo_url"] == "/api/media/media-veh901"
    r02 = request["evaluation"]["reasons"][0]
    assert r02["explanation"] == ("leyó 58.352 km (dígito cambiado); última lectura válida: 48.210 km; "
                                  "valor corregido: 48.352 km")


def test_confidence_of_exactly_60_percent_is_enough_to_show_the_reading(fresh, monkeypatch):
    _low_confidence(monkeypatch, odometer=0.6, level=0.6)
    chat = play(fresh, "GREEN", steps=3)
    assert chat["messages"][-1]["kind"] == "confirm_reading" and chat["request"]["step"] == "confirm"
    assert plain(chat["messages"][-1]["text"]) == "Leí en la foto 48.352 km y nivel de ¼ de tanque (25 %). ¿Es correcto?"


def test_unreadable_fuel_level_leaves_the_amount_to_the_technician(fresh, monkeypatch):
    _low_confidence(monkeypatch, odometer=0.95, level=0.4)
    chat = play(fresh, "GREEN")
    assert outbound(chat)[4]["text"] == "Leí en la foto 48.352 km y no pude leer el nivel de combustible. ¿Es correcto?"
    request = detail(fresh, chat["request"]["id"])
    assert request["evidence"]["fuel_level"] is None and request["calculation"]["computable"] is False
    assert request["suggested_amount"] is None and request["one_click_allowed"] is False


# ----------------------------------------------------------------------------- V04: mandatory photo

def test_vehicle_with_v04_is_told_the_photo_is_mandatory(fresh):
    send(fresh, wa_id=WA["VEH910"], text="Necesito tanquear", time="10:00")
    send(fresh, wa_id=WA["VEH910"], text="Sí, es para esa ruta")
    chat = conversation(fresh, WA["VEH910"])
    assert chat["request"]["vehicle"]["code"] == "VEH910" and chat["request"]["step"] == "photo"
    assert chat["messages"][-1]["text"] == ("Perfecto. Envíame una foto del tablero donde se vean el kilometraje y el "
                                            "nivel de combustible. En tu vehículo la foto es obligatoria.")


def test_vehicle_with_v04_cannot_continue_by_typing_the_km(fresh):
    send(fresh, wa_id=WA["VEH910"], text="Necesito tanquear", time="10:00")
    send(fresh, wa_id=WA["VEH910"], text="Sí, es para esa ruta")
    send(fresh, wa_id=WA["VEH910"], text="80500")
    chat = conversation(fresh, WA["VEH910"])
    assert chat["request"]["step"] == "photo" and chat["request"]["status"] == "awaiting_evidence"
    assert kinds(chat)[-2:] == ["ask_photo", "ask_photo"]
    assert chat["messages"][-1]["text"].endswith("En tu vehículo la foto es obligatoria.")
    assert detail(fresh, chat["request"]["id"])["evidence"] is None


def test_vehicle_without_v04_is_not_told_the_photo_is_mandatory(fresh):
    chat = play(fresh, "GREEN", steps=2)
    assert "obligatoria" not in chat["messages"][-1]["text"]


# ----------------------------------------------------------------------------- privacy notice

def test_privacy_notice_is_the_first_message_and_is_sent_only_once(fresh):
    chat = play(fresh, "NO_FUEL")
    assert outbound(chat)[0]["kind"] == "privacy_notice" and outbound(chat)[0]["text"] == PRIVACY
    assert chat["messages"][1]["kind"] == "privacy_notice"        # right after the driver's first message
    send(fresh, case="NO_FUEL", text="Necesito tanquear")         # a second request of the same driver
    send(fresh, case="NO_FUEL", text="¿Cómo va mi solicitud?")
    chat = conversation(fresh, NO_FUEL)
    assert kinds(chat).count("privacy_notice") == 1 and kinds(chat).count("greeting") == 2


def test_each_driver_gets_their_own_privacy_notice(fresh):
    play(fresh, "GREEN", steps=1)
    play(fresh, "VEH199", steps=1)
    assert kinds(conversation(fresh, GREEN)).count("privacy_notice") == 1
    assert kinds(conversation(fresh, VEH199)).count("privacy_notice") == 1


# ----------------------------------------------------------------------------- SLA of 10 minutes

def test_request_is_not_escalated_before_the_10_minutes(fresh, clock):
    play(fresh, "GREEN", steps=2)
    clock.advance(minutes=9, seconds=45)
    listing = queue(fresh, None)
    assert listing["items"][0]["status"] == "awaiting_evidence" and listing["items"][0]["sla_breached"] is False
    assert 0 < listing["items"][0]["sla_remaining_seconds"] <= 15
    assert listing["counts"] == {"total": 1, "in_review": 0, "green": 0, "yellow": 0, "red": 0, "sla_breached": 0}
    assert kinds(conversation(fresh, GREEN))[-1] == "ask_photo"


def test_sla_expiry_sends_the_request_to_the_technician_marking_the_missing_photo(fresh, clock):
    request_id = play(fresh, "GREEN", steps=2)["request"]["id"]
    clock.advance(minutes=10, seconds=5)
    listing = queue(fresh, "in_review")          # the queue checks the SLA when it is read
    assert listing["counts"] == {"total": 1, "in_review": 1, "green": 0, "yellow": 1, "red": 0, "sla_breached": 1}
    item = listing["items"][0]
    assert item["id"] == request_id and item["status"] == "in_review"
    assert item["missing"] == [{"key": "photo", "label": "Foto del tablero"}]
    assert item["sla_breached"] is True and -15 <= item["sla_remaining_seconds"] < 0

    request = detail(fresh, request_id)
    assert request["traffic_light"] == "yellow" and request["has_inconsistency"] is True
    assert request["rule_codes"] == ["R01"] and request["points"] == 1 and request["one_click_allowed"] is False
    incomplete = next(r for r in request["evaluation"]["reasons"] if r["code"] == "INC")
    assert incomplete["name"] == "Solicitud incompleta"
    assert incomplete["explanation"] == "Pasó al técnico al cumplirse los 10 minutos sin: foto del tablero."
    assert request["status_history"][-1]["status"] == "in_review"
    assert request["status_history"][-1]["note"] == "Pasó al técnico por SLA de 10 min. Faltó: foto del tablero"
    escalation = next(a for a in request["audit"] if a["action"] == "request.escalated")
    assert escalation["actor"] == "sistema" and escalation["after"] == {"missing": ["photo"]}
    assert escalation["summary"] == "SLA de 10 minutos cumplido: pasa al técnico. Faltó: foto del tablero"
    assert request["suggested_amount"] is None and request["step"] is None

    chat = conversation(fresh, GREEN)
    assert chat["messages"][-1]["kind"] == "handoff"
    assert chat["messages"][-1]["text"] == ("Carlos, pasé tu solicitud al técnico de Control y Monitoreo con lo que hay "
                                            "para no hacerte esperar. Te aviso apenas haya respuesta.")


def test_sla_expiry_right_after_the_first_message_marks_service_and_photo(fresh, clock):
    request_id = play(fresh, "GREEN", steps=1)["request"]["id"]
    clock.advance(minutes=11)
    chat = conversation(fresh, GREEN)             # reading the conversation also checks the SLA
    assert chat["request"]["status"] == "in_review"
    assert [m["key"] for m in chat["request"]["missing"]] == ["service", "photo"]
    request = detail(fresh, request_id)
    assert request["status_history"][-1]["note"] == (
        "Pasó al técnico por SLA de 10 min. Faltó: servicio o justificación, foto del tablero")
    incomplete = next(r for r in request["evaluation"]["reasons"] if r["code"] == "INC")
    assert incomplete["explanation"] == ("Pasó al técnico al cumplirse los 10 minutos sin: servicio o justificación, "
                                         "foto del tablero.")


def test_sla_expiry_with_the_photo_unconfirmed_uses_the_reading_and_marks_the_confirmation(fresh, clock):
    request_id = play(fresh, "GREEN", steps=3)["request"]["id"]
    clock.advance(minutes=11)
    assert queue(fresh, "in_review")["items"][0]["missing"] == [
        {"key": "confirmation", "label": "Confirmación del kilometraje"}]
    request = detail(fresh, request_id)
    assert request["evidence"]["odometer_km"] == 48352 and request["evidence"]["confirmed_by_driver"] is False
    assert request["suggested_amount"] == 90000 and request["rule_codes"] == [] and request["points"] == 0
    assert request["traffic_light"] == "yellow" and request["one_click_allowed"] is False
    # Yellow: approving needs the reason, and then the flow continues as usual.
    assert decide(fresh, request_id, action="approve").json()["code"] == "reason_required"
    approved = decide(fresh, request_id, action="approve", reason="Kilometraje verificado en la foto")
    assert approved.status_code == 200 and approved.json()["decision"]["amount"] == 90000
    assert authorize(fresh, request_id, "TER-SLA-0001").json()["status"] == "authorized"


def test_escalation_happens_once_and_a_late_answer_does_not_reopen_the_request(fresh, clock, db):
    request_id = play(fresh, "GREEN", steps=2)["request"]["id"]
    clock.advance(minutes=11)
    queue(fresh, None)
    queue(fresh, None)
    conversation(fresh, GREEN)
    assert [a["action"] for a in audit_items(fresh, f"request_id={request_id}")].count("request.escalated") == 1
    send(fresh, case="GREEN", media_id="media-veh901")           # the photo arrives late
    chat = conversation(fresh, GREEN)
    assert kinds(chat).count("handoff") == 1 and chat["messages"][-1]["kind"] == "duplicate"
    assert chat["request"]["status"] == "in_review" and _requests(db) == 1


def test_complete_request_waiting_more_than_10_minutes_is_marked_as_breached_but_stays_green(fresh, clock):
    request_id = play(fresh, "GREEN")["request"]["id"]
    clock.advance(minutes=12)
    listing = queue(fresh, "in_review")
    item = listing["items"][0]
    assert item["sla_breached"] is True and -125 <= item["sla_remaining_seconds"] <= -115
    assert 715 <= item["wait_seconds"] <= 725
    assert item["traffic_light"] == "green" and item["missing"] == [] and item["one_click_allowed"] is True
    assert listing["counts"]["sla_breached"] == 1 and listing["counts"]["green"] == 1
    assert kinds(conversation(fresh, GREEN))[-1] == "in_review"          # nobody is escalated twice
    decide(fresh, request_id, action="approve")
    decided = queue(fresh, "in_review")["items"][0]
    assert decided["sla_breached"] is False and decided["sla_remaining_seconds"] is None
