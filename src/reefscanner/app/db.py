"""Database engine, session lifecycle, and where the file lives.

Single-user desktop app, so one SQLite file in the OS's per-user data directory
— not in the repo, not next to the footage. Two SQLite details matter here and
both are set on every connection:

* ``check_same_thread=False`` — the job runner writes from a worker thread
  while request handlers read from the event loop's threadpool.
* WAL journal mode — lets those readers proceed while a job is mid-write,
  instead of blocking the UI behind ``database is locked``.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event as sa_event
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from . import models as _models  # noqa: F401 — import registers the tables

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


class Database:
    """Owns one SQLAlchemy engine. Created once per process by the app factory."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else default_db_path()
        if self.path.parent and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False},
        )

        @sa_event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    def create_all(self) -> None:
        """Create missing tables, then add any missing nullable columns.

        Not a migration framework. It handles exactly one kind of change —
        adding a nullable column — because that is what a young schema mostly
        does, and the alternative is telling someone to delete a database full
        of hand-made labels. Drops, renames and type changes still need Alembic;
        this will not attempt them.
        """
        SQLModel.metadata.create_all(self.engine)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        inspector = inspect(self.engine)
        present_tables = set(inspector.get_table_names())

        for table in SQLModel.metadata.sorted_tables:
            if table.name not in present_tables:
                continue  # create_all just made it, so it's already complete
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                # A NOT NULL column can't be added to rows that already exist
                # without a default, so those are left for a real migration.
                if column.name in existing or not column.nullable:
                    continue
                type_sql = column.type.compile(self.engine.dialect)
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            f'ALTER TABLE "{table.name}" '
                            f'ADD COLUMN "{column.name}" {type_sql}'
                        )
                    )
                logger.info("Added column %s.%s", table.name, column.name)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
