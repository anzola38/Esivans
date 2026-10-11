"""Test setup: a separate database (`<db>_test`) in the same PostgreSQL, migrated with Alembic and
seeded, so the demo data of the running application is never touched."""
from __future__ import annotations

import os

import psycopg
import pytest

_USER = os.getenv("POSTGRES_USER", "esivans")
_PASSWORD = os.getenv("POSTGRES_PASSWORD", "esivans_demo")
_HOST = os.getenv("POSTGRES_HOST", "db")
_PORT = os.getenv("POSTGRES_PORT", "5432")
_NAME = os.getenv("POSTGRES_DB", "esivans")
TEST_DB = f"{_NAME}_test"

os.environ["DATABASE_URL"] = f"postgresql+psycopg://{_USER}:{_PASSWORD}@{_HOST}:{_PORT}/{TEST_DB}"
os.environ["AI_PROVIDER"] = "mock"
os.environ["DEMO_MODE"] = "true"
os.environ["WHATSAPP_APP_SECRET"] = "test-secret"
os.environ["STORAGE_DIR"] = "/tmp/esivans-test-storage"


def _recreate_database() -> None:
    with psycopg.connect(host=_HOST, port=_PORT, user=_USER, password=_PASSWORD, dbname=_NAME, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')


@pytest.fixture(scope="session")
def app_ready():
    _recreate_database()
    from app.start import migrate

    migrate()
    from app.db import SessionLocal
    from app.seed.loader import reset_and_load

    with SessionLocal() as db:
        reset_and_load(db)
    yield


@pytest.fixture()
def db(app_ready):
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture()
def client(app_ready):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def fresh(client):
    """Reloads the seed before a test that walks a full flow."""
    assert client.post("/api/dev/reset").status_code == 200
    return client
