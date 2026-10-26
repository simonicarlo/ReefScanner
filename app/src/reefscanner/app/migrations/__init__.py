"""Alembic migrations for the app database.

The app runs ``upgrade head`` on every start (``Database.migrate``), so a user
never runs Alembic by hand. Developers write new revisions from ``app/``:

    uv run alembic revision --autogenerate -m "what changed"

then read the generated file before committing it; autogenerate misses some
changes (renames, SQLite constraint tweaks) and the review is the safeguard.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

SCRIPT_LOCATION = Path(__file__).parent


def alembic_config() -> Config:
    """Config pointing at these scripts, independent of the working directory."""
    cfg = Config()
    cfg.set_main_option("script_location", str(SCRIPT_LOCATION))
    return cfg
