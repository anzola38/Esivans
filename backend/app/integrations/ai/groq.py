"""Groq provider (AI_PROVIDER=groq + GROQ_API_KEY): OpenAI-compatible chat completions over httpx.

Two models, because the rate limits are per model: a text model interprets the driver's message
and a vision model reads the photo of the dashboard. Groq neither decides nor computes the
amount: it returns JSON that is normalised and validated here against the Pydantic contract.
Anything that does not validate is a failure, and the caller falls back (see `SafeProvider`).

Only the text of the message, a generic wording of the assistant's last question and the image
are sent: no names, phone numbers or plates.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Callable

import httpx
from pydantic import ValidationError

from app.integrations import media
from app.integrations.ai.base import DashboardReading, ExtractedRequest

log = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
USER_AGENT = "esivans-combustible/0.1 (prototipo)"
DEFAULT_TEXT_MODEL = "openai/gpt-oss-120b"
DEFAULT_VISION_MODEL = "qwen/qwen3.8-27b"

# What the assistant asked last, by conversation step. A fixed wording is sent instead of the real
# message, which may carry the driver's name or the route.
STEP_QUESTIONS = {
    "service": "¿El tanqueo es para tu próximo servicio programado (esa ruta)? Si no, dime para qué recorrido es.",
    "photo": "Envíame una foto del tablero donde se vean el kilometraje y el nivel de combustible.",
    "confirm": "Leí en la foto el kilometraje y el nivel de combustible, y te propuse un kilometraje. ¿Es correcto?",
    "manual_km": "Escríbeme el kilometraje que marca el odómetro, solo el número.",
    "not_needed": "Por ahora no necesitas tanquear. ¿Lo dejamos así?",
}
NO_QUESTION = "ninguna (el conductor inicia la conversación)"

EXTRACT_SYSTEM = (
    "Eres el intérprete de mensajes de WhatsApp del asistente de combustible de una empresa de transporte en "
    "Colombia. Recibes la última pregunta que hizo el asistente y el mensaje del conductor. Solo extraes datos: "
    "no decides nada ni respondes al conductor. Devuelve ÚNICAMENTE un objeto JSON con estas claves exactas:\n"
    '- "intent": "refuel" si pide o necesita combustible (tanquear, cargar, llenar, gasolina, ACPM, diésel, gas); '
    '"status" solo si pregunta cómo va su solicitud o si ya fue autorizada; "greeting" si únicamente saluda; '
    '"unknown" en cualquier otro caso (respuestas como sí, no, un número, un motivo o un recorrido son "unknown").\n'
    '- "confirmation": true si el mensaje afirma o acepta lo que preguntó el asistente (sí, correcto, listo, dale, '
    "de acuerdo, entendido, así es); false si lo niega, lo rechaza, pide corregir o dice que es otro; null si el "
    "mensaje no responde sí o no a la última pregunta, o si no hubo pregunta. Explicar un motivo o un recorrido sin "
    "decir sí ni no es null.\n"
    '- "chosen_service": "proposed" si acepta que el tanqueo es para el servicio o la ruta propuesta; "other" si '
    "dice que es otro servicio, otra ruta u otro recorrido; null en los demás casos.\n"
    '- "quantity": cantidad de combustible que pide, como número, solo si la escribe junto a su unidad; si no, null.\n'
    '- "quantity_unit": "gal" para galones o "m3" para metros cúbicos (m3, m³); null si no hay cantidad.\n'
    '- "odometer_km": kilometraje del odómetro que el conductor escribe, como entero sin separadores; null si no '
    "escribe un kilometraje. Nunca tomes como kilometraje una cantidad de combustible, una hora ni una placa.\n"
    '- "plate": placa del vehículo si la escribe (tres letras y tres números, por ejemplo ABC123), en mayúsculas y '
    "sin guion ni espacios; si no, null.\n"
    "Formato de números de Colombia (es-CO): el punto separa miles y la coma separa decimales. «195.406 km» es "
    "195406; «34.086» como kilometraje es 34086; «6,7 m3» es 6.7; «48 360» es 48360.\n"
    "No inventes ni completes datos: todo lo que no esté escrito en el mensaje va en null."
)
EXTRACT_USER = "Última pregunta del asistente: {question}\nMensaje del conductor: «{text}»"

DASHBOARD_PROMPT = (
    "La imagen es la foto del tablero de un vehículo. Lee dos cosas y devuelve ÚNICAMENTE un objeto JSON.\n"
    "1) Odómetro: el número total de kilómetros, dígito por dígito, sin confundirlo con el contador parcial "
    "(TRIP).\n"
    "2) Medidor de combustible: una aguja gira sobre un arco que va de E (vacío) a F (lleno). Estima qué "
    "porcentaje del recorrido del arco, desde E hasta F, ha avanzado la PUNTA de la aguja: E es 0, la marca 1/4 "
    "es 25, la marca 1/2 es 50, la marca 3/4 es 75 y F es 100; las marcas cortas sin rótulo quedan en 12, 37, 62 "
    "y 87.\n"
    "Claves del JSON, en este orden:\n"
    '- "odometer_digits": los dígitos del odómetro tal como se ven, como texto (por ejemplo "048352"). Si un '
    'dígito no se distingue por un reflejo o está tapado, escribe "?" en su lugar.\n'
    '- "needle": frase corta: sobre qué marca está la punta de la aguja, o entre cuáles y más cerca de cuál.\n'
    '- "fuel_percent": entero de 0 a 100 con el avance de la punta de la aguja de E a F; null si no se ve el '
    "medidor.\n"
    '- "confidence": {"odometer_km": número de 0 a 1, "fuel_level": número de 0 a 1}: qué tan seguro estás de '
    "cada lectura. Baja la confianza si hay reflejos, dígitos tapados o dudas sobre la posición de la aguja.\n"
    "No estimes ni inventes: lo que no se vea va en null y con confianza baja."
)

FUEL_MARKS = {"E": 0.0, "1/8": 0.125, "1/4": 0.25, "3/8": 0.375, "1/2": 0.5, "5/8": 0.625, "3/4": 0.75,
              "7/8": 0.875, "F": 1.0, "¼": 0.25, "½": 0.5, "¾": 0.75, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
              "0": 0.0, "1": 1.0, "VACIO": 0.0, "VACÍO": 0.0, "LLENO": 1.0, "EMPTY": 0.0, "FULL": 1.0}
MAX_ODOMETER_KM = 9_999_999
# Measured against the real service, the vision model reported 0.9 or more for fuel levels that were
# one mark off in about half of the readings. Its own confidence is capped so the console shows the
# level as doubtful and the technician looks at the photo before trusting the suggested amount.
FUEL_LEVEL_CONFIDENCE_CAP = 0.7
_RETRY_HINT = re.compile(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)\s*(ms|s)", re.IGNORECASE)
_PLATE = re.compile(r"^[A-Z]{3}\d{3}$")
_TRUE = {"true", "si", "sí", "yes", "1"}
_FALSE = {"false", "no", "0"}
_NULL = {"", "null", "none", "n/a", "ninguno", "ninguna"}


class GroqError(RuntimeError):
    """Failure of the provider. `code` is a short stable reason that is safe to store and show."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# --------------------------------------------------------------------------- normalisation

def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in _NULL)


def _es_number(value: Any) -> float | None:
    """Number as the model returned it: a JSON number, or text in es-CO format ("6,7", "195.406")."""
    if _blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d.,-]", "", str(value))
    if not re.search(r"\d", text):
        return None
    if "," in text:                                   # decimal comma: the dots are thousands
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):  # only thousands separators
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _odometer_from_text(value: Any, message: str) -> int | None:
    """Odometer typed by the driver. It must be written in the message: a value that is not there is
    dropped, and "195.406" returned as the decimal 195.406 is read back as 195406."""
    if _blank(value) or isinstance(value, bool):
        return None
    written = _digits(re.sub(r"(\d)[.\s](?=\d{3}(?!\d))", r"\1", message))
    candidates: list[int] = []
    if isinstance(value, float) and not value.is_integer():
        candidates.append(int(round(value * 1000)))
    else:
        number = _es_number(value)
        if number is not None:
            candidates.append(int(number))
            if isinstance(value, str) and not float(number).is_integer():
                candidates.append(int(round(number * 1000)))
    for candidate in candidates:
        if 0 <= candidate <= MAX_ODOMETER_KM and str(candidate) in written:
            return candidate
    return None


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if _blank(value):
        return None
    text = str(value).strip().lower()
    return True if text in _TRUE else False if text in _FALSE else None


def _unit(value: Any) -> str | None:
    if _blank(value):
        return None
    text = str(value).strip().lower().replace("³", "3")
    if text.startswith("m") or "cubic" in text or "cúbic" in text:
        return "m3"
    if text.startswith("gal"):
        return "gal"
    return None


def normalize_extraction(raw: dict, message: str) -> dict:
    intent = str(raw.get("intent") or "unknown").strip().lower()
    chosen = None if _blank(raw.get("chosen_service")) else str(raw.get("chosen_service")).strip().lower()
    plate = None if _blank(raw.get("plate")) else re.sub(r"[^A-Z0-9]", "", str(raw.get("plate")).upper())
    quantity, unit = _es_number(raw.get("quantity")), _unit(raw.get("quantity_unit"))
    if quantity is None or unit is None or quantity <= 0:      # a quantity only counts with its unit
        quantity, unit = None, None
    return {
        "intent": intent if intent in ("refuel", "status", "greeting", "unknown") else "unknown",
        "plate": plate if plate and _PLATE.match(plate) else None,
        "chosen_service": chosen if chosen in ("proposed", "other") else None,
        "confirmation": _boolean(raw.get("confirmation")),
        "quantity": quantity,
        "quantity_unit": unit,
        "odometer_km": _odometer_from_text(raw.get("odometer_km"), message),
    }


def _confidence(value: Any) -> float:
    number = _es_number(value)
    if number is None:
        return 0.0
    if number > 1:                      # some models answer 0-100
        number = number / 100
    return round(max(0.0, min(1.0, number)), 2)


def _fuel_level(value: Any) -> float | None:
    """Fuel level quantised to eighths, from the closed list of marks or from a number."""
    if _blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, str):
        key = value.strip().upper().replace(" ", "")
        if key in FUEL_MARKS:
            return FUEL_MARKS[key]
        fraction = re.fullmatch(r"(\d)/(\d)", key)
        if fraction and int(fraction.group(2)):
            value = int(fraction.group(1)) / int(fraction.group(2))
    number = _es_number(value)
    if number is None:
        return None
    if 1 < number <= 100:
        number = number / 100
    if not 0 <= number <= 1:
        return None
    return round(number * 8) / 8


def normalize_reading(raw: dict) -> dict:
    confidence = raw.get("confidence") if isinstance(raw.get("confidence"), dict) else {}
    odometer_conf = _confidence(confidence.get("odometer_km"))
    level_conf = _confidence(confidence.get("fuel_level"))

    digits = raw.get("odometer_digits", raw.get("odometer_km"))
    odometer: int | None = None
    if not _blank(digits) and not isinstance(digits, bool):
        text = str(int(digits)) if isinstance(digits, float) and digits.is_integer() else str(digits).strip()
        if "?" in text or not re.fullmatch(r"[\d.\s]+", text):
            odometer_conf = min(odometer_conf, 0.3)     # the model says a digit cannot be read
        clean = _digits(text)
        if clean and "?" not in text:
            odometer = int(clean)
            if odometer > MAX_ODOMETER_KM:
                odometer = None
    if odometer is None:
        odometer_conf = 0.0

    if not _blank(raw.get("fuel_percent")):
        percent = _es_number(raw.get("fuel_percent"))
        level = round(percent / 100 * 8) / 8 if percent is not None and 0 <= percent <= 100 else None
    else:                                           # tolerated: a mark of the gauge or a fraction
        level = _fuel_level(raw.get("fuel_mark", raw.get("fuel_level")))
    level_conf = 0.0 if level is None else min(level_conf, FUEL_LEVEL_CONFIDENCE_CAP)
    return {"odometer_km": odometer, "fuel_level": level,
            "confidence": {"odometer_km": odometer_conf, "fuel_level": level_conf}}


# --------------------------------------------------------------------------- provider

class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, text_model: str = DEFAULT_TEXT_MODEL, vision_model: str = DEFAULT_VISION_MODEL, *,
                 timeout_s: float = 8.0, max_retry_wait_s: float = 4.0, retries: int = 1,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY vacío")
        self.text_model, self.vision_model = text_model, vision_model
        self._key = api_key
        self._max_wait, self._retries, self._sleep = max_retry_wait_s, retries, sleep
        self._client = httpx.Client(
            base_url=GROQ_BASE_URL, transport=transport,
            timeout=httpx.Timeout(timeout_s, connect=min(4.0, timeout_s)),
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT})
        self.last_usage: dict = {}

    # -- transport

    def _scrub(self, text: object) -> str:
        return str(text).replace(self._key, "***")[:300]

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        header = response.headers.get("retry-after")
        try:
            if header is not None:
                return float(header)
        except ValueError:
            pass
        hint = _RETRY_HINT.search(response.text or "")
        if not hint:
            return None
        seconds = float(hint.group(2)) / (1000 if hint.group(3).lower() == "ms" else 1)
        return seconds + 60 * int(hint.group(1) or 0)

    def _chat(self, model: str, messages: list[dict], max_tokens: int, **extra: Any) -> dict:
        body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}, **extra}
        attempt = 0
        while True:
            try:
                response = self._client.post("/chat/completions", json=body)
            except httpx.TimeoutException as exc:
                raise GroqError("timeout", exc.__class__.__name__) from None
            except httpx.HTTPError as exc:
                raise GroqError("network", exc.__class__.__name__) from None
            if response.status_code == 429:
                wait = self._retry_after(response)
                if wait is not None and wait <= self._max_wait and attempt < self._retries:
                    attempt += 1
                    log.info("Groq pidió esperar %.1f s (límite por minuto de %s): se reintenta una vez", wait, model)
                    self._sleep(wait + 0.25)
                    continue
                # The daily quota of the account is another story: waiting a few seconds does not help.
                daily = "per day" in (response.text or "").lower()
                raise GroqError("daily_limit" if daily else "rate_limited",
                                f"espera de {wait:.0f} s" if wait is not None else "sin tiempo de espera")
            if response.status_code >= 400:
                raise GroqError("http_error", f"HTTP {response.status_code}: {self._scrub(self._error_message(response))}")
            try:
                payload = response.json()
                content = payload["choices"][0]["message"].get("content")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise GroqError("invalid_response", "respuesta sin choices") from None
            self.last_usage = payload.get("usage") or {}
            if not content or not str(content).strip():
                raise GroqError("empty_response", str(payload["choices"][0].get("finish_reason")))
            return self._json_object(str(content))

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            return str(response.json()["error"]["message"])
        except Exception:  # noqa: BLE001 - any body shape
            return response.text or ""

    @staticmethod
    def _json_object(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
        try:
            data = json.loads(text)
        except ValueError:
            raise GroqError("invalid_response", "el contenido no es JSON") from None
        if not isinstance(data, dict):
            raise GroqError("invalid_response", "el contenido no es un objeto JSON")
        return data

    # -- contract

    def extract_request(self, text: str, context: dict) -> ExtractedRequest:
        question = STEP_QUESTIONS.get(context.get("last_question") or "", NO_QUESTION)
        message = (text or "").strip()[:500]
        extra = {"reasoning_effort": "low"} if "gpt-oss" in self.text_model else {}
        raw = self._chat(self.text_model, [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": EXTRACT_USER.format(question=question, text=message)},
        ], max_tokens=400, **extra)
        try:
            return ExtractedRequest.model_validate(normalize_extraction(raw, message))
        except ValidationError as exc:
            raise GroqError("invalid_response", f"{exc.error_count()} campos no validan") from None

    def read_dashboard(self, image: bytes, mime_type: str = "image/svg+xml") -> DashboardReading:
        if mime_type == "image/svg+xml":
            raster = media.raster_for(image)
            if raster is None:
                raise GroqError("no_raster", "la imagen SVG no tiene PNG generado")
            image, mime_type = raster
        if mime_type not in ("image/png", "image/jpeg"):
            raise GroqError("unsupported_image", mime_type)
        url = f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"
        raw = self._chat(self.vision_model, [{"role": "user", "content": [
            {"type": "text", "text": DASHBOARD_PROMPT},
            {"type": "image_url", "image_url": {"url": url}},
        ]}], max_tokens=200)
        try:
            return DashboardReading.model_validate(normalize_reading(raw))
        except ValidationError as exc:
            raise GroqError("invalid_response", f"{exc.error_count()} campos no validan") from None
