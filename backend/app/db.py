"""Database engine and session. SQLite now; change DATABASE_URL for PostgreSQL."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

is_sqlite = settings.db_url.startswith("sqlite")
if is_sqlite:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
# check_same_thread is a SQLite-only option (FastAPI uses several threads).
engine = create_engine(
    settings.db_url, connect_args={"check_same_thread": False} if is_sqlite else {}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Use in a route:  def my_route(db: DbSession): ...
DbSession = Annotated[Session, Depends(get_db)]


def init_db() -> None:
    """Create all tables that do not exist yet."""
    from app import models  # noqa: F401  (registers the tables on Base)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Small dev helper: when a new column is added to a model, add it to the existing table.

    create_all() only creates missing tables, not missing columns. New columns are added
    as nullable. (For bigger changes later, use a real migration tool like Alembic.)
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing:
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(
                        text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
                    )
