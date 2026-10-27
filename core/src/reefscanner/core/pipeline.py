"""Pipeline orchestration (SPEC §3, §7).

Discover -> per-video [sample -> detector scan -> aggregate -> clips/thumbnails
-> CSV] -> mark complete. Resumable per-video: completed videos are skipped on
restart; an interrupted video reprocesses from frame 0.

The detector scans every sampled frame and is the recall source; motion is an
optional cheap pre-skip (``motion_prefilter``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .clips import (
    extract_clip,
    read_peak_frame,
    resolve_ffmpeg,
    save_clean_frame,
    save_thumbnail,
)
from .config import ReefScannerConfig
from .detectors import get_detector
from .discovery import discover_videos
from .events import Candidate, Event, aggregate_events
from .manifest import Manifest
from .motion import MotionGate
from .results import CsvWriter, event_to_row
from .videoio import VideoInfo, iter_sampled_frames, probe_video

logger = logging.getLogger("reefscanner")


class JobCancelled(Exception):
    """Raised when ``should_cancel`` asks the run to stop.

    Cancellation is cooperative and checked between sampled frames, so a Stop
    button reacts within one frame decode rather than after the current video.
    Work already committed (clips, CSV rows, manifest entries for *finished*
    videos) is kept — the run is interrupted, not rolled back.
    """


@dataclass
class VideoResult:
    video: Path
    info: VideoInfo | None
    events: list[Event] = field(default_factory=list)
    skipped: bool = False
    error: str | None = None


@dataclass
class BatchResult:
    csv_path: Path
    manifest_path: Path
    results: list[VideoResult] = field(default_factory=list)
    #: True when the run stopped early because ``should_cancel`` returned True.
    cancelled: bool = False

    @property
    def n_events(self) -> int:
        return sum(len(r.events) for r in self.results)

    @property
    def n_videos_processed(self) -> int:
        return sum(1 for r in self.results if not r.skipped and r.error is None)

    @property
    def n_skipped(self) -> int:
        """Videos already finished under these settings, so not redone."""
        return sum(1 for r in self.results if r.skipped)


def _collect_candidates(
    video,
    cfg: ReefScannerConfig,
    info: VideoInfo,
    detector,
    on_frame: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[Candidate]:
    """Produce per-frame candidates by running the detector on sampled frames.

    ``on_frame`` is called after each sampled frame with this video's progress
    as a 0..1 fraction (always 0.0 when the duration is unknown). It exists so a
    UI can show movement inside a single long video, where per-video callbacks
    would sit silent for minutes.
    """

    def _tick(sample) -> None:
        if should_cancel is not None and should_cancel():
            raise JobCancelled(f"cancelled during {video}")
        if on_frame is not None:
            duration = info.duration_seconds
            on_frame(min(1.0, sample.timestamp / duration) if duration > 0 else 0.0)

    candidates: list[Candidate] = []

    # The detector is the recall source. Motion is only ever an optional cheap
    # pre-skip of dead-static frames.
    prefilter = MotionGate(cfg) if cfg.motion_prefilter else None
    for sample in iter_sampled_frames(info, cfg.frame_sample_fps):
        if prefilter is not None and not prefilter.has_motion(sample):
            _tick(sample)
            continue  # cheap skip of dead-static frames (recall-safe)
        for det in detector.detect(sample.frame):
            candidates.append(
                Candidate(
                    sampled_index=sample.index,
                    source_frame=sample.source_frame,
                    timestamp=sample.timestamp,
                    bbox=det.bbox,
                    score=det.confidence,
                    class_name=det.class_name,
                    ml_confidence=det.confidence,
                )
            )
        _tick(sample)
    return candidates


def find_events(
    video: Path,
    cfg: ReefScannerConfig,
    info: VideoInfo,
    detector,
    on_frame: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[Event]:
    """The laptop scan's events for one video, with nothing written.

    Also the reference the edge agent's replay is checked against.
    """
    candidates = _collect_candidates(
        video, cfg, info, detector, on_frame=on_frame, should_cancel=should_cancel
    )
    return aggregate_events(
        candidates, cfg, video_stem=video.stem, source_video=str(video)
    )


def process_video(
    video: Path,
    cfg: ReefScannerConfig,
    info: VideoInfo,
    detector,
    ffmpeg: str,
    on_frame: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[Event], list[dict]]:
    """Run the per-video pipeline. Returns (events, csv_rows).

    Does no manifest/CSV side effects itself so the caller controls commit order
    (clips/thumbs/CSV then mark complete).
    """
    out_dir = Path(cfg.output_folder)
    clips_dir = out_dir / cfg.clips_dirname
    thumbs_dir = out_dir / cfg.thumbnails_dirname
    frames_dir = out_dir / cfg.frames_dirname

    events = find_events(
        video, cfg, info, detector, on_frame=on_frame, should_cancel=should_cancel
    )

    rows: list[dict] = []
    for event in events:
        clip_path = extract_clip(event, info, cfg, clips_dir, ffmpeg=ffmpeg)
        # One decode, two writes: the annotated thumbnail for triage and the
        # clean frame for training exports.
        peak = read_peak_frame(event, info)
        thumb_path = save_thumbnail(event, info, cfg, thumbs_dir, frame=peak)
        save_clean_frame(event, info, cfg, frames_dir, frame=peak)
        rows.append(event_to_row(
            event, info, str(clip_path), str(thumb_path),
            cfg.camera_timezone, cfg.camera_clock,
        ))
    return events, rows


def process_folder(
    cfg: ReefScannerConfig,
    progress: bool = True,
    on_video: Callable[[VideoResult], None] | None = None,
    on_frame: Callable[[Path, int, int, float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> BatchResult:
    """Process every video under ``cfg.input_folder`` into ``cfg.output_folder``.

    Resumable: videos already marked complete in the manifest are skipped.

    Two optional hooks let a UI drive this:

    * ``on_video(result)`` fires once per finished video — coarse but exact.
    * ``on_frame(video, index, total, fraction)`` fires per *sampled frame*,
      giving movement inside a single long video. ``index``/``total`` count
      videos; ``fraction`` is progress through the current one. Callers should
      expect this to be hot and throttle their own side.

    ``should_cancel`` is polled between sampled frames; returning True stops the
    run and leaves the batch partial (completed videos stay committed).
    """
    if not cfg.input_folder or not cfg.output_folder:
        raise ValueError("config.input_folder and config.output_folder are required")

    input_root = Path(cfg.input_folder)
    out_dir = Path(cfg.output_folder)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / cfg.csv_name
    manifest_path = out_dir / cfg.manifest_name
    manifest = Manifest(manifest_path, input_root, scan_key=cfg.scan_fingerprint())
    csv_writer = CsvWriter(csv_path)
    existing_ids = csv_writer.existing_event_ids()

    # Build the detector once (model loaded a single time); for 'none' a no-op.
    detector = get_detector(cfg)
    ffmpeg = resolve_ffmpeg(cfg)

    videos = discover_videos(input_root, cfg.extensions)
    if cfg.camera_timezone is None:
        logger.warning(
            "No camera timezone set, so events get no wall-clock timestamp. "
            "Set camera_timezone (--camera-timezone) to the zone the camera's "
            "clock was set to, e.g. Africa/Maputo."
        )
    logger.info(
        "Discovered %d video(s) under %s (detector=%s)",
        len(videos), input_root, cfg.detector,
    )

    iterator = videos
    if progress:
        try:
            from tqdm.auto import tqdm

            iterator = tqdm(videos, desc="Videos", unit="video")
        except ImportError:
            iterator = videos

    batch = BatchResult(csv_path=csv_path, manifest_path=manifest_path)

    for index, video in enumerate(iterator):
        result = VideoResult(video=video, info=None)

        if should_cancel is not None and should_cancel():
            batch.cancelled = True
            logger.info("Run cancelled before %s", video.name)
            break

        if manifest.is_complete(video):
            result.skipped = True
            logger.info("Skipping completed video: %s", video.name)
            batch.results.append(result)
            if on_video:
                on_video(result)
            continue

        try:
            info = probe_video(video)
            result.info = info
            frame_cb = None
            if on_frame is not None:
                frame_cb = lambda frac, _v=video, _i=index: on_frame(
                    _v, _i, len(videos), frac
                )
            events, rows = process_video(
                video, cfg, info, detector, ffmpeg,
                on_frame=frame_cb, should_cancel=should_cancel,
            )

            # Reconcile against any CSV rows from a prior torn run (SPEC §7).
            rows = [r for r in rows if r["event_id"] not in existing_ids]
            csv_writer.append_rows(rows)
            existing_ids.update(r["event_id"] for r in rows)

            # Mark complete only after clips+thumbs+CSV are flushed (SPEC §7).
            manifest.mark_complete(
                video, n_events=len(events),
                event_ids=[e.event_id for e in events],
            )
            result.events = events
        except JobCancelled:
            # Not an error: the partly-processed video is simply left unmarked
            # in the manifest, so a later run redoes it from frame 0.
            batch.cancelled = True
            logger.info("Run cancelled during %s", video.name)
            break
        except Exception as exc:  # keep going; an interrupted video reprocesses
            result.error = str(exc)
            logger.exception("Failed processing %s: %s", video, exc)

        batch.results.append(result)
        if on_video:
            on_video(result)

    logger.info(
        "Done. %d video(s) processed, %d event(s) emitted.",
        batch.n_videos_processed, batch.n_events,
    )
    return batch
