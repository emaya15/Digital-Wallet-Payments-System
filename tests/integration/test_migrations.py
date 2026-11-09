"""The hand-written Alembic migration must match the SQLAlchemy models exactly."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.database import Base, engine
import app.models  # noqa: F401


def test_migration_creates_every_model_table():
    tables = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)
    assert expected <= tables, expected - tables
    assert "alembic_version" in tables


def test_models_and_migration_have_no_drift():
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], diff
