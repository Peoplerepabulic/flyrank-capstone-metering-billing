"""Database setup: engine, session factory, and a tiny SQL migrator.

Schema is versioned as migrations/*.sql applied in order at startup
("schema as migrations"). Works with SQLite (default, $0) and Postgres
via DATABASE_URL.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./metering.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migrations() -> list[str]:
    """Apply pending migrations in filename order. Returns applied versions."""
    applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL "
            "DEFAULT (datetime('now')))"
        ))
        done = {r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            sql = path.read_text()
            for statement in [s.strip() for s in sql.split(";") if s.strip()]:
                conn.execute(text(statement))
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                         {"v": version})
            applied.append(version)
    return applied


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
