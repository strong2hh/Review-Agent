from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations() -> None:
    """Ensure new columns/tables exist for existing SQLite deployments without Alembic."""
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        if not _table_exists(conn, "settings"):
            return

        _ensure_column(conn, "settings", "question_provider", "question_provider VARCHAR(50) DEFAULT 'mock'")
        _ensure_column(conn, "settings", "question_model", "question_model VARCHAR(100) DEFAULT 'mock-q-v1'")
        _ensure_column(conn, "settings", "grading_provider", "grading_provider VARCHAR(50) DEFAULT 'mock'")
        _ensure_column(conn, "settings", "grading_model", "grading_model VARCHAR(100) DEFAULT 'mock-g-v1'")

        conn.execute(
            text(
                """
                UPDATE settings
                SET grading_provider = COALESCE(NULLIF(grading_provider, ''), NULLIF(model_provider, ''), 'mock'),
                    grading_model = COALESCE(NULLIF(grading_model, ''), NULLIF(model_name, ''), 'mock-g-v1'),
                    question_provider = COALESCE(NULLIF(question_provider, ''), 'mock'),
                    question_model = COALESCE(NULLIF(question_model, ''), 'mock-q-v1')
                """
            )
        )


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return row is not None


def _table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {str(r[1]) for r in rows}


def _ensure_column(conn, table_name: str, column_name: str, full_definition: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {full_definition}"))
