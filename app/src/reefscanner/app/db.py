"""Database engine, session lifecycle, and where the file lives.

Single-user desktop app, so one SQLite file in the OS's per-user data directory
— not in the repo, not next to the footage. Two SQLite details matter here and
both are set on every connection:

* ``check_same_thread=False`` — the job runner writes from a worker thread
  while request handlers read from the event loop's threadpool.
* WAL journal mode — lets those readers proceed while a job is mid-write,
  instead of blocking the UI behind ``database is locked``.

The schema is owned by Alembic (``migrations/``) and brought up to date on
every start. After migrating, the tables are compared with the models, and a
mismatch stops the app (``SchemaMismatch``) rather than failing on the first
write. A database can say it is up to date and still differ: one made by a
development build before a migration was rewritten keeps the old tables.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event as sa_event
from sqlmodel import Session, SQLModel, create_engine

from .migrations import alembic_config

logger = logging.getLogger("reefscanner.app.db")

#: Overrides the default location. Used by the tests and by `serve --db`.
DB_PATH_ENV = "REEFSCANNER_DB"


def default_data_dir() -> Path:
    """Per-user application data directory, following each OS's convention."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "ReefScanner"


def default_db_path() -> Path:
    override = os.environ.get(DB_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return default_data_dir() / "reefscanner.db"


class SchemaMismatch(RuntimeError):
    """The database's tables don't match this version's models."""

    def __init__(self, path: Path, differences: list) -> None:
        self.path = path
        self.differences = differences
        shown = "\n".join(f"  - {_describe(d)}" for d in differences[:5])
        more = f"\n  … and {len(differences) - 5} more" if len(differences) > 5 else ""
        super().__init__(
            f"The database at {path} doesn't match this version of ReefScanner, "
            "although it says it is up to date (probably made by an earlier "
            f"development build). To match, it would need to:\n{shown}{more}\n"
            f"Rename {path.name} and its -wal and -shm files, then start again "
            "to get a fresh database."
        )


def _describe(difference: Any) -> str:
    """One Alembic difference in words, e.g. 'add column project.deployment_id'."""
    if isinstance(difference, list):  # a column's changes come grouped
        difference = difference[0]
    op, *items = difference
    names = [
        getattr(item, "name", None) or (item if isinstance(item, str) else None)
        for item in items
    ]
    return f"{op.replace('_', ' ')} {'.'.join(n for n in names if n)}"


class Database:
    """Owns one SQLAlchemy engine. Created once per process by the app factory."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_db_path()
        if self.path.parent and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False},
        )

        @sa_event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record) -> None:  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    def migrate(self) -> None:
        """Bring the schema up to the latest migration. Safe to run every start.

        Raises ``SchemaMismatch`` if the tables still differ from the models.
        """
        cfg = alembic_config()
        with self.engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            differences = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
        if differences:
            raise SchemaMismatch(self.path, differences)
        logger.info("Database at %s is up to date", self.path)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
