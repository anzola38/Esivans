"""Container entry point: wait for PostgreSQL, migrate, seed if needed and serve."""
from __future__ import annotations

import logging
import time

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.config import BACKEND_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app.start")


def wait_for_db(retries: int = 60) -> None:
    from app.db import engine

    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 - startup retry
            log.info("Esperando la base de datos (%s/%s): %s", attempt, retries, exc.__class__.__name__)
            time.sleep(1)
    raise SystemExit("La base de datos no respondió")


def migrate() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


def main() -> None:
    wait_for_db()
    migrate()
    from app.db import SessionLocal
    from app.seed.loader import ensure_seed

    with SessionLocal() as db:
        log.info("Semilla: %s", ensure_seed(db))
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
