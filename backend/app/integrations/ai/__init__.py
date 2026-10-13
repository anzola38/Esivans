"""AI adapter: provider selection, hot switch for the demo, fallback and provenance.

The provider comes from AI_PROVIDER (mock | groq | groq_text | gemini). In demo mode the presenter
can switch between `mock`, `groq_text` and `groq` without restarting; "Reiniciar demo" goes back to
the configured one. `groq_text` is the mixed mode: Groq interprets what the driver writes and the
photo is never sent to it, the local sample reader answers and is recorded as such.
Any failure of a remote provider falls back locally, and every interpretation and reading carries
a `source`: which provider and model really answered, so nothing is shown as read by a model that
did not answer.
"""
from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache

from app.config import get_settings
from app.integrations.ai.base import AIProvider, DashboardReading, ExtractedRequest
from app.integrations.ai.mock import MockProvider

log = logging.getLogger(__name__)

PROVIDER_LABELS = {"mock": "Simulada", "groq": "Groq", "groq_text": "Groq (texto)", "gemini": "Gemini"}
SWITCHABLE = ("groq", "groq_text", "mock")
GROQ_MODES = ("groq", "groq_text")          # both need GROQ_API_KEY
MISSING_KEY_REASON = "Falta GROQ_API_KEY en el archivo .env: sin la clave solo funciona la IA simulada."
REASON_LABELS = {
    "rate_limited": "límite por minuto",
    "daily_limit": "límite diario de la cuenta",
    "timeout": "tiempo de espera agotado",
    "network": "sin conexión",
    "http_error": "error del servicio",
    "invalid_response": "respuesta no válida",
    "empty_response": "respuesta vacía",
    "no_raster": "imagen sin versión PNG",
    "unsupported_image": "formato de imagen no admitido",
}


# --------------------------------------------------------------------------- provenance

def _model_of(provider: object, kind: str) -> str | None:
    specific = getattr(provider, "vision_model" if kind == "vision" else "text_model", None)
    return specific or getattr(provider, "model", None)


def make_source(provider: object, kind: str, *, status: str = "ok", reason: str | None = None,
                answered_by: str | None = None, elapsed_ms: int | None = None) -> dict:
    """Who produced a result. `status`: ok, fallback (the local interpreter answered instead of
    `intended`) or failed (nobody read the photo: the driver is asked)."""
    name = getattr(provider, "name", "mock")
    source = {"kind": kind, "provider": answered_by or name,
              "model": None if answered_by else _model_of(provider, kind),
              "status": status, "reason": reason, "elapsed_ms": elapsed_ms}
    if status != "ok":
        source["intended"] = {"provider": name, "model": _model_of(provider, kind)}
    return source


def short_model(model: str | None) -> str:
    return (model or "").split("/")[-1]


def source_label(source: dict | None) -> str | None:
    """Short Spanish text for the interface, e.g. "Groq · qwen3.8-27b"."""
    if not source:
        return None
    status = source.get("status", "ok")
    if status == "ok":
        if source.get("provider") == "mock":
            if source.get("kind") != "vision":
                return "simulada (intérprete local)"
            if source.get("mode") == "groq_text":
                return "simulada (lectura de ejemplo; la foto no se envió a Groq)"
            return "simulada (lectura de ejemplo)"
        name = PROVIDER_LABELS.get(source.get("provider"), source.get("provider"))
        return f"{name} · {short_model(source.get('model'))}" if source.get("model") else str(name)
    intended = PROVIDER_LABELS.get((source.get("intended") or {}).get("provider"), "el proveedor")
    reason = REASON_LABELS.get(source.get("reason") or "", "no respondió")
    if status == "fallback":
        return f"intérprete local (respaldo: {intended}, {reason})"
    return f"{intended} no leyó la foto ({reason}): el conductor escribe el dato"


def _reason_of(exc: Exception) -> str:
    return getattr(exc, "code", None) or "error"


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class SafeProvider:
    """Wraps a remote provider so the flow never stops.

    Text: the local interpreter answers. Photo: there is no local reader (the mock only knows the
    sample photos by their hash, and passing its stored values off as a reading would not be honest),
    so the reading comes back empty and the assistant asks the driver to type the odometer.
    """

    def __init__(self, primary: AIProvider, fallback: AIProvider) -> None:
        self.primary, self.fallback = primary, fallback
        self.name = primary.name

    def extract_request_traced(self, text: str, context: dict) -> tuple[ExtractedRequest, dict]:
        started = time.monotonic()
        try:
            result = self.primary.extract_request(text, context)
            return result, make_source(self.primary, "text", elapsed_ms=_ms(started))
        except Exception as exc:  # noqa: BLE001
            log.warning("Fallo del proveedor de IA al interpretar el texto (%s); responde el intérprete local", exc)
            return self.fallback.extract_request(text, context), make_source(
                self.primary, "text", status="fallback", reason=_reason_of(exc), answered_by=self.fallback.name,
                elapsed_ms=_ms(started))

    def read_dashboard_traced(self, image: bytes, mime_type: str = "image/svg+xml") -> tuple[DashboardReading, dict]:
        started = time.monotonic()
        try:
            result = self.primary.read_dashboard(image, mime_type)
            return result, make_source(self.primary, "vision", elapsed_ms=_ms(started))
        except Exception as exc:  # noqa: BLE001
            log.warning("Fallo del proveedor de IA al leer la foto (%s); se pedirá el dato al conductor", exc)
            return DashboardReading(), make_source(self.primary, "vision", status="failed", reason=_reason_of(exc),
                                                   elapsed_ms=_ms(started))

    def extract_request(self, text: str, context: dict) -> ExtractedRequest:
        return self.extract_request_traced(text, context)[0]

    def read_dashboard(self, image: bytes, mime_type: str = "image/svg+xml") -> DashboardReading:
        return self.read_dashboard_traced(image, mime_type)[0]


class TextOnlyProvider:
    """Mixed mode of the demo (`groq_text`): a remote provider interprets what the driver writes and
    the photo never leaves the backend.

    The local sample reader answers for the photo and the source says so (provider `mock`, plus the
    mode), so the interface never shows that reading as made by the remote model.
    """

    name = "groq_text"

    def __init__(self, text: SafeProvider, vision: AIProvider) -> None:
        self.text, self.vision = text, vision

    def extract_request_traced(self, text: str, context: dict) -> tuple[ExtractedRequest, dict]:
        return self.text.extract_request_traced(text, context)

    def read_dashboard_traced(self, image: bytes, mime_type: str = "image/svg+xml") -> tuple[DashboardReading, dict]:
        started = time.monotonic()
        result = self.vision.read_dashboard(image, mime_type)
        return result, {**make_source(self.vision, "vision", elapsed_ms=_ms(started)), "mode": self.name}

    def extract_request(self, text: str, context: dict) -> ExtractedRequest:
        return self.extract_request_traced(text, context)[0]

    def read_dashboard(self, image: bytes, mime_type: str = "image/svg+xml") -> DashboardReading:
        return self.read_dashboard_traced(image, mime_type)[0]


def interpret(provider: AIProvider, text: str, context: dict) -> tuple[ExtractedRequest, dict]:
    """Interpretation of a message plus who produced it."""
    traced = getattr(provider, "extract_request_traced", None)
    if traced is not None:
        return traced(text, context)
    started = time.monotonic()
    result = provider.extract_request(text, context)
    return result, make_source(provider, "text", elapsed_ms=_ms(started))


def read_photo(provider: AIProvider, image: bytes, mime_type: str) -> tuple[DashboardReading, dict]:
    """Reading of the dashboard photo plus who produced it."""
    traced = getattr(provider, "read_dashboard_traced", None)
    if traced is not None:
        return traced(image, mime_type)
    started = time.monotonic()
    result = provider.read_dashboard(image, mime_type)
    return result, make_source(provider, "vision", elapsed_ms=_ms(started))


# --------------------------------------------------------------------------- selection and hot switch

_lock = threading.Lock()
_state: dict = {"override": None, "pinned": False}


def groq_available() -> bool:
    return bool(get_settings().groq_api_key)


def configured_provider() -> str:
    """Provider asked for by AI_PROVIDER, or `mock` when it cannot work (no key or model)."""
    settings = get_settings()
    if settings.ai_provider in GROQ_MODES and settings.groq_api_key:
        return settings.ai_provider
    if settings.ai_provider == "gemini" and settings.gemini_api_key and settings.gemini_model:
        return "gemini"
    return "mock"


def active_provider() -> str:
    override = _state["override"]
    if override in GROQ_MODES and not groq_available():
        return "mock"
    return override or configured_provider()


def set_active_provider(name: str, *, pinned: bool = False) -> bool:
    """Switches the provider without restarting. `pinned` keeps it across "Reiniciar demo" (the
    automated tests pin `mock`). Returns whether the active provider changed."""
    if name not in SWITCHABLE:
        raise ValueError(f"proveedor no conmutable: {name}")
    if name in GROQ_MODES and not groq_available():
        raise LookupError("GROQ_API_KEY no está configurada")
    with _lock:
        before = active_provider()
        _state.update(override=name, pinned=pinned)
        return active_provider() != before


def restore_configured_provider(*, force: bool = False) -> bool:
    """Back to the provider of AI_PROVIDER. A pinned provider stays unless `force`."""
    with _lock:
        if _state["pinned"] and not force:
            return False
        before = active_provider()
        _state.update(override=None, pinned=False)
        return active_provider() != before


def ai_state() -> dict:
    """What the interface shows: names only, never the key."""
    settings = get_settings()
    active = active_provider()
    available = groq_available()
    return {
        "active": active,
        "active_label": PROVIDER_LABELS.get(active, active),
        "configured": configured_provider(),
        "pinned": bool(_state["pinned"]),
        "options": [
            {"key": "groq", "label": PROVIDER_LABELS["groq"], "available": available,
             "unavailable_reason": None if available else MISSING_KEY_REASON,
             "text_model": settings.groq_text_model, "vision_model": settings.groq_vision_model},
            # Mixed mode: no vision model, the photo is not sent anywhere.
            {"key": "groq_text", "label": PROVIDER_LABELS["groq_text"], "available": available,
             "unavailable_reason": None if available else MISSING_KEY_REASON,
             "text_model": settings.groq_text_model, "vision_model": None},
            {"key": "mock", "label": PROVIDER_LABELS["mock"], "available": True, "unavailable_reason": None,
             "text_model": None, "vision_model": None},
        ],
    }


@lru_cache(maxsize=8)
def _build(name: str, api_key: str, text_model: str, vision_model: str) -> AIProvider:
    mock = MockProvider()
    try:
        if name in GROQ_MODES:
            from app.integrations.ai.groq import GroqProvider

            safe = SafeProvider(GroqProvider(api_key, text_model, vision_model), mock)
            return TextOnlyProvider(safe, mock) if name == "groq_text" else safe
        if name == "gemini":
            from app.integrations.ai.gemini import GeminiProvider

            return SafeProvider(GeminiProvider(api_key, text_model), mock)
    except Exception as exc:  # noqa: BLE001
        log.error("No se pudo iniciar el proveedor %s (%s): se usa el intérprete local", name, exc.__class__.__name__)
    return mock


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    name = active_provider()
    if name in GROQ_MODES:
        return _build(name, settings.groq_api_key, settings.groq_text_model, settings.groq_vision_model)
    if name == "gemini":
        return _build("gemini", settings.gemini_api_key, settings.gemini_model, settings.gemini_model)
    return _build("mock", "", "", "")


__all__ = ["AIProvider", "DashboardReading", "ExtractedRequest", "GROQ_MODES", "MockProvider", "SafeProvider",
           "TextOnlyProvider", "active_provider", "ai_state", "configured_provider", "get_ai_provider",
           "groq_available", "interpret", "make_source", "read_photo", "restore_configured_provider",
           "set_active_provider", "source_label"]
