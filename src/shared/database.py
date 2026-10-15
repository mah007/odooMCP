"""SQLAlchemy engine and session factory for shared SQLite database."""

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parents[2] / "data" / "mcp.db"))
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after v2, as (table, column, DDL). There is no Alembic: init_db() adds the
# missing ones in place. Defaults are chosen so existing rows keep their v2 behaviour.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("odoo_connections", "api_mode", "VARCHAR(10) NOT NULL DEFAULT 'auto'"),
    # v2 never verified certificates; keep that for existing rows (new rows default to True)
    ("odoo_connections", "verify_ssl", "BOOLEAN NOT NULL DEFAULT 0"),
    ("odoo_connections", "timeout", "INTEGER NOT NULL DEFAULT 120"),
    ("odoo_connections", "default_context", "TEXT"),
    ("odoo_connections", "detected_version", "VARCHAR(50)"),
    ("odoo_connections", "detected_mode", "VARCHAR(10)"),
    ("odoo_connections", "last_test_steps", "TEXT"),
    ("odoo_connections", "updated_at", "DATETIME"),
    ("api_keys", "scope", "VARCHAR(10) NOT NULL DEFAULT 'write'"),
    ("request_logs", "response_bytes", "INTEGER"),
    ("request_logs", "transport", "VARCHAR(10)"),
]


def migrate(bind: Engine) -> list[str]:
    """Add missing v3 columns to an existing database. Returns the columns added."""
    added = []
    with bind.begin() as conn:
        for table, column, ddl in MIGRATIONS:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if column in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                added.append(f"{table}.{column}")
            except OperationalError as exc:
                # Both services run init_db() at start-up; the other one may have won the race.
                if "duplicate column" not in str(exc):
                    raise
        if "odoo_connections.updated_at" in added:
            conn.execute(text("UPDATE odoo_connections SET updated_at = created_at WHERE updated_at IS NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_key_prefix ON api_keys (key_prefix)"))
    return added


def init_db(bind: Engine | None = None) -> None:
    from src.shared import models  # noqa: F401 — ensures models are registered
    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    migrate(bind)
