"""Provider imports (CSV) and the simulated Media API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.decisions.audit import Actor, require_roles
from app.errors import ApiError
from app.integrations import media
from app.reconciliation import service as reconciliation

router = APIRouter(tags=["integrations"])


@router.post("/integrations/{provider}/imports",
             summary="Cargar un CSV del proveedor al libro único (idempotente por hash de transacción)")
async def import_transactions(provider: str, request: Request, db: Session = Depends(get_db),
                              actor: Actor = Depends(require_roles("finance", "coordinator", "technician"))) -> dict:
    """Accepts multipart (`file`), JSON (`{"filename": ..., "content": "<csv>"}`) or the raw CSV (text/csv)."""
    content_type = (request.headers.get("content-type") or "").lower()
    filename: str | None = None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ApiError(422, "Adjunta el archivo CSV en el campo 'file'.", "file_required")
        raw = await upload.read()
        filename = getattr(upload, "filename", None)
    elif content_type.startswith("application/json"):
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("content"), str):
            raise ApiError(422, "Envía {\"filename\": ..., \"content\": \"<csv>\"}.", "content_required")
        raw, filename = body["content"].encode("utf-8"), body.get("filename")
    else:
        raw = await request.body()
        filename = request.headers.get("x-filename")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return reconciliation.import_csv(db, provider, text, filename, actor)


@router.get("/media/{media_id}", summary="Foto por media_id (simula la Media API)")
def get_media(media_id: str) -> FileResponse:
    path = media.media_path(media_id)
    if path is None:
        raise ApiError(404, f"No existe la foto {media_id}.", "media_not_found")
    return FileResponse(path, media_type=media.mime_of(path), headers={"Cache-Control": "no-cache"})
