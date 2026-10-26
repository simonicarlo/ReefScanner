"""SQLModel tables — the app's state store.

Division of responsibility with the engine (deliberate, don't collapse it):

* The engine's ``Manifest`` remains the resume mechanism for *video processing*
  — "have I finished analysing this file?". It lives in the output folder next
  to the clips it describes, so a results folder stays self-describing even if
  the database is thrown away.
* This database owns *app* state — projects, job history, and above all the
  human labels, which the engine knows nothing about.

``reefscanner_results.csv`` stops being the source of truth here and becomes an
export format; ``exports.py`` reads and writes it so runs from v1 aren't
orphaned.
"""

# NOTE: no ``from __future__ import annotations`` here on purpose. SQLModel
# resolves Relationship targets by evaluating the field annotation at class
# creation, and postponed evaluation turns those into unresolvable strings
# ("expression \"relationship(...)\" seems to be using a generic class").
# Python >= 3.10 is required anyway, so builtin generics work unquoted.

import datetime as _dt
from typing import Any, List, Optional

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import JSON, Field, Relationship, SQLModel

# Label verdicts. Deliberately three-valued: an event nobody has looked at yet
# has *no* Label row at all, which is different from one a human looked at and
# couldn't call (``unsure``).
VERDICT_TP = "TP"
VERDICT_FP = "FP"
VERDICT_UNSURE = "unsure"
VALID_VERDICTS = (VERDICT_TP, VERDICT_FP, VERDICT_UNSURE)

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
    """A folder of footage plus the config used to analyse it."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    input_folder: str
    output_folder: str
    #: A full ``ReefScannerConfig.to_dict()``. Stored whole rather than as
    #: columns so adding an engine tunable needs no migration.
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: _dt.datetime = Field(default_factory=_utcnow)

    jobs: List["Job"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Job(SQLModel, table=True):
    """One run of the engine over a project's input folder."""

    id: Optional[int] = Field(default=None, primary_key=True)
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
    started_at: Optional[_dt.datetime] = None
    finished_at: Optional[_dt.datetime] = None
    error: Optional[str] = Field(default=None, sa_column=Column(Text))

    project: Optional[Project] = Relationship(back_populates="jobs")
    events: List["Event"] = Relationship(
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Event(SQLModel, table=True):
    """A detected moment — mirrors ``core.events.Event`` plus output paths.

    ``event_id`` is the engine's own id (``<video-stem>_<seq>``), unique only
    within a job, hence the composite constraint rather than a primary key.
    """

    __table_args__ = (UniqueConstraint("job_id", "event_id", name="uq_event_job_eid"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    event_id: str = Field(index=True)
    source_video: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float = 0.0
    peak_timestamp: float = 0.0
    peak_score: float = 0.0
    #: ``[x, y, w, h]`` at the peak frame, in original video resolution.
    peak_bbox: Optional[list[int]] = Field(default=None, sa_column=Column(JSON))
    motion_score: Optional[float] = None
    ml_confidence: Optional[float] = None
    detected_class: Optional[str] = Field(default=None, index=True)
    #: Wall-clock ISO time of the event start, "" when the video has no
    #: creation-time metadata.
    start_timestamp: str = ""
    #: Source video resolution — the coordinate space ``peak_bbox`` lives in.
    #: Recorded at ingest so the annotation exporters don't have to reopen
    #: media just to normalise a box. Null for events imported from a v1 CSV.
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    clip_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    #: Clean peak frame with no annotation — what the exporters reference.
    #: Null for events scanned before clean frames existed.
    frame_path: Optional[str] = None

    job: Optional[Job] = Relationship(back_populates="events")
    label: Optional["Label"] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )


class Label(SQLModel, table=True):
    """A human's verdict on an event — the point of the whole app.

    One row per event (upserted, not appended): the current opinion is what
    matters, and an audit trail of a solo researcher changing their mind isn't
    worth the complexity. ``tight_bbox`` is optional and only set when someone
    corrects the engine's box, which is what makes these rows usable as
    fine-tuning data later.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", unique=True, index=True)
    verdict: str = Field(index=True)
    species: Optional[str] = Field(default=None, index=True)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    #: ``[x, y, w, h]`` — a human-corrected box, original resolution.
    tight_bbox: Optional[list[int]] = Field(default=None, sa_column=Column(JSON))
    updated_at: _dt.datetime = Field(default_factory=_utcnow)

    event: Optional[Event] = Relationship(back_populates="label")
