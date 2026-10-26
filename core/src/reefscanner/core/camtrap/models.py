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
from typing import Any

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

    def process_bind_param(self, value: _dt.datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"timestamp needs a timezone: {value!r}")
        return value.isoformat()

    def process_result_value(self, value: str | None, dialect: Any) -> _dt.datetime | None:
        return None if value is None else _dt.datetime.fromisoformat(value)


def _tz(nullable: bool = False) -> Any:
    return Field(default=None, sa_column=Column(TZDateTime(), nullable=nullable))


def _text() -> Any:
    return Field(default=None, sa_column=Column(Text))


class Deployment(SQLModel, table=True):
    """One rig drop: a continuous recording at one place."""

    __tablename__ = "deployments"

    deploymentID: str = Field(primary_key=True)
    locationID: str | None = None
    locationName: str | None = None
    # Required by the standard and by us: a good setup records coordinates.
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    coordinateUncertainty: int | None = Field(default=None, ge=1)
    # Required at export, but unknown when a deployment is set up before sealing.
    deploymentStart: _dt.datetime | None = _tz(nullable=True)
    deploymentEnd: _dt.datetime | None = _tz(nullable=True)
    setupBy: str | None = None
    cameraID: str | None = None
    cameraModel: str | None = None
    cameraDelay: int | None = Field(default=None, ge=0)
    cameraHeight: float | None = Field(default=None, ge=0)
    #: Metres. For a BRUV this is the rig's water depth.
    cameraDepth: float | None = Field(default=None, ge=0)
    cameraTilt: int | None = Field(default=None, ge=-90, le=90)
    cameraHeading: int | None = Field(default=None, ge=0, le=360)
    detectionDistance: float | None = Field(default=None, ge=0)
    timestampIssues: bool | None = None
    baitUse: bool | None = None
    featureType: str | None = None
    habitat: str | None = None
    deploymentGroups: str | None = None
    deploymentTags: str | None = None
    deploymentComments: str | None = _text()


class Media(SQLModel, table=True):
    """One kept file: an event clip, a clean peak frame, or a backup segment."""

    __tablename__ = "media"

    mediaID: str = Field(primary_key=True)
    deploymentID: str = Field(
        foreign_key="deployments.deploymentID", index=True, ondelete="CASCADE"
    )
    captureMethod: str | None = None
    #: The file's first frame.
    timestamp: _dt.datetime = _tz()
    #: Relative to the package folder.
    filePath: str
    filePublic: bool = False
    fileName: str | None = None
    fileMediatype: str
    exifData: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    favorite: bool | None = None
    mediaComments: str | None = _text()


class Observation(SQLModel, table=True):
    """One classification of something seen, by the detector or a human."""

    __tablename__ = "observations"

    observationID: str = Field(primary_key=True)
    deploymentID: str = Field(
        foreign_key="deployments.deploymentID", index=True, ondelete="CASCADE"
    )
    mediaID: str | None = Field(
        default=None, foreign_key="media.mediaID", index=True, ondelete="CASCADE"
    )
    eventID: str | None = Field(default=None, index=True)
    eventStart: _dt.datetime = _tz()
    eventEnd: _dt.datetime = _tz()
    observationLevel: str
    observationType: str = Field(index=True)
    cameraSetupType: str | None = None
    scientificName: str | None = Field(default=None, index=True)
    count: int | None = Field(default=None, ge=1)
    lifeStage: str | None = None
    sex: str | None = None
    behavior: str | None = None
    individualID: str | None = None
    individualPositionRadius: float | None = Field(default=None, ge=0)
    individualPositionAngle: float | None = Field(default=None, ge=-90, le=90)
    individualSpeed: float | None = Field(default=None, ge=0)
    #: Bounding box, relative to the media file's width and height (0 to 1).
    bboxX: float | None = Field(default=None, ge=0, le=1)
    bboxY: float | None = Field(default=None, ge=0, le=1)
    bboxWidth: float | None = Field(default=None, gt=0, le=1)
    bboxHeight: float | None = Field(default=None, gt=0, le=1)
    classificationMethod: str | None = Field(default=None, index=True)
    classifiedBy: str | None = None
    classificationTimestamp: _dt.datetime | None = _tz(nullable=True)
    classificationProbability: float | None = Field(default=None, ge=0, le=1)
    #: Pipe-separated ``key:value`` tags; carries ``verdict:<TP|FP|...>``.
    observationTags: str | None = None
    observationComments: str | None = _text()


# -- sidecar: what Camtrap DP has no field for ------------------------------------

class ObservationExtra(SQLModel, table=True):
    """ReefScanner's per-observation fields, written as reefscanner-observations.csv."""

    __tablename__ = "reefscanner_observations"

    observationID: str = Field(
        primary_key=True, foreign_key="observations.observationID", ondelete="CASCADE"
    )
    #: The scan run that produced this observation (the app's run id).
    scanID: str | None = Field(default=None, index=True)
    trackID: str | None = None
    #: Where in the original footage the event is: file name and seconds.
    sourceVideo: str | None = None
    videoStartSeconds: float | None = None
    videoEndSeconds: float | None = None
    peakSeconds: float | None = None
    #: The detector's own class label, before mapping to a scientific name.
    detectorClass: str | None = None
    modelName: str | None = None
    modelVersion: str | None = None
    detectorBackend: str | None = None
    #: The scan config the detection came from, as JSON.
    detectorConfig: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )


class Detection(SQLModel, table=True):
    """One detector hit on one sampled frame, written as reefscanner-detections.csv.

    The per-frame confidence series behind an observation's single peak value,
    for threshold analysis and, later, tracking.
    """

    __tablename__ = "reefscanner_detections"

    id: int | None = Field(default=None, primary_key=True)
    observationID: str = Field(
        foreign_key="observations.observationID", index=True, ondelete="CASCADE"
    )
    frameTimestamp: _dt.datetime = _tz()
    bboxX: float = Field(ge=0, le=1)
    bboxY: float = Field(ge=0, le=1)
    bboxWidth: float = Field(gt=0, le=1)
    bboxHeight: float = Field(gt=0, le=1)
    confidence: float = Field(ge=0, le=1)
