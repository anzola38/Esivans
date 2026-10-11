"""Uniform API errors: {"detail": "<mensaje en español>", "code": "<codigo>", ...extra}."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, code: str = "error", extra: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.extra = extra or {}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code, **exc.extra})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail), "code": "http_error"})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")}
                  for e in exc.errors()]
        fields = ", ".join(e["field"] for e in errors if e["field"]) or "cuerpo de la petición"
        return JSONResponse(status_code=422, content={
            "detail": f"Datos inválidos: revisa {fields}.", "code": "validation_error", "errors": errors})
