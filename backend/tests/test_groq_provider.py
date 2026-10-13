"""Groq provider: requests and normalisation (with httpx.MockTransport, never the real service),
fallback when it fails, which provider is recorded for each interpretation and reading, and the
hot switch of the demo. One optional live test runs only with RUN_LIVE_AI=1 and a key."""
from __future__ import annotations

import base64
import dataclasses
import json
import os

import httpx
import pytest

from app import config
from app.integrations import ai, media
from app.integrations.ai import SafeProvider, TextOnlyProvider, source_label
from app.integrations.ai.base import MIN_CONFIDENCE
from app.integrations.ai.groq import (DASHBOARD_PROMPT, FUEL_LEVEL_CONFIDENCE_CAP, GroqError, GroqProvider,
                                      STEP_QUESTIONS, normalize_extraction, normalize_reading)
from app.integrations.ai.mock import MockProvider
from app.seed.photos import MEDIA_DIR

from .conftest import LIVE_GROQ_KEY
from .helpers import COORD, FINANCE, SUPPORT, TECH, WA, conversation, detail, send

KEY = "clave-de-prueba-NO-REAL-0123456789"
TEXT_MODEL, VISION_MODEL = "openai/gpt-oss-120b", "qwen/qwen3.8-27b"
SVG = {name: (MEDIA_DIR / f"{name}.svg").read_bytes() for name in ("veh901", "veh015", "veh199", "veh902")}


def _completion(content: object, status: int = 200) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return httpx.Response(status, json={"choices": [{"message": {"role": "assistant", "content": text},
                                                     "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def _rate_limited(message: str, **headers: str) -> httpx.Response:
    return httpx.Response(429, headers=headers, json={"error": {"message": message, "type": "tokens",
                                                                "code": "rate_limit_exceeded"}})


class Recorder:
    """Transport that answers with the queued responses (the last one repeats) and keeps the requests."""

    def __init__(self, *responses) -> None:
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses[min(len(self.requests), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response(request) if callable(response) else response

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def _provider(*responses, **options) -> tuple[GroqProvider, Recorder, list[float]]:
    recorder, sleeps = Recorder(*responses), []
    provider = GroqProvider(KEY, TEXT_MODEL, VISION_MODEL, transport=httpx.MockTransport(recorder),
                            sleep=sleeps.append, **options)
    return provider, recorder, sleeps


# ----------------------------------------------------------------------------- text: request and result

def test_text_request_follows_the_chat_completions_contract():
    provider, recorder, _ = _provider(_completion({"intent": "refuel", "confirmation": None, "chosen_service": None,
                                                   "quantity": 6.7, "quantity_unit": "m3", "odometer_km": None,
                                                   "plate": None}))
    result = provider.extract_request("Necesito tanquear 6,7 m3 de gas", {"last_question": None})
    assert (result.intent, result.quantity, result.quantity_unit) == ("refuel", 6.7, "m3")
    assert result.confirmation is None and result.odometer_km is None and result.plate is None

    request, body = recorder.requests[0], recorder.bodies[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions" and request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["user-agent"].startswith("esivans-combustible/")
    assert body["model"] == TEXT_MODEL and body["temperature"] == 0 and body["max_tokens"] <= 400
    assert body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "Necesito tanquear 6,7 m3 de gas" in body["messages"][1]["content"]
    assert "es-CO" in body["messages"][0]["content"] and "null" in body["messages"][0]["content"]


def test_only_the_message_and_a_generic_last_question_are_sent():
    provider, recorder, _ = _provider(_completion({"intent": "unknown", "confirmation": True}))
    provider.extract_request("Sí, es para esa ruta",
                             {"last_question": "service", "plate": "ZZA901", "driver": "Carlos Andrés Pérez",
                              "wa_id": "573005550901"})
    sent = json.dumps(recorder.bodies[0], ensure_ascii=False)
    assert STEP_QUESTIONS["service"] in sent and "Sí, es para esa ruta" in sent
    for private in ("ZZA901", "Carlos", "573005550901"):
        assert private not in sent


@pytest.mark.parametrize("raw, message, expected", [
    # Wrong types and es-CO formats that the model may return.
    ({"intent": "REFUEL", "quantity": "6,7", "quantity_unit": "metros cúbicos", "confirmation": "null"},
     "necesito cargar 6,7 m3", {"intent": "refuel", "quantity": 6.7, "quantity_unit": "m3", "confirmation": None}),
    ({"intent": "refuel", "quantity": "10", "quantity_unit": "Galones"}, "Necesito 10 galones",
     {"quantity": 10.0, "quantity_unit": "gal"}),
    ({"confirmation": "sí", "chosen_service": "PROPOSED"}, "Sí, es para esa ruta",
     {"confirmation": True, "chosen_service": "proposed", "intent": "unknown"}),
    ({"confirmation": "no", "chosen_service": "otra"}, "no, es otro", {"confirmation": False, "chosen_service": None}),
    ({"confirmation": "tal vez"}, "tal vez", {"confirmation": None}),
    ({"intent": "saludo"}, "Hola", {"intent": "unknown"}),
    ({"plate": "zza-901"}, "es la van de placa zza-901", {"plate": "ZZA901"}),
    ({"plate": "la van"}, "la van", {"plate": None}),
    # "195.406 km" answered as the decimal 195.406: it is the odometer written in the message.
    ({"odometer_km": 195.406}, "está mal, marca 195.406 km", {"odometer_km": 195406}),
    ({"odometer_km": "34.086"}, "Sí, es 34.086", {"odometer_km": 34086}),
    ({"odometer_km": "48 360 km"}, "marca 48 360", {"odometer_km": 48360}),
    ({"odometer_km": 51777.0}, "El km es 51777", {"odometer_km": 51777}),
    # Nothing is invented: an odometer that is not in the message is dropped.
    ({"odometer_km": 48352}, "Sí, es correcto", {"odometer_km": None}),
    ({"odometer_km": -5}, "menos 5", {"odometer_km": None}),
    # A quantity only counts with its unit (a typed odometer is never a quantity).
    ({"quantity": 34.086, "quantity_unit": None}, "34.086", {"quantity": None, "quantity_unit": None}),
    ({"quantity": 0, "quantity_unit": "gal"}, "0 galones", {"quantity": None, "quantity_unit": None}),
])
def test_extraction_is_normalised_before_validating(raw, message, expected):
    normalised = normalize_extraction(raw, message)
    assert {key: normalised[key] for key in expected} == expected
    provider, _, _ = _provider(_completion(raw))
    result = provider.extract_request(message, {}).model_dump()
    assert {key: result[key] for key in expected} == expected


# ----------------------------------------------------------------------------- failures of the service

@pytest.mark.parametrize("content", ["no es JSON", "[1, 2, 3]", '"solo texto"'])
def test_content_that_is_not_a_json_object_is_a_failure(content):
    provider, _, _ = _provider(_completion(content))
    with pytest.raises(GroqError) as error:
        provider.extract_request("Hola", {})
    assert error.value.code == "invalid_response"


def test_json_inside_a_code_fence_is_accepted():
    provider, _, _ = _provider(_completion('```json\n{"intent": "greeting"}\n```'))
    assert provider.extract_request("Hola", {}).intent == "greeting"


@pytest.mark.parametrize("response", [
    _completion(""), _completion("   "),
    httpx.Response(200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]}),
])
def test_empty_answer_is_a_failure(response):
    provider, _, _ = _provider(response)
    with pytest.raises(GroqError) as error:
        provider.extract_request("Hola", {})
    assert error.value.code == "empty_response"


def test_answer_without_choices_is_a_failure():
    provider, _, _ = _provider(httpx.Response(200, json={"choices": []}))
    with pytest.raises(GroqError) as error:
        provider.extract_request("Hola", {})
    assert error.value.code == "invalid_response"


def test_short_rate_limit_waits_what_the_service_says_and_retries_once():
    provider, recorder, sleeps = _provider(
        _rate_limited("Rate limit reached on tokens per minute (TPM). Please try again in 1.2s."),
        _completion({"intent": "greeting"}))
    assert provider.extract_request("Hola", {}).intent == "greeting"
    assert len(recorder.requests) == 2 and sleeps == [pytest.approx(1.45)]


def test_retry_after_header_is_respected():
    provider, recorder, sleeps = _provider(_rate_limited("Rate limit reached", **{"retry-after": "2"}),
                                           _completion({"intent": "greeting"}))
    provider.extract_request("Hola", {})
    assert len(recorder.requests) == 2 and sleeps == [pytest.approx(2.25)]


def test_rate_limit_that_persists_fails_after_one_retry():
    provider, recorder, sleeps = _provider(_rate_limited("Please try again in 900ms."))
    with pytest.raises(GroqError) as error:
        provider.extract_request("Hola", {})
    assert error.value.code == "rate_limited" and len(recorder.requests) == 2 and len(sleeps) == 1


@pytest.mark.parametrize("message, code", [
    ("Rate limit reached on tokens per minute (TPM): Limit 8000. Please try again in 31.5s.", "rate_limited"),
    ("Rate limit reached on tokens per day (TPD): Limit 200000, Used 197776. Please try again in 2m20.4s.",
     "daily_limit"),
    ("Rate limit reached", "rate_limited"),
])
def test_long_rate_limit_fails_at_once_without_waiting(message, code):
    provider, recorder, sleeps = _provider(_rate_limited(message))
    with pytest.raises(GroqError) as error:
        provider.extract_request("Hola", {})
    assert error.value.code == code and len(recorder.requests) == 1 and sleeps == []


@pytest.mark.parametrize("failure, code", [
    (httpx.ReadTimeout("lento"), "timeout"), (httpx.ConnectTimeout("lento"), "timeout"),
    (httpx.ConnectError("sin red"), "network"),
])
def test_timeout_and_network_errors_fail_without_retrying(failure, code):
    provider, recorder, sleeps = _provider(failure)
    with pytest.raises(GroqError) as error:
        provider.extract_request("Hola", {})
    assert error.value.code == code and len(recorder.requests) == 1 and sleeps == []


@pytest.mark.parametrize("status", [400, 401, 500, 503])
def test_http_error_is_a_failure_and_never_carries_the_key(status):
    provider, recorder, _ = _provider(httpx.Response(status, json={"error": {"message": f"Invalid API Key {KEY}"}}))
    with pytest.raises(GroqError) as error:
        provider.extract_request("Hola", {})
    assert error.value.code == "http_error" and f"HTTP {status}" in str(error.value)
    assert KEY not in str(error.value) and KEY not in repr(error.value) and len(recorder.requests) == 1


def test_provider_needs_a_key():
    with pytest.raises(ValueError):
        GroqProvider("")


# ----------------------------------------------------------------------------- photo

def test_sample_svg_is_sent_as_its_versioned_png():
    provider, recorder, _ = _provider(_completion({
        "odometer_digits": "048352", "needle": "sobre la marca de 1/4", "fuel_percent": 26,
        "confidence": {"odometer_km": 0.98, "fuel_level": 0.9}}))
    reading = provider.read_dashboard(SVG["veh901"], "image/svg+xml")
    assert (reading.odometer_km, reading.fuel_level) == (48352, 0.25)
    # The model's own confidence in the level is capped: it was often wrong while saying 0.9 or more.
    assert (reading.confidence.odometer_km, reading.confidence.fuel_level) == (0.98, FUEL_LEVEL_CONFIDENCE_CAP)
    assert MIN_CONFIDENCE <= FUEL_LEVEL_CONFIDENCE_CAP == 0.7

    body = recorder.bodies[0]
    assert body["model"] == VISION_MODEL and body["temperature"] == 0 and body["max_tokens"] <= 200
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": DASHBOARD_PROMPT}
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    png = base64.b64decode(url.split(",", 1)[1])
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and png == (MEDIA_DIR / "raster" / "veh901.png").read_bytes()


def test_every_sample_photo_has_its_png():
    index = json.loads((MEDIA_DIR / "raster" / "index.json").read_text(encoding="utf-8"))
    assert len(index) == 4
    for name, svg in SVG.items():
        png, mime = media.raster_for(svg)
        assert mime == "image/png" and png == (MEDIA_DIR / "raster" / f"{name}.png").read_bytes()


def test_svg_without_png_is_a_controlled_failure_and_nothing_is_sent():
    provider, recorder, _ = _provider(_completion({"odometer_digits": "1"}))
    with pytest.raises(GroqError) as error:
        provider.read_dashboard(SVG["veh901"].replace(b"048352", b"048353") + b"<!-- cambiado -->", "image/svg+xml")
    assert error.value.code == "no_raster" and recorder.requests == []
    with pytest.raises(GroqError) as error:
        provider.read_dashboard(b"GIF89a", "image/gif")
    assert error.value.code == "unsupported_image" and recorder.requests == []


def test_png_or_jpeg_photo_is_sent_as_it_arrives():
    provider, recorder, _ = _provider(_completion({"odometer_digits": "61512", "fuel_percent": 88,
                                                   "confidence": {"odometer_km": 0.9, "fuel_level": 0.8}}))
    reading = provider.read_dashboard(b"\xff\xd8\xff\xe0foto", "image/jpeg")
    assert (reading.odometer_km, reading.fuel_level) == (61512, 0.875)
    url = recorder.bodies[0]["messages"][0]["content"][1]["image_url"]["url"]
    assert url == "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0foto").decode()


@pytest.mark.parametrize("raw, expected", [
    # The level is quantised to eighths; the odometer is an integer without the leading zero.
    ({"odometer_digits": "048352", "fuel_percent": 25, "confidence": {"odometer_km": 1, "fuel_level": 0.95}},
     (48352, 0.25, 1.0, 0.7)),
    ({"odometer_digits": "195406", "fuel_percent": 87, "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (195406, 0.875, 0.9, 0.7)),
    ({"odometer_digits": "61.512", "fuel_percent": "62", "confidence": {"odometer_km": "0,9", "fuel_level": "80"}},
     (61512, 0.625, 0.9, 0.7)),
    ({"odometer_digits": 48352, "fuel_percent": 0, "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (48352, 0.0, 0.9, 0.7)),
    # Tolerated variants of the answer: a mark of the gauge or a fraction instead of the percentage.
    ({"odometer_km": 48352, "fuel_mark": "1/4", "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (48352, 0.25, 0.9, 0.7)),
    ({"odometer_km": 48352, "fuel_level": 0.27, "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (48352, 0.25, 0.9, 0.7)),
    ({"odometer_km": 48352, "fuel_mark": "F", "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (48352, 1.0, 0.9, 0.7)),
    # A digit the model could not see: no odometer and no confidence, so the driver is asked.
    ({"odometer_digits": "0?4086", "fuel_percent": 25, "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (None, 0.25, 0.0, 0.7)),
    # What is missing or out of range is not a reading.
    ({"odometer_digits": None, "fuel_percent": None, "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (None, None, 0.0, 0.0)),
    ({"odometer_digits": "048352", "fuel_percent": 140, "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (48352, None, 0.9, 0.0)),
    ({"odometer_digits": "99999999999", "fuel_percent": 50, "confidence": {"odometer_km": 0.9, "fuel_level": 0.9}},
     (None, 0.5, 0.0, 0.7)),
    ({"odometer_digits": "048352", "fuel_percent": 50}, (48352, 0.5, 0.0, 0.0)),      # no confidence: not trusted
    ({"odometer_digits": "048352", "fuel_percent": 50, "confidence": {"odometer_km": 0.5, "fuel_level": 0.4}},
     (48352, 0.5, 0.5, 0.4)),                                                         # the model doubts: kept low
    ({}, (None, None, 0.0, 0.0)),
])
def test_reading_is_normalised_validated_and_quantised_to_eighths(raw, expected):
    reading = normalize_reading(raw)
    assert (reading["odometer_km"], reading["fuel_level"], reading["confidence"]["odometer_km"],
            reading["confidence"]["fuel_level"]) == expected
    provider, _, _ = _provider(_completion(raw))
    result = provider.read_dashboard(b"\x89PNG", "image/png")
    assert (result.odometer_km, result.fuel_level) == expected[:2]


# ----------------------------------------------------------------------------- fallback and provenance

def _safe(*responses) -> tuple[SafeProvider, Recorder]:
    provider, recorder, _ = _provider(*responses)
    return SafeProvider(provider, MockProvider()), recorder


def _answer_like_the_model(request: httpx.Request) -> httpx.Response:
    """Plays the remote model for the green case: interprets the text or reads the photo."""
    body = json.loads(request.content)
    if body["model"] == VISION_MODEL:
        return _completion({"odometer_digits": "048352", "needle": "sobre la marca de 1/4", "fuel_percent": 25,
                            "confidence": {"odometer_km": 0.97, "fuel_level": 0.92}})
    text = body["messages"][1]["content"]
    if "necesito tanquear" in text:
        return _completion({"intent": "refuel"})
    return _completion({"intent": "unknown", "confirmation": True})


def test_sources_say_which_provider_and_model_answered():
    safe, _ = _safe(_completion({"intent": "greeting"}))
    result, source = ai.interpret(safe, "Hola", {})
    assert result.intent == "greeting"
    assert (source["kind"], source["provider"], source["model"], source["status"]) == ("text", "groq", TEXT_MODEL, "ok")
    assert source_label(source) == "Groq · gpt-oss-120b" and isinstance(source["elapsed_ms"], int)

    result, source = ai.interpret(MockProvider(), "Hola", {})
    assert (source["provider"], source["model"], source["status"]) == ("mock", None, "ok")
    assert source_label(source) == "simulada (intérprete local)"
    _, source = ai.read_photo(MockProvider(), SVG["veh901"], "image/svg+xml")
    assert source_label(source) == "simulada (lectura de ejemplo)" and source_label(None) is None


@pytest.mark.parametrize("failure, reason, label", [
    (httpx.ReadTimeout("lento"), "timeout", "intérprete local (respaldo: Groq, tiempo de espera agotado)"),
    (httpx.Response(500, json={"error": {"message": "boom"}}), "http_error",
     "intérprete local (respaldo: Groq, error del servicio)"),
    (_rate_limited("tokens per day (TPD). Please try again in 2m20s."), "daily_limit",
     "intérprete local (respaldo: Groq, límite diario de la cuenta)"),
    (_completion("no es JSON"), "invalid_response", "intérprete local (respaldo: Groq, respuesta no válida)"),
])
def test_text_falls_back_to_the_local_interpreter_and_says_so(failure, reason, label):
    safe, _ = _safe(failure)
    result, source = ai.interpret(safe, "Necesito tanquear 6,7 m3 de gas", {})
    assert result.intent == "refuel" and result.quantity == 6.7            # the local interpreter answered
    assert (source["provider"], source["model"], source["status"], source["reason"]) == ("mock", None, "fallback", reason)
    assert source["intended"] == {"provider": "groq", "model": TEXT_MODEL} and source_label(source) == label


def test_photo_failure_gives_no_reading_and_says_so():
    safe, _ = _safe(_rate_limited("tokens per minute (TPM). Please try again in 40s."))
    reading, source = ai.read_photo(safe, SVG["veh901"], "image/svg+xml")
    assert reading.odometer_km is None and reading.fuel_level is None and reading.confidence.odometer_km == 0.0
    assert (source["provider"], source["status"], source["reason"]) == ("groq", "failed", "rate_limited")
    assert source_label(source) == "Groq no leyó la foto (límite por minuto): el conductor escribe el dato"


def test_green_case_with_groq_records_the_provider_of_every_step(fresh, monkeypatch):
    safe, recorder = _safe(_answer_like_the_model)
    monkeypatch.setattr("app.requests.conversation.get_ai_provider", lambda: safe)
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    send(fresh, case="GREEN", media_id="media-veh901")
    send(fresh, case="GREEN", text="Sí, es correcto")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["status"] == "in_review" and chat["request"]["suggested_amount"] == 90000

    inbound = [m for m in chat["messages"] if m["direction"] == "inbound"]
    assert [m["ai"]["label"] for m in inbound] == ["Groq · gpt-oss-120b", "Groq · gpt-oss-120b", "Groq · qwen3.8-27b",
                                                   "Groq · gpt-oss-120b"]
    assert [m["ai"]["kind"] for m in inbound] == ["text", "text", "vision", "text"]
    assert all(m["ai"] is None for m in chat["messages"] if m["direction"] == "outbound")

    body = detail(fresh, chat["request"]["id"])
    evidence = body["evidence"]
    assert evidence["ai_source_label"] == "Groq · qwen3.8-27b"
    assert (evidence["ai_source"]["provider"], evidence["ai_source"]["model"]) == ("groq", VISION_MODEL)
    assert (evidence["odometer_km"], evidence["fuel_level"]) == (48352, 0.25)
    read = next(a for a in body["audit"] if a["action"] == "evidence.read")
    assert read["after"]["ai"]["label"] == "Groq · qwen3.8-27b" and read["after"]["ai"]["status"] == "ok"

    # Nothing personal left the backend: only the messages, generic questions and the image.
    sent = "".join(request.content.decode() for request in recorder.requests)
    for private in ("Carlos", "ZZA901", WA["GREEN"]):
        assert private not in sent
    assert len(recorder.requests) == 4


def test_mock_mode_is_recorded_as_simulated(fresh):
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    send(fresh, case="GREEN", media_id="media-veh901")
    chat = conversation(fresh, WA["GREEN"])
    inbound = [m for m in chat["messages"] if m["direction"] == "inbound"]
    assert [m["ai"]["label"] for m in inbound] == ["simulada (intérprete local)", "simulada (intérprete local)",
                                                   "simulada (lectura de ejemplo)"]
    evidence = detail(fresh, chat["request"]["id"])["evidence"]
    assert evidence["ai_source_label"] == "simulada (lectura de ejemplo)" and evidence["ai_source"]["provider"] == "mock"


def test_text_failure_does_not_stop_the_conversation_and_is_recorded(fresh, monkeypatch):
    safe, recorder = _safe(httpx.ConnectError("sin red"))
    monkeypatch.setattr("app.requests.conversation.get_ai_provider", lambda: safe)
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["step"] == "photo" and chat["messages"][-1]["kind"] == "ask_photo"
    labels = [m["ai"]["label"] for m in chat["messages"] if m["direction"] == "inbound"]
    assert labels == ["intérprete local (respaldo: Groq, sin conexión)"] * 2
    assert [m["ai"]["provider"] for m in chat["messages"] if m["direction"] == "inbound"] == ["mock", "mock"]
    assert len(recorder.requests) == 2


def test_photo_failure_asks_the_driver_and_the_request_still_reaches_the_technician(fresh, monkeypatch):
    def answer(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == VISION_MODEL:
            return _rate_limited("tokens per day (TPD): Limit 200000. Please try again in 18m2s.")
        return _answer_like_the_model(request)

    safe, _ = _safe(answer)
    monkeypatch.setattr("app.requests.conversation.get_ai_provider", lambda: safe)
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    send(fresh, case="GREEN", media_id="media-veh901")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["step"] == "manual_km" and chat["messages"][-1]["text"].startswith("No logro leer bien")
    failed = "Groq no leyó la foto (límite diario de la cuenta): el conductor escribe el dato"
    assert chat["messages"][-2]["ai"] == {"kind": "vision", "provider": "groq", "model": VISION_MODEL,
                                          "status": "failed", "label": failed}

    body = detail(fresh, chat["request"]["id"])
    assert body["evidence"]["ai_source_label"] == failed and body["evidence"]["odometer_read"] is None
    read = next(a for a in body["audit"] if a["action"] == "evidence.read")
    assert read["summary"] == failed and read["after"]["ai"]["reason"] == "daily_limit"

    monkeypatch.setattr("app.requests.conversation.get_ai_provider", lambda: MockProvider())
    send(fresh, case="GREEN", text="48352")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["status"] == "in_review"
    assert detail(fresh, chat["request"]["id"])["evidence"]["odometer_source"] == "driver"


# ----------------------------------------------------------------------------- hot switch of the demo

@pytest.fixture()
def switch(fresh, monkeypatch):
    """Leaves the switch as it was; `with_key()` simulates a configured GROQ_API_KEY."""
    def with_key(provider: str = "mock") -> None:
        settings = dataclasses.replace(config.get_settings(), groq_api_key=KEY, ai_provider=provider)
        monkeypatch.setattr(ai, "get_settings", lambda: settings)

    ai.restore_configured_provider(force=True)
    yield with_key
    ai._state.update(override=None, pinned=False)


def test_switch_reports_the_configured_provider_and_groq_disabled_without_key(switch):
    state = ai.ai_state()
    assert state["active"] == state["configured"] == "mock" and state["active_label"] == "Simulada"
    assert state["pinned"] is False and [o["key"] for o in state["options"]] == ["groq", "groq_text", "mock"]
    groq, groq_text, mock = state["options"]
    assert groq["available"] is False and "GROQ_API_KEY" in groq["unavailable_reason"]
    assert (groq["text_model"], groq["vision_model"]) == (TEXT_MODEL, VISION_MODEL)
    assert groq_text == {"key": "groq_text", "label": "Groq (texto)", "available": False,
                         "unavailable_reason": groq["unavailable_reason"], "text_model": TEXT_MODEL,
                         "vision_model": None}
    assert mock == {"key": "mock", "label": "Simulada", "available": True, "unavailable_reason": None,
                    "text_model": None, "vision_model": None}


def test_switch_endpoint_shows_the_state(fresh, switch):
    response = fresh.get("/api/dev/ai")
    assert response.status_code == 200 and response.json() == ai.ai_state()
    assert response.json()["active"] == "mock"


def test_switching_to_groq_without_key_is_rejected(fresh, switch):
    response = fresh.put("/api/dev/ai", json={"provider": "groq"})
    assert response.status_code == 409 and response.json()["code"] == "ai_provider_unavailable"
    assert "GROQ_API_KEY" in response.json()["detail"]
    assert fresh.get("/api/dev/ai").json()["active"] == "mock"
    assert fresh.get("/api/audit?action=demo.ai_provider").json()["items"] == []


@pytest.mark.parametrize("body", [{"provider": "gemini"}, {"provider": ""}, {}, {"provider": "groq", "pinned": "x"}])
def test_switch_rejects_unknown_providers(fresh, switch, body):
    switch()
    response = fresh.put("/api/dev/ai", json=body)
    assert response.status_code == 422 and response.json()["code"] == "validation_error"
    assert fresh.get("/api/dev/ai").json()["active"] == "mock"


def test_switch_changes_the_provider_without_restarting_and_never_shows_the_key(fresh, switch):
    switch()
    response = fresh.put("/api/dev/ai", json={"provider": "groq"}, headers=COORD)
    assert response.status_code == 200
    state = response.json()
    assert state["active"] == "groq" and state["active_label"] == "Groq" and state["configured"] == "mock"
    assert state["options"][0]["available"] is True and state["options"][0]["unavailable_reason"] is None
    health = fresh.get("/api/health").json()
    assert health["ai_provider"] == "groq"
    assert health["ai"] == {"active": "groq", "configured": "mock", "text_model": TEXT_MODEL, "vision_model": VISION_MODEL}
    assert fresh.get("/api/dev/simulator/cases").json()["ai_provider"] == "groq"
    for payload in (response.text, fresh.get("/api/dev/ai").text, fresh.get("/api/health").text):
        assert KEY not in payload

    provider = ai.get_ai_provider()
    assert isinstance(provider, SafeProvider) and provider.name == "groq"
    assert (provider.primary.text_model, provider.primary.vision_model) == (TEXT_MODEL, VISION_MODEL)

    entry = fresh.get("/api/audit?action=demo.ai_provider").json()["items"][0]
    assert entry["actor"] == "Andres Molina" and entry["role"] == "coordinator"
    assert entry["summary"] == "Andres Molina cambió la IA de la demo a Groq"
    assert (entry["before"], entry["after"]) == ({"provider": "mock"}, {"provider": "groq"})

    assert fresh.put("/api/dev/ai", json={"provider": "mock"}).json()["active"] == "mock"
    assert isinstance(ai.get_ai_provider(), MockProvider)
    assert fresh.get("/api/health").json()["ai"]["text_model"] is None


def test_switching_to_the_same_provider_is_not_recorded_again(fresh, switch):
    switch()
    fresh.put("/api/dev/ai", json={"provider": "groq"})
    fresh.put("/api/dev/ai", json={"provider": "groq"})
    fresh.put("/api/dev/ai", json={"provider": "groq", "pinned": True})
    assert len(fresh.get("/api/audit?action=demo.ai_provider").json()["items"]) == 1


@pytest.mark.parametrize("headers", [TECH, COORD, FINANCE, SUPPORT, {}])
def test_every_role_of_the_demo_can_use_the_switch(fresh, switch, headers):
    switch()
    assert fresh.put("/api/dev/ai", json={"provider": "groq"}, headers=headers).json()["active"] == "groq"
    assert fresh.post("/api/dev/ai/restore", headers=headers).json()["active"] == "mock"


def test_switch_rejects_an_unknown_role(fresh, switch):
    switch()
    response = fresh.put("/api/dev/ai", json={"provider": "groq"}, headers={"X-Demo-Role": "admin"})
    assert response.status_code == 400 and response.json()["code"] == "unknown_role"
    assert fresh.get("/api/dev/ai").json()["active"] == "mock"


def test_reset_goes_back_to_the_configured_provider(fresh, switch):
    switch("groq")                                   # AI_PROVIDER=groq with its key
    assert fresh.get("/api/dev/ai").json()["active"] == "groq"
    assert fresh.put("/api/dev/ai", json={"provider": "mock"}).json()["active"] == "mock"
    assert fresh.post("/api/dev/reset").status_code == 200
    state = fresh.get("/api/dev/ai").json()
    assert state["active"] == state["configured"] == "groq" and state["pinned"] is False


def test_pinned_provider_survives_the_reset_until_it_is_restored(fresh, switch):
    switch("groq")
    state = fresh.put("/api/dev/ai", json={"provider": "mock", "pinned": True}).json()
    assert state["active"] == "mock" and state["pinned"] is True and state["configured"] == "groq"
    fresh.post("/api/dev/reset")
    fresh.post("/api/dev/reset")
    assert fresh.get("/api/dev/ai").json()["active"] == "mock"            # the automated tests stay on mock
    assert isinstance(ai.get_ai_provider(), MockProvider)
    state = fresh.post("/api/dev/ai/restore").json()
    assert state["active"] == "groq" and state["pinned"] is False
    # A switch from the interface is not pinned: the next reset undoes it.
    fresh.put("/api/dev/ai", json={"provider": "mock"})
    fresh.post("/api/dev/reset")
    assert fresh.get("/api/dev/ai").json()["active"] == "groq"


def test_ai_provider_groq_without_key_uses_the_local_interpreter(fresh, switch, monkeypatch):
    settings = dataclasses.replace(config.get_settings(), groq_api_key="", ai_provider="groq")
    monkeypatch.setattr(ai, "get_settings", lambda: settings)
    state = fresh.get("/api/dev/ai").json()
    assert state["active"] == state["configured"] == "mock" and state["options"][0]["available"] is False
    assert isinstance(ai.get_ai_provider(), MockProvider) and fresh.get("/api/health").json()["ai_provider"] == "mock"


def test_switch_is_a_demo_route(fresh, switch, monkeypatch):
    settings = dataclasses.replace(config.get_settings(), demo_mode=False)
    monkeypatch.setattr("app.dev.router.get_settings", lambda: settings)
    for response in (fresh.get("/api/dev/ai"), fresh.put("/api/dev/ai", json={"provider": "mock"}),
                     fresh.post("/api/dev/ai/restore")):
        assert response.status_code == 404 and response.json()["code"] == "demo_disabled"


def test_suite_never_holds_a_real_key():
    assert config.get_settings().groq_api_key == "" and os.environ["GROQ_API_KEY"] == ""
    assert ai.active_provider() == "mock"


# ----------------------------------------------------------------------------- mixed mode (groq_text)

MIXED_PHOTO_LABEL = "simulada (lectura de ejemplo; la foto no se envió a Groq)"


def _text_only(*responses) -> tuple[TextOnlyProvider, Recorder]:
    """Mixed mode over a fake transport that refuses anything that is not a text request."""
    recorder = Recorder(*responses)

    def guarded(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == TEXT_MODEL, "el modo mixto llamó al modelo de visión"
        assert all(isinstance(message["content"], str) for message in body["messages"]), "se envió una imagen"
        return recorder(request)

    groq = GroqProvider(KEY, TEXT_MODEL, VISION_MODEL, transport=httpx.MockTransport(guarded), sleep=lambda _: None)
    return TextOnlyProvider(SafeProvider(groq, MockProvider()), MockProvider()), recorder


def test_mixed_mode_sends_the_text_to_groq_and_records_it():
    provider, recorder = _text_only(_completion({"intent": "refuel", "quantity": 6.7, "quantity_unit": "m3"}))
    result, source = ai.interpret(provider, "Necesito tanquear 6,7 m3 de gas", {"last_question": None})
    assert provider.name == "groq_text"
    assert (result.intent, result.quantity, result.quantity_unit) == ("refuel", 6.7, "m3")
    assert (source["kind"], source["provider"], source["model"], source["status"]) == ("text", "groq", TEXT_MODEL, "ok")
    assert source_label(source) == "Groq · gpt-oss-120b" and "mode" not in source
    assert len(recorder.requests) == 1 and recorder.bodies[0]["model"] == TEXT_MODEL
    assert provider.extract_request("Necesito tanquear 6,7 m3 de gas", {}).intent == "refuel"


@pytest.mark.parametrize("photo, expected", [("veh901", (48352, 0.25)), ("veh015", (24086, 0.25))])
def test_mixed_mode_reads_the_photo_locally_and_never_calls_groq(photo, expected):
    provider, recorder = _text_only(AssertionError("la foto llegó al transporte de Groq"))
    reading, source = ai.read_photo(provider, SVG[photo], "image/svg+xml")
    local = MockProvider().read_dashboard(SVG[photo], "image/svg+xml")
    assert reading == local and (reading.odometer_km, reading.fuel_level) == expected
    assert provider.read_dashboard(SVG[photo]) == local
    assert recorder.requests == []
    # Recorded as the sample reading of the local reader, never as a model of Groq.
    assert (source["kind"], source["provider"], source["model"], source["status"]) == ("vision", "mock", None, "ok")
    assert source["mode"] == "groq_text" and source["reason"] is None and "intended" not in source
    assert source_label(source) == MIXED_PHOTO_LABEL and "Groq ·" not in source_label(source)


def test_mixed_mode_with_an_unknown_photo_gives_no_reading_and_sends_nothing():
    provider, recorder = _text_only(AssertionError("la foto llegó al transporte de Groq"))
    reading, source = ai.read_photo(provider, b"\x89PNG una foto que no es de ejemplo", "image/png")
    assert reading.odometer_km is None and reading.confidence.odometer_km == 0.0
    assert (source["provider"], source["status"], source["mode"]) == ("mock", "ok", "groq_text")
    assert recorder.requests == []


@pytest.mark.parametrize("failure, reason, label", [
    (httpx.ReadTimeout("lento"), "timeout", "intérprete local (respaldo: Groq, tiempo de espera agotado)"),
    (httpx.ConnectError("sin red"), "network", "intérprete local (respaldo: Groq, sin conexión)"),
    (_rate_limited("tokens per day (TPD). Please try again in 2m20s."), "daily_limit",
     "intérprete local (respaldo: Groq, límite diario de la cuenta)"),
    (_completion("no es JSON"), "invalid_response", "intérprete local (respaldo: Groq, respuesta no válida)"),
])
def test_mixed_mode_text_falls_back_to_the_local_interpreter_and_says_so(failure, reason, label):
    provider, _ = _text_only(failure)
    result, source = ai.interpret(provider, "Necesito tanquear 6,7 m3 de gas", {})
    assert result.intent == "refuel" and result.quantity == 6.7            # the local interpreter answered
    assert (source["provider"], source["model"], source["status"], source["reason"]) == ("mock", None, "fallback", reason)
    assert source["intended"] == {"provider": "groq", "model": TEXT_MODEL} and source_label(source) == label


def test_green_case_in_mixed_mode_gives_the_script_figures_and_records_each_provider(fresh, monkeypatch):
    provider, recorder = _text_only(_answer_like_the_model)
    monkeypatch.setattr("app.requests.conversation.get_ai_provider", lambda: provider)
    send(fresh, case="GREEN", text="Hola, necesito tanquear")
    send(fresh, case="GREEN", text="Sí, es para esa ruta")
    send(fresh, case="GREEN", media_id="media-veh901")
    send(fresh, case="GREEN", text="Sí, es correcto")
    chat = conversation(fresh, WA["GREEN"])
    assert chat["request"]["status"] == "in_review" and chat["request"]["suggested_amount"] == 90000

    inbound = [m for m in chat["messages"] if m["direction"] == "inbound"]
    assert [m["ai"]["label"] for m in inbound] == ["Groq · gpt-oss-120b", "Groq · gpt-oss-120b", MIXED_PHOTO_LABEL,
                                                   "Groq · gpt-oss-120b"]
    assert [(m["ai"]["kind"], m["ai"]["provider"]) for m in inbound] == [("text", "groq"), ("text", "groq"),
                                                                         ("vision", "mock"), ("text", "groq")]
    assert inbound[2]["ai"]["model"] is None

    body = detail(fresh, chat["request"]["id"])
    evidence = body["evidence"]
    assert evidence["ai_source_label"] == MIXED_PHOTO_LABEL
    assert (evidence["ai_source"]["provider"], evidence["ai_source"]["model"], evidence["ai_source"]["mode"]) == (
        "mock", None, "groq_text")
    assert (evidence["odometer_km"], evidence["fuel_level"]) == (48352, 0.25)
    read = next(a for a in body["audit"] if a["action"] == "evidence.read")
    assert read["after"]["ai"]["label"] == MIXED_PHOTO_LABEL
    assert (read["after"]["ai"]["provider"], read["after"]["ai"]["mode"]) == ("mock", "groq_text")

    # Three text requests and not one for the photo (the transport would have refused it).
    assert len(recorder.requests) == 3 and {sent["model"] for sent in recorder.bodies} == {TEXT_MODEL}
    assert "image_url" not in "".join(request.content.decode() for request in recorder.requests)


def test_typo_case_in_mixed_mode_still_shows_the_sample_reading(fresh, monkeypatch):
    provider, _ = _text_only(_answer_like_the_model)
    monkeypatch.setattr("app.requests.conversation.get_ai_provider", lambda: provider)
    send(fresh, case="VEH015", text="Hola, necesito tanquear")
    send(fresh, case="VEH015", text="Sí, es para esa ruta")
    send(fresh, case="VEH015", media_id="media-veh015")
    chat = conversation(fresh, WA["VEH015"])
    evidence = detail(fresh, chat["request"]["id"])["evidence"]
    assert evidence["odometer_read"] == 24086 and evidence["proposed_odometer"] == 34086
    assert evidence["ai_source_label"] == MIXED_PHOTO_LABEL


def test_mixed_mode_is_switchable_without_restarting_and_is_recorded(fresh, switch):
    switch()
    response = fresh.put("/api/dev/ai", json={"provider": "groq_text"}, headers=COORD)
    assert response.status_code == 200
    state = response.json()
    assert (state["active"], state["active_label"], state["configured"], state["pinned"]) == (
        "groq_text", "Groq (texto)", "mock", False)
    assert [(o["key"], o["available"]) for o in state["options"]] == [("groq", True), ("groq_text", True), ("mock", True)]
    health = fresh.get("/api/health").json()
    assert health["ai_provider"] == "groq_text"
    assert health["ai"] == {"active": "groq_text", "configured": "mock", "text_model": TEXT_MODEL, "vision_model": None}
    assert fresh.get("/api/dev/simulator/cases").json()["ai_provider"] == "groq_text"
    for payload in (response.text, fresh.get("/api/dev/ai").text, fresh.get("/api/health").text):
        assert KEY not in payload

    provider = ai.get_ai_provider()
    assert isinstance(provider, TextOnlyProvider) and provider.name == "groq_text"
    assert isinstance(provider.text, SafeProvider) and isinstance(provider.text.primary, GroqProvider)
    assert provider.text.primary.text_model == TEXT_MODEL and isinstance(provider.vision, MockProvider)
    # The provider the application builds reads the photo without the network client of Groq.
    provider.text.primary._client = None
    reading, source = ai.read_photo(provider, SVG["veh901"], "image/svg+xml")
    assert reading.odometer_km == 48352 and source_label(source) == MIXED_PHOTO_LABEL
    ai._build.cache_clear()

    entry = fresh.get("/api/audit?action=demo.ai_provider").json()["items"][0]
    assert entry["actor"] == "Andres Molina" and entry["role"] == "coordinator"
    assert entry["summary"] == "Andres Molina cambió la IA de la demo a Groq (texto)"
    assert (entry["before"], entry["after"]) == ({"provider": "mock"}, {"provider": "groq_text"})


def test_switch_goes_through_the_three_modes_and_records_each_change(fresh, switch):
    switch()
    for provider, label in (("groq_text", "Groq (texto)"), ("groq", "Groq"), ("groq_text", "Groq (texto)"),
                            ("mock", "Simulada")):
        state = fresh.put("/api/dev/ai", json={"provider": provider}).json()
        assert (state["active"], state["active_label"]) == (provider, label)
        assert fresh.get("/api/health").json()["ai_provider"] == provider
    fresh.put("/api/dev/ai", json={"provider": "mock"})                    # already active: not recorded again
    entries = fresh.get("/api/audit?action=demo.ai_provider").json()["items"]
    changes = sorted((entry["before"]["provider"], entry["after"]["provider"]) for entry in entries)
    assert changes == sorted([("mock", "groq_text"), ("groq_text", "groq"), ("groq", "groq_text"), ("groq_text", "mock")])
    assert isinstance(ai.get_ai_provider(), MockProvider)


def test_switching_to_the_mixed_mode_without_key_is_rejected(fresh, switch):
    response = fresh.put("/api/dev/ai", json={"provider": "groq_text"})
    assert response.status_code == 409 and response.json()["code"] == "ai_provider_unavailable"
    assert "GROQ_API_KEY" in response.json()["detail"]
    assert fresh.get("/api/dev/ai").json()["active"] == "mock"
    assert fresh.get("/api/audit?action=demo.ai_provider").json()["items"] == []
    with pytest.raises(LookupError):
        ai.set_active_provider("groq_text")


def test_reset_from_the_mixed_mode_goes_back_to_the_configured_provider(fresh, switch):
    switch()                                         # AI_PROVIDER=mock with the key set, as in the presentation
    assert fresh.put("/api/dev/ai", json={"provider": "groq_text"}).json()["active"] == "groq_text"
    assert fresh.post("/api/dev/reset").status_code == 200
    state = fresh.get("/api/dev/ai").json()
    assert state["active"] == state["configured"] == "mock" and state["pinned"] is False


def test_mixed_mode_as_the_configured_provider_survives_the_reset(fresh, switch):
    switch("groq_text")                              # AI_PROVIDER=groq_text with its key
    state = fresh.get("/api/dev/ai").json()
    assert state["active"] == state["configured"] == "groq_text"
    assert fresh.put("/api/dev/ai", json={"provider": "mock"}).json()["active"] == "mock"
    assert fresh.post("/api/dev/reset").status_code == 200
    assert fresh.get("/api/dev/ai").json()["active"] == "groq_text"
    assert fresh.post("/api/dev/ai/restore").json()["active"] == "groq_text"


def test_ai_provider_groq_text_without_key_uses_the_local_interpreter(fresh, switch, monkeypatch):
    settings = dataclasses.replace(config.get_settings(), groq_api_key="", ai_provider="groq_text")
    monkeypatch.setattr(ai, "get_settings", lambda: settings)
    state = fresh.get("/api/dev/ai").json()
    assert state["active"] == state["configured"] == "mock"
    assert [o["available"] for o in state["options"]] == [False, False, True]
    assert isinstance(ai.get_ai_provider(), MockProvider) and fresh.get("/api/health").json()["ai_provider"] == "mock"


@pytest.fixture()
def environment(monkeypatch):
    """Settings rebuilt from the environment variables of the test, and the real ones back afterwards."""
    def load(**variables: str):
        for name, value in variables.items():
            monkeypatch.setenv(name, value)
        config.get_settings.cache_clear()
        return config.get_settings()

    ai.restore_configured_provider(force=True)
    yield load
    monkeypatch.undo()
    config.get_settings.cache_clear()
    ai._build.cache_clear()
    ai._state.update(override=None, pinned=False)


@pytest.mark.parametrize("value, key, expected", [
    ("groq_text", KEY, "groq_text"), (" GROQ_TEXT ", KEY, "groq_text"), ("groq", KEY, "groq"),
    ("groq_text", "", "mock"), ("mock", KEY, "mock"), ("otro", KEY, "mock"),
])
def test_ai_provider_variable_selects_the_mode(environment, value, key, expected):
    settings = environment(AI_PROVIDER=value, GROQ_API_KEY=key)
    assert settings.ai_provider == value.strip().lower()
    assert ai.configured_provider() == ai.active_provider() == expected
    provider = ai.get_ai_provider()
    assert provider.name == expected
    assert isinstance(provider, {"groq_text": TextOnlyProvider, "groq": SafeProvider, "mock": MockProvider}[expected])


def test_environment_of_the_suite_is_back_after_changing_the_variable():
    assert config.get_settings().ai_provider == "mock" and config.get_settings().groq_api_key == ""
    assert ai.active_provider() == "mock"


# ----------------------------------------------------------------------------- optional live test

@pytest.mark.live_ai
@pytest.mark.skipif(os.getenv("RUN_LIVE_AI") != "1" or not LIVE_GROQ_KEY,
                    reason="prueba en vivo: necesita RUN_LIVE_AI=1 y GROQ_API_KEY")
def test_live_groq_interprets_a_message_and_reads_a_sample_photo():
    provider = GroqProvider(LIVE_GROQ_KEY, os.getenv("GROQ_TEXT_MODEL") or TEXT_MODEL,
                            os.getenv("GROQ_VISION_MODEL") or VISION_MODEL, timeout_s=30, max_retry_wait_s=30)
    extracted = provider.extract_request("Necesito tanquear 6,7 m3 de gas", {"last_question": None})
    assert (extracted.intent, extracted.quantity, extracted.quantity_unit) == ("refuel", 6.7, "m3")
    reading = provider.read_dashboard(SVG["veh199"], "image/svg+xml")
    assert reading.odometer_km == 195406 and reading.fuel_level is not None
