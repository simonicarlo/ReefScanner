"""Alembic owns the schema: the app migrates its database on every start."""

from __future__ import annotations

import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlmodel import SQLModel

from reefscanner.app.db import Database, SchemaMismatch
from reefscanner.app.main import create_app
from reefscanner.app.migrations import alembic_config


def _tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {r[0] for r in rows}
    finally:
        conn.close()


def _revision(path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()


def test_fresh_database_is_migrated_to_head(tmp_path) -> None:
    db = Database(tmp_path / "fresh.db")
    db.migrate()
    db.dispose()

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert _revision(tmp_path / "fresh.db") == head
    assert {
        "project", "job",
        "deployments", "media", "observations",
        "reefscanner_observations", "reefscanner_detections",
    } <= _tables(tmp_path / "fresh.db")


def test_migrate_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "x.db")
    db.migrate()
    db.migrate()  # every start runs it; the second run must be a no-op
    db.dispose()


def test_models_and_migrations_agree(tmp_path) -> None:
    """Fails when a model changes without a migration.

    Fix by writing one from app/: uv run alembic revision --autogenerate -m "..."
    """
    db = Database(tmp_path / "x.db")
    db.migrate()
    with db.engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
    db.dispose()
    assert diff == [], f"models differ from migrations: {diff}"


def test_migrations_downgrade_cleanly(tmp_path) -> None:
    db = Database(tmp_path / "x.db")
    db.migrate()
    cfg = alembic_config()
    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    db.dispose()
    assert _tables(tmp_path / "x.db") == {"alembic_version"}


def test_a_database_that_differs_from_the_models_stops_the_app(tmp_path) -> None:
    """It can say it is up to date and still differ: one made by a development
    build before migration 0001 was rewritten kept its old tables, and the
    first project failed with a 500 instead of the app saying why."""
    path = tmp_path / "stale.db"
    db = Database(path)
    db.migrate()
    db.dispose()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE label (id INTEGER PRIMARY KEY)")  # a v2 leftover
    conn.commit()
    conn.close()

    with pytest.raises(SchemaMismatch, match="stale.db") as exc:
        create_app(db_path=path)
    assert "label" in str(exc.value)
