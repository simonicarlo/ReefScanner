"""Camtrap DP tables, as SQLModel classes.

One definition for every tier: the edge agent builds these as plain objects and
writes them to CSV, and the field app stores the same classes in SQLite. Field
names are exactly the standard's (``deploymentID``, ``bboxX``…), so a row maps
onto a CSV column with no translation table to keep in sync.

The three Camtrap tables follow the 1.0.2 table schemas. Columns the standard
requires are NOT NULL here, except where a row legitimately exists before the
value is known (a deployment is set up before it starts recording); the package
writer enforces the standard's rules at export.

What Camtrap DP has no field for lives in two sidecar tables keyed by
``observationID``; see the design note in docs/specs/v3/features/.

Two things to know when using them:

* There are no ORM relationships, so SQLAlchemy won't order inserts by foreign
  key. Add rows parents-first (deployments, media, observations, sidecar) and
  flush between levels.
* Like any SQLModel table class, the constructor does not validate. Use
  ``Model.model_validate(data)`` where the constraints (coordinate ranges,
  relative boxes) must hold.
"""

# NOTE: no ``from __future__ import annotations``: SQLModel evaluates field
# annotations at class creation (see app/models.py for the same note).
import datetime as _dt
from typing import Any, Optional

from sqlalchemy import JSON, Column, String, Text, TypeDecorator
from sqlmodel import Field, SQLModel


class TZDateTime(TypeDecorator):
    """A timezone-aware datetime, stored as ISO 8601 text with its offset.

    SQLAlchemy's DateTime drops the offset on SQLite, and Camtrap DP requires
    one on every timestamp. Storing a naive datetime is refused outright: a
    timestamp without a timezone is ambiguous by hours, which is exactly the
    error the standard exists to rule out.
    """

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: Optional[_dt.datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"timestamp needs a timezone: {value!r}")
        return value.isoformat()

    def process_result_value(self, value: Optional[str], dialect):
        return None if value is None else _dt.datetime.fromisoformat(value)


def _tz(nullable: bool = False) -> Any:
    return Field(default=None, sa_column=Column(TZDateTime(), nullable=nullable))


def _text() -> Any:
    return Field(default=None, sa_column=Column(Text))


class Deployment(SQLModel, table=True):
    """One rig drop: a continuous recording at one place."""

    __tablename__ = "deployments"

    deploymentID: str = Field(primary_key=True)
    locationID: Optional[str] = None
    locationName: Optional[str] = None
    # Required by the standard and by us: a good setup records coordinates.
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    coordinateUncertainty: Optional[int] = Field(default=None, ge=1)
    # Required at export, but unknown when a deployment is set up before sealing.
    deploymentStart: Optional[_dt.datetime] = _tz(nullable=True)
    deploymentEnd: Optional[_dt.datetime] = _tz(nullable=True)
    setupBy: Optional[str] = None
    cameraID: Optional[str] = None
    cameraModel: Optional[str] = None
    cameraDelay: Optional[int] = Field(default=None, ge=0)
    cameraHeight: Optional[float] = Field(default=None, ge=0)
    #: Metres. For a BRUV this is the rig's water depth.
    cameraDepth: Optional[float] = Field(default=None, ge=0)
    cameraTilt: Optional[int] = Field(default=None, ge=-90, le=90)
    cameraHeading: Optional[int] = Field(default=None, ge=0, le=360)
    detectionDistance: Optional[float] = Field(default=None, ge=0)
    timestampIssues: Optional[bool] = None
    baitUse: Optional[bool] = None
    featureType: Optional[str] = None
    habitat: Optional[str] = None
    deploymentGroups: Optional[str] = None
    deploymentTags: Optional[str] = None
    deploymentComments: Optional[str] = _text()


class Media(SQLModel, table=True):
    """One kept file: an event clip, a clean peak frame, or a backup segment."""

    __tablename__ = "media"

    mediaID: str = Field(primary_key=True)
    deploymentID: str = Field(
        foreign_key="deployments.deploymentID", index=True, ondelete="CASCADE"
    )
    captureMethod: Optional[str] = None
    #: The file's first frame.
    timestamp: _dt.datetime = _tz()
    #: Relative to the package folder.
    filePath: str
    filePublic: bool = False
    fileName: Optional[str] = None
    fileMediatype: str
    exifData: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    favorite: Optional[bool] = None
    mediaComments: Optional[str] = _text()


class Observation(SQLModel, table=True):
    """One classification of something seen, by the detector or a human."""

    __tablename__ = "observations"

    observationID: str = Field(primary_key=True)
    deploymentID: str = Field(
        foreign_key="deployments.deploymentID", index=True, ondelete="CASCADE"
    )
    mediaID: Optional[str] = Field(
        default=None, foreign_key="media.mediaID", index=True, ondelete="CASCADE"
    )
    eventID: Optional[str] = Field(default=None, index=True)
    eventStart: _dt.datetime = _tz()
    eventEnd: _dt.datetime = _tz()
    observationLevel: str
    observationType: str = Field(index=True)
    cameraSetupType: Optional[str] = None
    scientificName: Optional[str] = Field(default=None, index=True)
    count: Optional[int] = Field(default=None, ge=1)
    lifeStage: Optional[str] = None
    sex: Optional[str] = None
    behavior: Optional[str] = None
    individualID: Optional[str] = None
    individualPositionRadius: Optional[float] = Field(default=None, ge=0)
    individualPositionAngle: Optional[float] = Field(default=None, ge=-90, le=90)
    individualSpeed: Optional[float] = Field(default=None, ge=0)
    #: Bounding box, relative to the media file's width and height (0 to 1).
    bboxX: Optional[float] = Field(default=None, ge=0, le=1)
    bboxY: Optional[float] = Field(default=None, ge=0, le=1)
    bboxWidth: Optional[float] = Field(default=None, gt=0, le=1)
    bboxHeight: Optional[float] = Field(default=None, gt=0, le=1)
    classificationMethod: Optional[str] = Field(default=None, index=True)
    classifiedBy: Optional[str] = None
    classificationTimestamp: Optional[_dt.datetime] = _tz(nullable=True)
    classificationProbability: Optional[float] = Field(default=None, ge=0, le=1)
    #: Pipe-separated ``key:value`` tags; carries ``verdict:<TP|FP|...>``.
    observationTags: Optional[str] = None
    observationComments: Optional[str] = _text()


# -- sidecar: what Camtrap DP has no field for ------------------------------------

class ObservationExtra(SQLModel, table=True):
    """ReefScanner's per-observation fields, written as reefscanner-observations.csv."""

    __tablename__ = "reefscanner_observations"

    observationID: str = Field(
        primary_key=True, foreign_key="observations.observationID", ondelete="CASCADE"
    )
    trackID: Optional[str] = None
    modelName: Optional[str] = None
    modelVersion: Optional[str] = None
    detectorBackend: Optional[str] = None
    #: The scan config the detection came from, as JSON.
    detectorConfig: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )


class Detection(SQLModel, table=True):
    """One detector hit on one sampled frame, written as reefscanner-detections.csv.

    The per-frame confidence series behind an observation's single peak value,
    for threshold analysis and, later, tracking.
    """

    __tablename__ = "reefscanner_detections"

    id: Optional[int] = Field(default=None, primary_key=True)
    observationID: str = Field(
        foreign_key="observations.observationID", index=True, ondelete="CASCADE"
    )
    frameTimestamp: _dt.datetime = _tz()
    bboxX: float = Field(ge=0, le=1)
    bboxY: float = Field(ge=0, le=1)
    bboxWidth: float = Field(gt=0, le=1)
    bboxHeight: float = Field(gt=0, le=1)
    confidence: float = Field(ge=0, le=1)
