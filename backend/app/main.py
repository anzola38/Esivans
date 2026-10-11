"""FastAPI application: modular monolith with the modules of the report.

requests (assistant and request states), ledger (single refuel ledger), rules (rules, traffic
light and amount), decisions (decision, roles and audit log), reconciliation (authorized vs.
recorded) and integrations (providers and AI).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dashboard.router import router as dashboard_router
from app.db import get_db
from app.decisions.audit import ROLE_LABELS, ROLES
from app.decisions.router import router as decisions_router
from app.dev.router import router as dev_router
from app.errors import install_error_handlers
from app.integrations.router import router as integrations_router
from app.ledger.router import router as ledger_router
from app.reconciliation.router import router as alerts_router
from app.requests.router import router as requests_router
from app.rules.repository import rules_version_label
from app.rules.router import router as rules_router
from app.seed import loader
from app.timeutil import iso, now

app = FastAPI(
    title="Suministro de combustible - prototipo",
    description=("Prototipo con datos ilustrativos | Uso exclusivo del proceso de selección. "
                 "Roles simulados con las cabeceras X-Demo-Role y X-Demo-User."),
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
install_error_handlers(app)

api = APIRouter(prefix="/api")


@api.get("/health", tags=["health"], summary="Estado del servicio")
def health(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "service": "esivans-combustible-backend",
        "database": "ok",
        "time": iso(now()),
        "timezone": settings.timezone,
        "ai_provider": settings.ai_provider,
        "demo_mode": settings.demo_mode,
        "seed_date": loader.seed_date(db),
        "rules_version": rules_version_label(db),
        "roles": [{"key": role, "label": ROLE_LABELS[role]} for role in ROLES],
    }


for router in (requests_router, decisions_router, ledger_router, integrations_router, alerts_router, rules_router,
               dashboard_router, dev_router):
    api.include_router(router)
app.include_router(api)
