"""Alembic environment.

Two ways in: the app hands over an open connection (``Database.migrate``), and
the ``alembic`` CLI from ``app/`` gives a URL in ``alembic.ini``.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

# Importing the models registers their tables on SQLModel.metadata.
from reefscanner.app import models as _app_models  # noqa: F401
from reefscanner.core.camtrap import models as _camtrap_models  # noqa: F401

target_metadata = SQLModel.metadata


def run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't ALTER most things in place; batch mode copies the table.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    engine = create_engine(context.config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        run(conn)
