"""AI adapter: the deterministic interpreter of the driver's messages, the reading of the sample
photos, the fallback when the remote provider fails, and the es-CO formats used in every text."""
from __future__ import annotations

import hashlib
from datetime import datetime

import pytest

from app.config import get_settings
from app.integrations.ai import SafeProvider, get_ai_provider
from app.integrations.ai.base import MIN_CONFIDENCE, DashboardReading, ExtractedRequest
from app.integrations.ai.mock import MockProvider
from app.requests.conversation import level_text
from app.seed.photos import ensure_photos
from app.timeutil import BOGOTA, clock12, ddmmyyyy, fmt_cop, fmt_int, fmt_num, fmt_pct, fmt_unit, hhmm, iso, parse_iso

from .helpers import WA, conversation, plain, send

MOCK = MockProvider()


def _read(text: str) -> ExtractedRequest:
    return MOCK.extract_request(text, {})


# ----------------------------------------------------------------------------- text interpreter

@pytest.mark.parametrize("text, intent", [
    ("Hola, necesito tanquear", "refuel"), ("Buenas, necesito combustible", "refuel"),
    ("Necesito tanquear 6,7 m3 de gas", "refuel"), ("me quedé sin gasolina", "refuel"),
    ("¿Cómo va mi solicitud?", "status"), ("¿Ya me autorizaron?", "status"), ("ya me autorizó el técnico?", "status"),
    ("alguna novedad", "status"), ("Hola", "greeting"), ("Buenos días", "greeting"), ("48352", "unknown"),
])
def test_intent_of_the_message(text, intent):
    assert _read(text).intent == intent


@pytest.mark.parametrize("text, expected", [
    ("Sí, es correcto", True), ("Si", True), ("Sí, es para esa ruta", True), ("Sí, es 34.086", True),
    ("Entendido, gracias", True), ("Correcto", True), ("No, corregir", False), ("No", False),
    ("Está mal", False), ("Es otro recorrido", False), ("Traslado no programado", None),
    ("No tengo servicio asignado", False), ("Necesito tanquear", None), ("48352", None),
])
def test_yes_or_no_to_the_last_question(text, expected):
    assert _read(text).confirmation is expected


@pytest.mark.parametrize("text, quantity, unit", [
    ("Necesito tanquear 6,7 m3 de gas", 6.7, "m3"), ("necesito 6.7 m³", 6.7, "m3"), ("5 galones por favor", 5.0, "gal"),
    ("Necesito 10 gal", 10.0, "gal"), ("quiero 8 metros cubicos", 8.0, "m3"), ("Necesito tanquear", None, None),
])
def test_quantity_and_unit_requested(text, quantity, unit):
    result = _read(text)
    assert (result.quantity, result.quantity_unit) == (quantity, unit)


@pytest.mark.parametrize("text, km", [
    ("34086", 34086), ("Sí, es 34.086", 34086), ("El km es 51777", 51777), ("marca 195 406", 195406),
    ("No, es 48.360", 48360), ("Sí, es correcto", None), ("123", None),
    ("Necesito tanquear 6,7 m3 de gas", None),          # the quantity is not an odometer
])
def test_odometer_typed_by_the_driver(text, km):
    assert _read(text).odometer_km == km


def test_plate_and_chosen_service_are_extracted():
    assert _read("es la van de placa zza-901").plate == "ZZA901"
    assert _read("Sí, es para esa ruta").chosen_service == "proposed"
    assert _read("Es otro recorrido").chosen_service == "other"
    assert _read("Hola").chosen_service is None


def test_empty_message_gives_an_empty_extraction():
    assert _read("") == ExtractedRequest()
    assert ExtractedRequest().intent == "unknown" and ExtractedRequest().confirmation is None


# ----------------------------------------------------------------------------- photo reading

@pytest.mark.parametrize("name, odometer, level, confidence", [
    ("veh901", 48352, 0.25, (0.97, 0.92)), ("veh015", 24086, 0.25, (0.78, 0.9)),
    ("veh199", 195406, 0.25, (0.96, 0.88)), ("veh902", 61512, 0.875, (0.97, 0.93)),
])
def test_each_sample_photo_has_its_reading(fresh, name, odometer, level, confidence):
    image = fresh.get(f"/api/media/media-{name}").content
    reading = MOCK.read_dashboard(image)
    assert reading.odometer_km == odometer and reading.fuel_level == level
    assert (reading.confidence.odometer_km, reading.confidence.fuel_level) == confidence
    assert min(confidence) >= MIN_CONFIDENCE == 0.6


def test_unknown_photo_has_no_reading_and_zero_confidence():
    reading = MOCK.read_dashboard(b"<svg>otra imagen</svg>")
    assert reading == DashboardReading()
    assert reading.odometer_km is None and reading.fuel_level is None
    assert reading.confidence.odometer_km == 0.0 and reading.confidence.fuel_level == 0.0


def test_sample_photos_are_generated_identically_every_time(fresh):
    before = {name: hashlib.sha256(fresh.get(f"/api/media/media-{name}").content).hexdigest()
              for name in ("veh901", "veh015", "veh199", "veh902")}
    assert ensure_photos() == []                 # nothing is rewritten when the files already exist
    after = {name: hashlib.sha256(fresh.get(f"/api/media/media-{name}").content).hexdigest() for name in before}
    assert after == before


def test_reading_is_validated_against_the_schema():
    with pytest.raises(ValueError):
        DashboardReading(odometer_km=-5)
    with pytest.raises(ValueError):
        DashboardReading(fuel_level=1.4)
    with pytest.raises(ValueError):
        DashboardReading(confidence={"odometer_km": 2})


# ----------------------------------------------------------------------------- provider selection and fallback

class _Broken:
    name = "gemini"

    def extract_request(self, text, context):
        raise RuntimeError("sin conexión")

    def read_dashboard(self, image, mime_type="image/svg+xml"):
        raise RuntimeError("sin conexión")


def test_default_provider_is_the_local_one():
    assert get_settings().ai_provider == "mock"
    assert isinstance(get_ai_provider(), MockProvider) and get_ai_provider().name == "mock"


def test_text_falls_back_to_the_local_interpreter_when_the_remote_provider_fails():
    safe = SafeProvider(_Broken(), MockProvider())
    result = safe.extract_request("Necesito tanquear 6,7 m3 de gas", {})
    assert safe.name == "gemini" and result.intent == "refuel" and result.quantity == 6.7


def test_photo_reading_failure_returns_no_reading_so_the_driver_is_asked(fresh, monkeypatch):
    safe = SafeProvider(_Broken(), MockProvider())
    assert safe.read_dashboard(b"cualquier foto") == DashboardReading()
    # Through the conversation: the assistant asks for the km and the request keeps moving.
    monkeypatch.setattr("app.requests.conversation.get_ai_provider", lambda: safe)
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    send(fresh, case="GREEN", media_id="media-veh901")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["step"] == "manual_km" and chat["messages"][-1]["text"].startswith("No logro leer bien")
    send(fresh, case="GREEN", text="48352")
    assert conversation(fresh, WA["GREEN"])["request"]["status"] == "in_review"


def test_error_while_processing_a_message_is_told_to_the_driver_and_audited(fresh, monkeypatch):
    send(fresh, case="GREEN", text="Hola, necesito tanquear")

    def explode(self, text, context):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(MockProvider, "extract_request", explode)
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["assistant_typing"] is False                       # the message is not left pending forever
    assert chat["messages"][-1]["kind"] == "error"
    assert chat["messages"][-1]["text"] == ("Tuvimos un problema procesando tu mensaje. El técnico de turno ya fue "
                                            "avisado y te atiende por este medio.")
    assert chat["request"]["step"] == "service"                    # nothing was half applied
    failed = fresh.get("/api/audit?action=message.failed").json()["items"]
    assert len(failed) == 1 and failed[0]["actor"] == "sistema" and failed[0]["entity"] == "inbound_message"
    monkeypatch.undo()
    send(fresh, case="GREEN", text="Sí, es para esa ruta")         # the driver repeats and the flow continues
    assert conversation(fresh, WA["GREEN"])["request"]["step"] == "photo"


# ----------------------------------------------------------------------------- es-CO formats

def test_money_and_number_formats():
    assert fmt_cop(27783) == "$27.783" and fmt_cop(90000) == "$90.000" and fmt_cop(0) == "$0"
    assert fmt_cop(4128960) == "$4.128.960" and fmt_cop(-4501) == "-$4.501" and fmt_cop(None) == "s/d"
    assert fmt_cop(90666.67) == "$90.667"
    assert fmt_int(33948) == "33.948" and fmt_int(195406) == "195.406" and fmt_int(783) == "783"
    assert fmt_num(6.7, 1) == "6,7" and fmt_num(5.647, 3) == "5,647" and fmt_num(1234.5) == "1.234,5"
    assert fmt_num(None) == "s/d"
    assert plain(fmt_pct(0.61)) == "61 %" and plain(fmt_pct(0.0711, 1)) == "7,1 %" and fmt_pct(None) == "s/d"
    assert fmt_pct(0.25) == "25 %"                 # non-breaking space: the figure never splits from its sign
    assert fmt_unit("m3") == "m³" and fmt_unit("gal") == "gal"


@pytest.mark.parametrize("hour, minute, text", [(0, 5, "12:05 a. m."), (9, 40, "9:40 a. m."), (11, 40, "11:40 a. m."),
                                                 (12, 0, "12:00 p. m."), (13, 14, "1:14 p. m."), (23, 14, "11:14 p. m.")])
def test_single_time_convention_in_messages(hour, minute, text):
    moment = datetime(2026, 10, 11, hour, minute, tzinfo=BOGOTA)
    assert plain(clock12(moment)) == text
    assert hhmm(moment) == f"{hour:02d}:{minute:02d}"


def test_dates_are_rendered_in_bogota_time():
    moment = parse_iso("2026-10-12T04:14:00Z")                      # 23:14 of the previous day in Bogotá
    assert iso(moment) == "2026-10-11T23:14:00-05:00"
    assert ddmmyyyy(moment) == "11/10/2026" and hhmm(moment) == "23:14"
    assert iso(datetime(2026, 10, 11, 9, 40)) == "2026-10-11T09:40:00-05:00"    # naive values are Bogotá time
    assert iso(None) is None


@pytest.mark.parametrize("level, text", [(0.0, "vacío (0 %)"), (0.125, "⅛ de tanque (12 %)"), (0.25, "¼ de tanque (25 %)"),
                                         (0.5, "½ de tanque (50 %)"), (0.875, "⅞ de tanque (88 %)"),
                                         (1.0, "lleno (100 %)"), (None, "sin lectura")])
def test_fuel_level_is_described_in_eighths(level, text):
    assert plain(level_text(level)) == text
