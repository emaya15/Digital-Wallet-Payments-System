"""Integration fixtures. They need a reachable MySQL TEST database.

The schema is created ONLY by running the real Alembic migration (never create_all).
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import settings
from app.database import engine

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _alembic_config() -> Config:
    cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(PROJECT_ROOT, "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    assert settings.is_test, "Integration tests must run with APP_ENV=test"
    assert "test" in settings.database_url.rsplit("/", 1)[-1], "Refusing to run against a database whose name has no 'test' in it"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"MySQL test database is not reachable ({exc.__class__.__name__}); set TEST_DATABASE_URL", allow_module_level=False)
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(migrated_database):
    from app.services.ledger_service import ensure_system_accounts
    from app.database import SessionLocal
    from app.utils import email as email_utils

    with engine.begin() as connection:
        connection.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        tables = [r[0] for r in connection.execute(text("SHOW TABLES"))]
        for table in tables:
            if table != "alembic_version":
                connection.execute(text(f"TRUNCATE TABLE `{table}`"))
        connection.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    with SessionLocal() as db:
        ensure_system_accounts(db)
    email_utils.OUTBOX.clear()
    yield


@pytest.fixture(scope="session")
def client(migrated_database):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def outbox():
    from app.utils import email as email_utils

    return email_utils.OUTBOX
