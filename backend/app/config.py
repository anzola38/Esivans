"""Application settings read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent


@dataclass(frozen=True)
class Settings:
    database_url: str
    ai_provider: str
    gemini_api_key: str
    gemini_model: str
    groq_api_key: str
    groq_text_model: str
    groq_vision_model: str
    whatsapp_app_secret: str
    whatsapp_verify_token: str
    demo_mode: bool
    timezone: str
    seed_media_dir: Path
    samples_dir: Path
    storage_dir: Path


def _database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    user = os.getenv("POSTGRES_USER", "esivans")
    password = os.getenv("POSTGRES_PASSWORD", "esivans_demo")
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "esivans")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=_database_url(),
        # mock | groq | groq_text (Groq for the text, sample reading for the photo) | gemini
        ai_provider=(os.getenv("AI_PROVIDER") or "mock").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_text_model=(os.getenv("GROQ_TEXT_MODEL") or "openai/gpt-oss-120b").strip(),
        groq_vision_model=(os.getenv("GROQ_VISION_MODEL") or "qwen/qwen3.8-27b").strip(),
        whatsapp_app_secret=os.getenv("WHATSAPP_APP_SECRET") or "demo-secret",
        whatsapp_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN") or "demo-verify-token",
        demo_mode=(os.getenv("DEMO_MODE") or "true").strip().lower() in {"1", "true", "yes", "si"},
        timezone=os.getenv("TZ") or "America/Bogota",
        seed_media_dir=APP_DIR / "seed" / "media",
        samples_dir=APP_DIR / "seed" / "samples",
        storage_dir=Path(os.getenv("STORAGE_DIR") or (BACKEND_DIR / "storage")),
    )
