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


def test_released_migrations_are_unchanged() -> None:
    """A released migration has already run on someone's database, so editing
    it would leave theirs different from a fresh one. Change the schema with a
    new revision instead. set_version.sh locks new ones at each release."""
    import hashlib

    from reefscanner.app.migrations import SCRIPT_LOCATION

    lock = SCRIPT_LOCATION / "released.txt"
    for line in lock.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, rel = line.split(maxsplit=1)
        path = SCRIPT_LOCATION / rel
        assert path.exists(), f"released migration {rel} was removed"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == digest, f"released migration {rel} was edited"


def _backups(tmp_path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir() if ".bak-" in p.name)


def test_fresh_and_up_to_date_databases_are_not_backed_up(tmp_path) -> None:
    db = Database(tmp_path / "x.db")
    db.migrate()
    db.migrate()
    db.dispose()
    assert _backups(tmp_path) == []


def test_database_is_backed_up_before_a_pending_migration(tmp_path, monkeypatch) -> None:
    """An update migrates someone's only copy of their reviews; keep the old one."""
    import shutil

    from reefscanner.app import db as db_module
    from reefscanner.app.migrations import SCRIPT_LOCATION

    path = tmp_path / "x.db"
    db = Database(path)
    db.migrate()
    with db.session() as session:
        session.connection().exec_driver_sql(
            "INSERT INTO appsettings (id, name, appearance_mode, translucency) "
            "VALUES (1, 'Reef A', 'system', 1)"
        )
        session.commit()
    db.dispose()
    before = _revision(path)

    # The same scripts plus one new, empty revision on top.
    scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPT_LOCATION, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "versions" / "9999_next.py").write_text(
        f"revision = '9999'\ndown_revision = {before!r}\n"
        "branch_labels = None\ndepends_on = None\n"
        "def upgrade():\n    pass\n"
        "def downgrade():\n    pass\n"
    )

    def config():
        cfg = alembic_config()
        cfg.set_main_option("script_location", str(scripts))
        return cfg

    monkeypatch.setattr(db_module, "alembic_config", config)
    db = Database(path)
    db.migrate()
    db.dispose()

    assert _revision(path) == "9999"
    assert _backups(tmp_path) == [f"x.db.bak-{before}"]
    conn = sqlite3.connect(tmp_path / f"x.db.bak-{before}")
    try:
        assert conn.execute("SELECT name FROM appsettings").fetchall() == [("Reef A",)]
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == before
    finally:
        conn.close()


def test_running_from_source_keeps_its_database_apart_from_the_installed_app(
    tmp_path, monkeypatch
) -> None:
    """A development build may carry migrations no release has yet. Sharing
    the installed app's database would migrate it past what that app knows,
    and the app would then refuse to start."""
    import sys

    from reefscanner.app.db import DB_PATH_ENV, default_db_path

    monkeypatch.delenv(DB_PATH_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    monkeypatch.delattr(sys, "frozen", raising=False)
    from_source = default_db_path()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    installed = default_db_path()

    assert from_source.parent.name == "ReefScanner Dev"
    assert installed.parent.name == "ReefScanner"
    assert from_source.parent.parent == installed.parent.parent  # side by side

    monkeypatch.setenv(DB_PATH_ENV, str(tmp_path / "chosen.db"))
    assert default_db_path() == tmp_path / "chosen.db"  # an explicit path wins
