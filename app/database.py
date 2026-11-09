"""SQLAlchemy engine, session factory and declarative base.

Tables are created ONLY through Alembic migrations (never `create_all`).
READ COMMITTED isolation is used so that locking reads (`SELECT ... FOR UPDATE`)
and the limit / fraud aggregate queries that follow them always see the latest
committed rows.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=1800,
    isolation_level="READ COMMITTED",
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
