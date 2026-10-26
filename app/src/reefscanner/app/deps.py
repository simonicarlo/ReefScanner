"""Shared FastAPI dependencies.

The database and job runner are created once by the app factory and stashed on
``app.state``, so these just hand them out. Doing it through the dependency
system (rather than a module global) is what lets the tests spin up an app on a
temporary database without touching the real one.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlmodel import Session

from .db import Database
from .jobs import JobRunner


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def get_session(db: Database = Depends(get_db)) -> Iterator[Session]:
    with db.session() as session:
        yield session
