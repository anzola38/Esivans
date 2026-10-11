"""AI adapter contract. The AI only returns data; the backend validates it and decides.

`extract_request` interprets the driver's message and `read_dashboard` reads the photo of the
dashboard. Both return validated Pydantic models, whatever the provider behind.
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

Intent = Literal["refuel", "status", "greeting", "unknown"]


class ExtractedRequest(BaseModel):
    intent: Intent = "unknown"
    plate: str | None = Field(default=None, description="Placa mencionada por el conductor, si la dice")
    chosen_service: Literal["proposed", "other"] | None = Field(
        default=None, description="Si acepta el servicio propuesto o indica otro")
    confirmation: bool | None = Field(default=None, description="Sí o no a la última pregunta")
    quantity: float | None = Field(default=None, ge=0, description="Cantidad pedida, si la dice")
    quantity_unit: Literal["gal", "m3"] | None = None
    odometer_km: int | None = Field(default=None, ge=0, description="Kilometraje escrito por el conductor")


class ReadingConfidence(BaseModel):
    odometer_km: float = Field(default=0.0, ge=0, le=1)
    fuel_level: float = Field(default=0.0, ge=0, le=1)


class DashboardReading(BaseModel):
    odometer_km: int | None = Field(default=None, ge=0, description="Kilometraje del odómetro")
    fuel_level: float | None = Field(default=None, ge=0, le=1, description="Nivel de combustible entre 0 y 1")
    confidence: ReadingConfidence = Field(default_factory=ReadingConfidence)


class AIProvider(Protocol):
    name: str

    def extract_request(self, text: str, context: dict) -> ExtractedRequest: ...

    def read_dashboard(self, image: bytes, mime_type: str = "image/svg+xml") -> DashboardReading: ...


MIN_CONFIDENCE = 0.6  # below this the driver types the number or the technician reviews the photo
