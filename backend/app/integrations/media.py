"""Local storage that simulates the WhatsApp Media API.

Photos arrive in the webhook as a `media_id`; the handler "downloads" them from this library
and stores a private copy named by its SHA-256 (the evidence keeps path and hash).
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

MIME_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
MEDIA_PREFIX = "media-"


def _library() -> Path:
    return get_settings().seed_media_dir


def media_path(media_id: str) -> Path | None:
    name = media_id.removeprefix(MEDIA_PREFIX)
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    for suffix in MIME_TYPES:
        candidate = _library() / f"{name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def mime_of(path: Path) -> str:
    return MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def media_url(media_id: str | None) -> str | None:
    return f"/api/media/{media_id}" if media_id else None


def download(media_id: str) -> dict | None:
    """Simulates GET /{media-id} + download: returns bytes, MIME type, hash and the stored copy."""
    source = media_path(media_id)
    if source is None:
        return None
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    inbound = get_settings().storage_dir / "media" / "inbound"
    inbound.mkdir(parents=True, exist_ok=True)
    stored = inbound / f"{digest}{source.suffix.lower()}"
    if not stored.exists():
        stored.write_bytes(content)
    return {"content": content, "mime_type": mime_of(source), "sha256": digest,
            "path": str(stored.relative_to(get_settings().storage_dir)).replace("\\", "/")}


@lru_cache
def _readings_by_hash() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for sidecar in sorted(_library().glob("*.json")):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        image = next((sidecar.with_suffix(s) for s in MIME_TYPES if sidecar.with_suffix(s).is_file()), None)
        if image is not None:
            index[hashlib.sha256(image.read_bytes()).hexdigest()] = data
    return index


def reading_for_hash(digest: str) -> dict | None:
    return _readings_by_hash().get(digest)


def reset_cache() -> None:
    _readings_by_hash.cache_clear()
