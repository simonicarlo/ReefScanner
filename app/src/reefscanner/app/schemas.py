"""Request/response models for the HTTP API.

Separate from the SQLModel tables on purpose: the wire format shouldn't move
every time a column does, and the read models flatten a Label onto its Event
because that's how the review UI wants it (one card = one decision).

Config is validated by round-tripping through ``ReefScannerConfig`` rather than
being redeclared here — ``from_dict`` already rejects unknown keys and
``validate()`` already enforces the ranges, and duplicating those rules is how
they drift apart.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from reefscanner.core.config import ReefScannerConfig
from .models import VALID_VERDICTS


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


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    input_folder: str = Field(min_length=1)
    output_folder: str = Field(min_length=1)
    #: Partial or full engine config; unset keys take the engine's defaults,
    #: except camera_timezone, which has to be given.
    config: dict[str, Any]

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
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    input_folder: Optional[str] = None
    output_folder: Optional[str] = None
    config: Optional[dict[str, Any]] = None

    @field_validator("config")
    @classmethod
    def _check_config(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if v is None:
            return v
        v = {k: val for k, val in v.items() if k not in ("input_folder", "output_folder")}
        # A config update replaces the stored blob, so it can't drop the zone.
        _require_camera_timezone(v)
        validated_config(v)
        return v


class ProjectRead(BaseModel):
    id: int
    name: str
    input_folder: str
    output_folder: str
    config: dict[str, Any]
    created_at: _dt.datetime
    job_count: int = 0


class JobRead(BaseModel):
    id: int
    project_id: int
    status: str
    progress: float
    message: str
    videos_total: int
    videos_done: int
    events_found: int
    started_at: Optional[_dt.datetime] = None
    finished_at: Optional[_dt.datetime] = None
    error: Optional[str] = None


class LabelWrite(BaseModel):
    """A human verdict. Upserted — posting twice updates, never duplicates."""

    verdict: str
    species: Optional[str] = None
    notes: Optional[str] = None
    tight_bbox: Optional[list[int]] = None

    @field_validator("verdict")
    @classmethod
    def _check_verdict(cls, v: str) -> str:
        if v not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {VALID_VERDICTS}")
        return v

    @field_validator("tight_bbox")
    @classmethod
    def _check_bbox(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        if v is None:
            return v
        if len(v) != 4:
            raise ValueError("tight_bbox must be [x, y, w, h]")
        if v[2] <= 0 or v[3] <= 0:
            raise ValueError("tight_bbox width and height must be > 0")
        return v


class LabelRead(BaseModel):
    verdict: str
    species: Optional[str] = None
    notes: Optional[str] = None
    tight_bbox: Optional[list[int]] = None
    updated_at: _dt.datetime


class EventRead(BaseModel):
    """One reviewable event, with its label flattened in when there is one."""

    id: int
    job_id: int
    event_id: str
    source_video: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    peak_timestamp: float
    peak_score: float
    peak_bbox: Optional[list[int]] = None
    motion_score: Optional[float] = None
    ml_confidence: Optional[float] = None
    detected_class: Optional[str] = None
    start_timestamp: str = ""
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    #: URLs served by the media router, not filesystem paths — the UI must not
    #: need to know where on disk the output folder is.
    clip_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    #: The clean frame, for anything that must not see the drawn box.
    frame_url: Optional[str] = None
    label: Optional[LabelRead] = None


class EventPage(BaseModel):
    """A page of events plus the totals the UI shows above the grid."""

    items: list[EventRead]
    total: int
    limit: int
    offset: int
    n_labeled: int
    n_tp: int
    n_fp: int
