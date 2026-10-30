"""Request/response models for the HTTP API.

Separate from the tables on purpose: the wire format shouldn't move every time
a column does, and an "event" here flattens a machine observation, its sidecar
and the human review into one card, because that's how the review UI wants it.

Config is validated by round-tripping through ``ReefScannerConfig`` rather than
being redeclared here — ``from_dict`` already rejects unknown keys and
``validate()`` already enforces the ranges, and duplicating those rules is how
they drift apart.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.camtrap import VERDICTS


def validated_config(data: dict[str, Any]) -> dict[str, Any]:
    """Normalise a config dict via the engine, raising ValueError if invalid."""
    return ReefScannerConfig.from_dict(data).to_dict()


def _require_camera_timezone(v: dict[str, Any]) -> None:
    """A project must say which timezone the camera clock was in.

    File timestamps can't be trusted for it (GoPros label local time as UTC),
    and the laptop's own zone is only a guess, so the UI pre-fills that and
    asks the person to confirm.
    """
    if not v.get("camera_timezone"):
        raise ValueError(
            "camera_timezone is required: the IANA timezone the camera's clock "
            "was set to, e.g. 'Africa/Maputo'"
        )


class DeploymentWrite(BaseModel):
    """Where and how the footage was filmed. Becomes the Camtrap deployment."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: str | None = None
    #: Water depth of the rig, in metres.
    camera_depth: float | None = Field(default=None, ge=0)
    bait_use: bool | None = None
    comments: str | None = None


class DeploymentRead(DeploymentWrite):
    deployment_id: str
    start: _dt.datetime | None = None
    end: _dt.datetime | None = None
    #: True when some video's start time had to be guessed from the file.
    timestamp_issues: bool = False


#: Enough to catch a name typed into the email box; not a full RFC check.
_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class Contributor(BaseModel):
    """A person or organisation behind the data (Camtrap ``contributors``).

    Unknown keys are dropped rather than refused, since packages from other
    tools may carry more (an ORCID ``path``, say) and none of it is needed.
    """

    title: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=200, pattern=_EMAIL)
    organization: str | None = Field(default=None, max_length=200)
    #: The roles Camtrap DP allows.
    role: Literal[
        "contact", "principalInvestigator", "rightsHolder", "publisher", "contributor"
    ] = "contributor"


class ProjectInfo(BaseModel):
    """Camtrap ``project``: the study the data was collected for."""

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)


class PackageMetadata(BaseModel):
    """What an exported package says about who made it and why.

    Shaped as in ``datapackage.json``. Camtrap requires a contributor.
    """

    project: ProjectInfo
    contributors: list[Contributor] = Field(min_length=1, max_length=100)


class SettingsWrite(BaseModel):
    """The person using this laptop."""

    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200, pattern=_EMAIL)
    organization: str | None = Field(default=None, max_length=200)


class SettingsRead(SettingsWrite):
    #: Who reviews are signed as: ``name``, or the login name while unset.
    signed_as: str


class Appearance(BaseModel):
    """How the app looks on this laptop. Separate from the person, so changing
    the mode never resubmits their details."""

    mode: Literal["system", "light", "dark"] = "system"
    translucency: bool = True


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    input_folder: str = Field(min_length=1)
    output_folder: str = Field(min_length=1)
    deployment: DeploymentWrite
    #: Partial or full engine config; unset keys take the engine's defaults,
    #: except camera_timezone, which has to be given.
    config: dict[str, Any]
    #: Defaults to the project's name as title and you as the contributor.
    package_metadata: PackageMetadata | None = None

    @field_validator("config")
    @classmethod
    def _check_config(cls, v: dict[str, Any]) -> dict[str, Any]:
        # input/output folders live on the project, not in the config blob, so
        # they're stripped here and re-attached when a job builds the config.
        v = {k: val for k, val in v.items() if k not in ("input_folder", "output_folder")}
        _require_camera_timezone(v)
        validated_config(v)
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    input_folder: str | None = None
    output_folder: str | None = None
    config: dict[str, Any] | None = None
    package_metadata: PackageMetadata | None = None

    @field_validator("config")
    @classmethod
    def _check_config(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        v = {k: val for k, val in v.items() if k not in ("input_folder", "output_folder")}
        # A config update replaces the stored blob, so it can't drop the zone.
        _require_camera_timezone(v)
        validated_config(v)
        return v


class RunSummary(BaseModel):
    """Where a project's review stands: its latest run with events.

    One run rather than a sum over runs, because rescans of the same footage
    find the same animals again.
    """

    job_id: int
    events: int
    reviewed: int
    confirmed: int
    #: "Nothing there" and "something else" together.
    rejected: int
    #: The frame that stands for the project: its most recent confirmed event,
    #: otherwise its first event.
    cover_url: str | None


class ProjectRead(BaseModel):
    id: int
    name: str
    input_folder: str
    output_folder: str
    config: dict[str, Any]
    created_at: _dt.datetime
    job_count: int = 0
    latest_run: RunSummary | None = None
    package_metadata: PackageMetadata
    deployment: DeploymentRead


class ProjectImport(BaseModel):
    """A Camtrap DP package folder to import as a new project."""

    package_folder: str = Field(min_length=1)
    #: Where the import run copies the package's clips and frames.
    output_folder: str = Field(min_length=1)
    #: Defaults to the deployment's location name, or its ID.
    name: str | None = Field(default=None, min_length=1, max_length=200)


class JobRead(BaseModel):
    id: int
    project_id: int
    status: str
    progress: float
    message: str
    videos_total: int
    videos_done: int
    events_found: int
    started_at: _dt.datetime | None = None
    finished_at: _dt.datetime | None = None
    error: str | None = None
    #: The package folder an import run came from; None for a scan.
    source: str | None = None


def _check_relative_bbox(v: list[float] | None) -> list[float] | None:
    if v is None:
        return v
    if len(v) != 4:
        raise ValueError("bbox must be [x, y, width, height]")
    x, y, w, h = v
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
        raise ValueError("bbox values are fractions of the frame, from 0 to 1")
    return v


class ReviewWrite(BaseModel):
    """A human verdict on an event. Posting again revises it, never duplicates.

    ``scientific_name`` is the species for a TP, and what it was instead for an
    FP-other; ``bbox`` is a corrected box, relative to the frame.
    """

    verdict: str
    scientific_name: str | None = None
    notes: str | None = None
    bbox: list[float] | None = None

    @field_validator("verdict")
    @classmethod
    def _check_verdict(cls, v: str) -> str:
        if v not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}")
        return v

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, v: list[float] | None) -> list[float] | None:
        return _check_relative_bbox(v)


class ReviewRead(BaseModel):
    verdict: str
    scientific_name: str | None = None
    notes: str | None = None
    bbox: list[float] | None = None
    reviewed_at: _dt.datetime | None = None


class EventRead(BaseModel):
    """One reviewable event: the machine observation, its context, its review."""

    #: The Camtrap ``eventID``. Contains ``:``, never ``/``.
    id: str
    job_id: int
    source_video: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    peak_seconds: float
    #: Wall-clock start, in the camera's timezone.
    start_time: _dt.datetime
    confidence: float | None = None
    detected_class: str | None = None
    scientific_name: str | None = None
    #: The detector's box at the peak frame, relative to the frame (0 to 1).
    bbox: list[float] | None = None
    #: URLs served by the media router, not filesystem paths — the UI must not
    #: need to know where on disk the output folder is.
    clip_url: str
    frame_url: str
    review: ReviewRead | None = None


class EventPage(BaseModel):
    """A page of events plus the totals the UI shows above the grid."""

    items: list[EventRead]
    total: int
    limit: int
    offset: int
    n_labeled: int
    n_tp: int
    #: False positives of either kind (nothing there, or something else).
    n_fp: int
