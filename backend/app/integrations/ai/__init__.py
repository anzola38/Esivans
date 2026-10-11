"""AI adapter factory. Any failure of the optional provider falls back to the deterministic one."""
from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.integrations.ai.base import AIProvider, DashboardReading, ExtractedRequest
from app.integrations.ai.mock import MockProvider

log = logging.getLogger(__name__)


class SafeProvider:
    """Wraps a remote provider: if it fails, the mock answers and the flow continues."""

    def __init__(self, primary: AIProvider, fallback: AIProvider) -> None:
        self.primary, self.fallback = primary, fallback
        self.name = primary.name

    def extract_request(self, text: str, context: dict) -> ExtractedRequest:
        try:
            return self.primary.extract_request(text, context)
        except Exception:  # noqa: BLE001
            log.exception("Fallo del proveedor de IA al interpretar el texto; se usa el interpretador local")
            return self.fallback.extract_request(text, context)

    def read_dashboard(self, image: bytes, mime_type: str = "image/svg+xml") -> DashboardReading:
        try:
            return self.primary.read_dashboard(image, mime_type)
        except Exception:  # noqa: BLE001
            log.exception("Fallo del proveedor de IA al leer la foto; se pedirá el dato al conductor")
            return DashboardReading()


@lru_cache
def get_ai_provider() -> AIProvider:
    settings = get_settings()
    mock = MockProvider()
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key or not settings.gemini_model:
            log.warning("AI_PROVIDER=gemini sin GEMINI_API_KEY o GEMINI_MODEL: se usa el proveedor mock")
            return mock
        try:
            from app.integrations.ai.gemini import GeminiProvider

            return SafeProvider(GeminiProvider(settings.gemini_api_key, settings.gemini_model), mock)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo iniciar Gemini: se usa el proveedor mock")
    return mock


__all__ = ["AIProvider", "DashboardReading", "ExtractedRequest", "MockProvider", "get_ai_provider"]
