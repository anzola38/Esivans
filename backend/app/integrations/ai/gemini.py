"""Optional Gemini provider (AI_PROVIDER=gemini + GEMINI_API_KEY + GEMINI_MODEL).

Uses the official `google-genai` SDK with structured output against the Pydantic schemas, low
temperature, timeout and retries. Gemini neither decides nor computes the amount: it returns
data that the backend validates. If it fails, the caller falls back to asking the driver.
The model name is NOT hardcoded: set GEMINI_MODEL to a Flash-family model from the official
documentation. In production this would be the paid Gemini API or Vertex AI.
"""
from __future__ import annotations

import logging
import time

from app.integrations.ai.base import DashboardReading, ExtractedRequest

log = logging.getLogger(__name__)

EXTRACT_PROMPT = (
    "Eres el asistente de combustible de una empresa de transporte. Interpreta el mensaje del conductor "
    "y devuelve solo los campos del esquema. intent: refuel si pide tanquear, status si pregunta por su "
    "solicitud, greeting si solo saluda, unknown en otro caso. confirmation: true o false solo si responde "
    "sí o no a la última pregunta. No inventes datos: deja null lo que no esté en el mensaje.\n"
    "Última pregunta del asistente: {question}\nMensaje del conductor: {text}"
)
DASHBOARD_PROMPT = (
    "Lee la foto del tablero de un vehículo. Devuelve odometer_km (entero, kilometraje total del odómetro), "
    "fuel_level (fracción entre 0 y 1 según el medidor de combustible) y confidence por campo (0 a 1). "
    "Si un dato no se ve con claridad, devuélvelo en null y con confianza baja. No estimes."
)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_s: float = 20.0, retries: int = 2) -> None:
        from google import genai  # imported lazily: the mock provider must work without the SDK
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        self._model = model
        self._retries = retries

    def _generate(self, contents: list, schema: type):
        config = self._types.GenerateContentConfig(
            temperature=0.1, response_mime_type="application/json", response_schema=schema)
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._client.models.generate_content(model=self._model, contents=contents, config=config)
                return schema.model_validate_json(response.text)
            except Exception as exc:  # noqa: BLE001 - any provider failure is retried, then reported
                last_error = exc
                log.warning("Gemini falló (intento %s): %s", attempt + 1, exc.__class__.__name__)
                time.sleep(0.5 * (2 ** attempt))
        raise RuntimeError("Gemini no respondió") from last_error

    def extract_request(self, text: str, context: dict) -> ExtractedRequest:
        prompt = EXTRACT_PROMPT.format(question=context.get("last_question") or "ninguna", text=text)
        return self._generate([prompt], ExtractedRequest)

    def read_dashboard(self, image: bytes, mime_type: str = "image/jpeg") -> DashboardReading:
        part = self._types.Part.from_bytes(data=image, mime_type=mime_type)
        return self._generate([part, DASHBOARD_PROMPT], DashboardReading)
