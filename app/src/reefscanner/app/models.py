"""SQLModel tables for the app's own state: projects and scan runs.

What a scan finds and what a reviewer decides live in the Camtrap DP tables
(``reefscanner.core.camtrap.models``), in this same database: media, machine
and human observations, and the sidecar. These tables only add what the app
needs around them.

* A **project** is one Camtrap deployment — a folder of footage from one place
  — plus the config it is scanned with.
* **App settings** hold the one person using this laptop.
* A **job** is one scan run, or one imported package (``source`` set). Its
  observations carry its id as ``scanID``, and its files live in
  ``<output folder>/scan-<id>/``, which is also where its Camtrap DP package
  is written.

The engine's ``Manifest`` remains the resume mechanism for video processing:
"have I finished analysing this file under these settings?".
"""

# NOTE: no ``from __future__ import annotations`` here on purpose. SQLModel
# resolves Relationship targets by evaluating the field annotation at class
# creation, and postponed evaluation turns those into unresolvable strings
# ("expression \"relationship(...)\" seems to be using a generic class").
# Python >= 3.12 is required anyway, so builtin generics work unquoted.

import datetime as _dt
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Text
from sqlmodel import JSON, Field, Relationship, SQLModel

# The Camtrap tables must be registered on the same metadata.
from reefscanner.core.camtrap import models as _camtrap  # noqa: F401

# Job lifecycle.
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
TERMINAL_JOB_STATUSES = (JOB_DONE, JOB_FAILED, JOB_CANCELLED)


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class Project(SQLModel, table=True):
    """A folder of footage from one place, its deployment, and its config."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    #: The Camtrap deployment this project is. Deleted with the project.
    deployment_id: str = Field(foreign_key="deployments.deploymentID", unique=True)
    input_folder: str
    output_folder: str
    #: A full ``ReefScannerConfig.to_dict()``. Stored whole rather than as
    #: columns so adding an engine tunable needs no migration.
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    #: Who made the data and for what, in Camtrap's own shape (``project``,
    #: ``contributors``) so an export copies it as is. See ``metadata.py``.
    package_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: _dt.datetime = Field(default_factory=_utcnow)

    jobs: list["Job"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class AppSettings(SQLModel, table=True):
    """The person using this laptop. A single row (``id`` 1).

    Reviews are signed with ``name``, and new projects start with this person
    as their contributor. Unset, the login name stands in.
    """

    id: int = Field(default=1, primary_key=True)
    name: str | None = None
    email: str | None = None
    organization: str | None = None


class Job(SQLModel, table=True):
    """One scan run over a project's input folder."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    status: str = Field(default=JOB_PENDING, index=True)
    #: 0.0–1.0. Videos are the unit; a long single video moves in fractions of
    #: one video as frames are sampled (see jobs.py).
    progress: float = 0.0
    #: Human-readable "what is it doing right now", surfaced in the UI.
    message: str = ""
    videos_total: int = 0
    videos_done: int = 0
    events_found: int = 0
    started_at: _dt.datetime | None = None
    finished_at: _dt.datetime | None = None
    error: str | None = Field(default=None, sa_column=Column(Text))
    #: The package folder an import run copies from; None for a scan.
    source: str | None = None

    project: Project | None = Relationship(back_populates="jobs")


def scan_id(job_id: int) -> str:
    """The ``scanID`` a job's observations carry."""
    return f"scan-{job_id}"


def run_folder(project: Project, job_id: int) -> Path:
    """Where a run's files and its Camtrap DP package live."""
    return Path(project.output_folder).expanduser() / scan_id(job_id)
