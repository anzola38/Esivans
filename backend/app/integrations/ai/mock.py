"""Deterministic AI provider (default): the demo never depends on the internet.

Text is interpreted with simple rules and every sample photo has its reading in a JSON file
next to it, matched by the SHA-256 of the image.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from app.integrations.ai.base import DashboardReading, ExtractedRequest
from app.integrations.media import reading_for_hash

YES = ("si", "correcto", "confirmo", "confirmado", "ok", "dale", "listo", "claro", "de acuerdo", "asi es",
       "es para esa", "entendido")
NO = ("no", "incorrecto", "corregir", "esta mal", "negativo")
# Whole words only (see _starts_or_contains): a stem such as "ya me autoriz" would never match.
STATUS = ("estado", "como va", "como vamos", "ya me autorizaron", "ya me autorizo", "ya autorizaron", "ya autorizo",
          "que paso con", "novedad", "consulta")
REFUEL = ("tanque", "tanquear", "combustible", "gasolina", "diesel", "acpm", "gas", "cargar", "llenar", "recarga")
GREETING = ("hola", "buenos dias", "buenas tardes", "buenas noches", "buenas")

_QUANTITY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(m3|m³|metros cubicos|metros|galones|galon|gal)\b")
_ODOMETER = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.\s]\d{3})+|\d{4,7})(?![\d])")
_PLATE = re.compile(r"\b([a-z]{3})[\s-]?(\d{3})\b")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def _starts_or_contains(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text) for w in words)


class MockProvider:
    name = "mock"

    def extract_request(self, text: str, context: dict) -> ExtractedRequest:
        clean = normalize(text or "")
        data: dict = {"intent": "unknown"}

        quantity = _QUANTITY.search(clean)
        if quantity:
            data["quantity"] = float(quantity.group(1).replace(",", "."))
            data["quantity_unit"] = "m3" if quantity.group(2).startswith("m") else "gal"
        without_quantity = _QUANTITY.sub(" ", clean)

        odometer = _ODOMETER.search(without_quantity)
        if odometer:
            data["odometer_km"] = int(re.sub(r"[.\s]", "", odometer.group(1)))

        plate = _PLATE.search(clean)
        if plate:
            data["plate"] = (plate.group(1) + plate.group(2)).upper()

        first = clean.split(",")[0].split(".")[0].strip()
        if re.match(r"^(no)\b", clean) or _starts_or_contains(first, NO[1:]):
            data["confirmation"] = False
        elif re.match(r"^(si)\b", clean) or _starts_or_contains(first, YES[1:]):
            data["confirmation"] = True

        if "otro" in clean and ("servicio" in clean or "recorrido" in clean or "ruta" in clean):
            data["chosen_service"] = "other"
            data["confirmation"] = False
        elif data.get("confirmation") and ("ruta" in clean or "servicio" in clean):
            data["chosen_service"] = "proposed"

        if _starts_or_contains(clean, STATUS):
            data["intent"] = "status"
        elif _starts_or_contains(clean, REFUEL):
            data["intent"] = "refuel"
        elif _starts_or_contains(clean, GREETING):
            data["intent"] = "greeting"
        return ExtractedRequest.model_validate(data)

    def read_dashboard(self, image: bytes, mime_type: str = "image/svg+xml") -> DashboardReading:
        reading = reading_for_hash(hashlib.sha256(image).hexdigest())
        if reading is None:  # unknown photo: zero confidence, the assistant asks the driver to type the km
            return DashboardReading()
        return DashboardReading.model_validate({
            "odometer_km": reading.get("odometer_km"),
            "fuel_level": reading.get("fuel_level"),
            "confidence": reading.get("confidence", {}),
        })
