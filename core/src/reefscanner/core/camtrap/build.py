"""From "the detector found something" to Camtrap DP rows.

The one mapping between the engine's events and the standard, used by the
field app's scans and, later, the edge agent's event writer. Decisions behind
it are in docs/specs/v3/features/ (the data-model and app-on-Camtrap notes).

IDs are readable and deterministic, joined with ``:`` so they survive in URL
paths: ``<deployment>:<scan>:<video-stem>_<seq>`` for an event, with
``:clip``/``:frame`` and ``:machine``/``:human`` suffixes for its rows.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..events import Event, wall_clock
from ..videoio import VideoInfo
from .models import Detection, Media, Observation, ObservationExtra
from .vocab import taxon_for_class

#: Media types for the files a scan keeps.
_MEDIATYPES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v",
    ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",
}


@dataclass
class ScanContext:
    """What one scan knows that the rows need, beyond the events themselves."""

    deployment_id: str
    scan_id: str
    camera_timezone: str
    camera_clock: str
    #: Where the scan put clips and clean frames, relative to the package root.
    clips_dir: str
    frames_dir: str
    frame_ext: str
    #: Seconds of padding the clip extractor added around each event.
    pad_seconds: float
    model_name: str
    model_version: str
    detector_backend: str
    detector_config: dict[str, Any] = field(default_factory=dict)
    classified_at: _dt.datetime = field(
        default_factory=lambda: _dt.datetime.now(_dt.timezone.utc)
    )


@dataclass
class VideoRows:
    """Camtrap rows for one scanned video, in insertion order (parents first)."""

    media: list[Media] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    extras: list[ObservationExtra] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)
    #: When the video started and ended on the wall clock.
    video_start: _dt.datetime | None = None
    video_end: _dt.datetime | None = None
    #: True when the start time was guessed from the file, not recorded in it.
    timestamp_issues: bool = False

    def extend(self, other: VideoRows) -> None:
        self.media += other.media
        self.observations += other.observations
        self.extras += other.extras
        self.detections += other.detections


def event_id(ctx: ScanContext, event: Event) -> str:
    return f"{ctx.deployment_id}:{ctx.scan_id}:{event.event_id}"


def file_start(
    info: VideoInfo, camera_timezone: str, camera_clock: str
) -> tuple[_dt.datetime, bool]:
    """When a video's first frame happened, and whether that is a guess.

    The recorded creation time, read per the camera's timezone and clock, when
    the file has one. Otherwise the file's modification time minus its
    duration: often right for a file straight off the camera, wrong for a copy,
    hence flagged so the deployment can say its timestamps have issues.
    """
    recorded = wall_clock(info.creation_time, 0.0, camera_timezone, camera_clock)
    if recorded is not None:
        return recorded, False
    from zoneinfo import ZoneInfo

    modified = _dt.datetime.fromtimestamp(
        Path(info.path).stat().st_mtime, tz=ZoneInfo(camera_timezone)
    )
    return modified - _dt.timedelta(seconds=info.duration_seconds or 0.0), True


def rows_for_video(
    ctx: ScanContext, info: VideoInfo, events: Sequence[Event]
) -> VideoRows:
    """Media, machine observations and per-frame detections for one video."""
    start, guessed = file_start(info, ctx.camera_timezone, ctx.camera_clock)
    out = VideoRows(
        video_start=start,
        video_end=start + _dt.timedelta(seconds=info.duration_seconds or 0.0),
        timestamp_issues=guessed,
    )
    for ev in events:
        out.extend(rows_for_event(
            ctx, ev, start=start, width=info.width, height=info.height,
            source_name=Path(info.path).name,
            clip_suffix=Path(info.path).suffix.lower() or ".mp4",
        ))
    return out


def rows_for_event(
    ctx: ScanContext,
    ev: Event,
    *,
    start: _dt.datetime,
    width: int,
    height: int,
    source_name: str,
    clip_suffix: str,
    clip_start_seconds: float | None = None,
) -> VideoRows:
    """Media, machine observation and per-frame detections for one event.

    ``start`` is when second 0 of the event's times happened; ``width`` and
    ``height`` are the frame size its boxes are in. The clip is assumed to
    start ``pad_seconds`` before the event unless ``clip_start_seconds`` says
    where it really starts (the edge agent's clips snap to buffer segments).
    """
    out = VideoRows()

    def at(seconds: float) -> _dt.datetime:
        # Camtrap timestamps have whole seconds; keep the offset, drop the rest.
        return (start + _dt.timedelta(seconds=seconds)).replace(microsecond=0)

    if clip_start_seconds is None:
        clip_start_seconds = max(0.0, ev.start_seconds - ctx.pad_seconds)
    eid = event_id(ctx, ev)
    clip_id, frame_id = f"{eid}:clip", f"{eid}:frame"
    out.media += [
        Media(
            mediaID=clip_id,
            deploymentID=ctx.deployment_id,
            captureMethod="activityDetection",
            timestamp=at(clip_start_seconds),
            filePath=f"{ctx.clips_dir}/{ev.event_id}{clip_suffix}",
            fileName=f"{ev.event_id}{clip_suffix}",
            fileMediatype=_MEDIATYPES.get(clip_suffix, "video/mp4"),
        ),
        Media(
            mediaID=frame_id,
            deploymentID=ctx.deployment_id,
            captureMethod="activityDetection",
            timestamp=at(ev.peak_timestamp),
            filePath=f"{ctx.frames_dir}/{ev.event_id}{ctx.frame_ext}",
            fileName=f"{ev.event_id}{ctx.frame_ext}",
            fileMediatype=_MEDIATYPES.get(ctx.frame_ext, "image/jpeg"),
        ),
    ]

    taxon = taxon_for_class(ev.peak_class) if ev.peak_class else None
    box = relative_bbox(ev.peak_bbox, width, height)
    obs_id = f"{eid}:machine"
    out.observations.append(Observation(
        observationID=obs_id,
        deploymentID=ctx.deployment_id,
        mediaID=frame_id,
        eventID=eid,
        eventStart=at(ev.start_seconds),
        eventEnd=at(ev.end_seconds),
        observationLevel="media",
        # A class we can't name scientifically is still a detection worth
        # reviewing, just not a known animal.
        observationType="animal" if taxon else "unknown",
        scientificName=taxon,
        **box,
        classificationMethod="machine",
        classifiedBy=f"{ctx.model_name} ({ctx.detector_backend}, {ctx.model_version})",
        classificationTimestamp=ctx.classified_at.replace(microsecond=0),
        classificationProbability=_unit(ev.peak_ml_confidence),
    ))
    out.extras.append(ObservationExtra(
        observationID=obs_id,
        scanID=ctx.scan_id,
        sourceVideo=source_name,
        videoStartSeconds=round(ev.start_seconds, 3),
        videoEndSeconds=round(ev.end_seconds, 3),
        peakSeconds=round(ev.peak_timestamp, 3),
        detectorClass=ev.peak_class,
        modelName=ctx.model_name,
        modelVersion=ctx.model_version,
        detectorBackend=ctx.detector_backend,
        detectorConfig=ctx.detector_config,
    ))
    for hit in ev.members:
        if hit.ml_confidence is None:
            continue
        out.detections.append(Detection(
            observationID=obs_id,
            frameTimestamp=at(hit.timestamp),
            **relative_bbox(hit.bbox, width, height),
            confidence=_unit(hit.ml_confidence),
        ))
    return out


def relative_bbox(
    bbox: Sequence[float] | None, width: int, height: int
) -> dict[str, float | None]:
    """Pixel (x, y, w, h) to Camtrap's 0-1 box, clipped to the frame."""
    if not bbox or not width or not height:
        return {"bboxX": None, "bboxY": None, "bboxWidth": None, "bboxHeight": None}
    x, y, w, h = bbox
    x0, y0 = min(max(x / width, 0.0), 1.0), min(max(y / height, 0.0), 1.0)
    x1, y1 = min(max((x + w) / width, 0.0), 1.0), min(max((y + h) / height, 0.0), 1.0)
    # The standard needs a width and height above zero.
    tiny = 1e-6
    return {
        "bboxX": round(x0, 6),
        "bboxY": round(y0, 6),
        "bboxWidth": round(max(x1 - x0, tiny), 6),
        "bboxHeight": round(max(y1 - y0, tiny), 6),
    }


def _unit(value: float | None) -> float | None:
    return None if value is None else round(min(max(float(value), 0.0), 1.0), 6)
