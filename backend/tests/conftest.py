"""Test setup: a separate database (`<db>_test`) in the same PostgreSQL, migrated with Alembic and
seeded, so the demo data of the running application is never touched."""
from __future__ import annotations

import os
from datetime import timedelta

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
# The container may carry a real key: the suite never calls the service. Only the optional live test
# (RUN_LIVE_AI=1) reads the key kept here; every other test sees an empty one.
LIVE_GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()
os.environ["GROQ_API_KEY"] = ""
os.environ["DEMO_MODE"] = "true"
os.environ["WHATSAPP_APP_SECRET"] = "test-secret"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"
os.environ["STORAGE_DIR"] = "/tmp/esivans-test-storage"


def _recreate_database() -> None:
    with psycopg.connect(host=_HOST, port=_PORT, user=_USER, password=_PASSWORD, dbname=_NAME, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        # A test that leaves a read transaction open before "Reiniciar demo" must fail, not hang forever.
        conn.execute(f"""ALTER DATABASE "{TEST_DB}" SET lock_timeout = '20s'""")
        # Only for this throwaway database: do not wait for the disk on every commit (the suite commits thousands of times).
        conn.execute(f"""ALTER DATABASE "{TEST_DB}" SET synchronous_commit = off""")


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


class PristineState:
    """State right after "Reiniciar demo", kept as a copy inside the test database.

    Loading the seed through the ORM takes about 0.7 s; hundreds of tests start from that state, so the
    first one resets through the real endpoint and copies every table to the `pristine` schema, and the
    following ones restore that copy (about 0.1 s). `POST /api/dev/reset` itself has its own tests.
    """

    SCHEMA = "pristine"

    def __init__(self) -> None:
        self.seed_date: str | None = None

    @staticmethod
    def _tables() -> list:
        from app.models import Base

        return list(Base.metadata.sorted_tables)

    def restore(self, client) -> None:
        from app.db import engine
        from app.timeutil import today

        if self.seed_date != today().isoformat():      # first use, or the day changed while the suite ran
            assert client.post("/api/dev/reset").status_code == 200
            self._copy(engine)
            self.seed_date = today().isoformat()
            return
        tables = self._tables()
        names = ", ".join(f'public."{t.name}"' for t in tables)
        with engine.begin() as conn:
            conn.exec_driver_sql(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
            for table in tables:        # parents first: the order respects the foreign keys
                conn.exec_driver_sql(f'INSERT INTO public."{table.name}" SELECT * FROM {self.SCHEMA}."{table.name}"')
            for table in tables:        # sequences continue after the copied rows; empty tables start again at 1
                if "id" in table.c:
                    conn.exec_driver_sql(
                        f"""SELECT setval(pg_get_serial_sequence('public."{table.name}"', 'id'), """
                        f"""COALESCE(max(id), 1), max(id) IS NOT NULL) FROM public."{table.name}" """)

    def _copy(self, engine) -> None:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {self.SCHEMA} CASCADE")
            conn.exec_driver_sql(f"CREATE SCHEMA {self.SCHEMA}")
            for table in self._tables():
                conn.exec_driver_sql(f'CREATE TABLE {self.SCHEMA}."{table.name}" AS TABLE public."{table.name}"')


_pristine = PristineState()


@pytest.fixture()
def fresh(client):
    """Starts the test from the state "Reiniciar demo" leaves: seed loaded, empty queue, rules v1."""
    _pristine.restore(client)
    return client


class FakeClock:
    """Moves the clock of the whole application without sleeping.

    Every module reads the time through `app.timeutil.now()`, which calls `datetime.now(...)`
    on the name bound in that module. Replacing that name with a proxy shifts the time for
    the API, the conversation, the SLA, the seed and the SQLAlchemy defaults at once.
    """

    def __init__(self, monkeypatch) -> None:
        from app import timeutil

        self.offset = timedelta(0)
        real = timeutil.datetime
        clock = self

        class _DatetimeProxy:
            def __getattr__(self, name):
                return getattr(real, name)

            def __call__(self, *args, **kwargs):
                return real(*args, **kwargs)

            def now(self, tz=None):
                return real.now(tz) + clock.offset

        monkeypatch.setattr(timeutil, "datetime", _DatetimeProxy())

    def advance(self, **delta) -> None:
        self.offset += timedelta(**delta)


@pytest.fixture()
def clock(monkeypatch, app_ready):
    """Controllable clock. A test that moves to another day reloads the seed itself
    (`/api/dev/reset`); the next test starts again from `fresh`."""
    return FakeClock(monkeypatch)
