"""Pipeline orchestration (SPEC §3, §7).

Discover -> per-video [sample -> (motion gate | detector scan) -> aggregate ->
clips/thumbnails -> CSV] -> mark complete. Resumable per-video: completed videos
are skipped on restart; an interrupted video reprocesses from frame 0.

Two modes (chosen by ``cfg.detector``):
  * ``none`` — v1 motion-only: the motion gate is the recall source (no ML deps).
  * ``marine`` / ``generic`` — v2 detector-scans-frames: the detector scans every
    sampled frame and is the recall source; motion becomes an optional cheap
    pre-skip (``motion_prefilter``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .clips import extract_clip, resolve_ffmpeg, save_thumbnail
from .config import DETECTOR_NONE, ReefScannerConfig
from .detectors import get_detector
from .discovery import discover_videos
from .events import Candidate, Event, aggregate_events
from .manifest import Manifest
from .motion import MotionGate
from .results import CsvWriter, event_to_row
from .videoio import VideoInfo, iter_sampled_frames, probe_video

logger = logging.getLogger("reefscanner")


@dataclass
class VideoResult:
    video: Path
    info: Optional[VideoInfo]
    events: list[Event] = field(default_factory=list)
    skipped: bool = False
    error: Optional[str] = None


@dataclass
class BatchResult:
    csv_path: Path
    manifest_path: Path
    results: list[VideoResult] = field(default_factory=list)

    @property
    def n_events(self) -> int:
        return sum(len(r.events) for r in self.results)

    @property
    def n_videos_processed(self) -> int:
        return sum(1 for r in self.results if not r.skipped and r.error is None)


def _collect_candidates(
    video,
    cfg: ReefScannerConfig,
    info: VideoInfo,
    detector,
) -> list[Candidate]:
    """Produce per-frame candidates via motion (v1) or the detector (v2)."""
    candidates: list[Candidate] = []

    if cfg.detector == DETECTOR_NONE:
        # v1 motion-only: the gate is the recall source.
        gate = MotionGate(cfg)
        for sample in iter_sampled_frames(info, cfg.frame_sample_fps):
            cand = gate.process(sample)
            if cand is not None:
                candidates.append(cand)
        return candidates

    # v2 detector-scans-frames: the detector is the recall source.
    prefilter = MotionGate(cfg) if cfg.motion_prefilter else None
    for sample in iter_sampled_frames(info, cfg.frame_sample_fps):
        if prefilter is not None and not prefilter.has_motion(sample):
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
    return candidates


def process_video(
    video: Path,
    cfg: ReefScannerConfig,
    info: VideoInfo,
    detector,
    ffmpeg: str,
) -> tuple[list[Event], list[dict]]:
    """Run the per-video pipeline. Returns (events, csv_rows).

    Does no manifest/CSV side effects itself so the caller controls commit order
    (clips/thumbs/CSV then mark complete).
    """
    out_dir = Path(cfg.output_folder)
    clips_dir = out_dir / cfg.clips_dirname
    thumbs_dir = out_dir / cfg.thumbnails_dirname

    candidates = _collect_candidates(video, cfg, info, detector)
    events = aggregate_events(
        candidates, cfg, video_stem=video.stem, source_video=str(video)
    )

    rows: list[dict] = []
    for event in events:
        clip_path = extract_clip(event, info, cfg, clips_dir, ffmpeg=ffmpeg)
        thumb_path = save_thumbnail(event, info, cfg, thumbs_dir)
        rows.append(event_to_row(event, info, str(clip_path), str(thumb_path)))
    return events, rows


def process_folder(
    cfg: ReefScannerConfig,
    progress: bool = True,
    on_video: Optional[Callable[[VideoResult], None]] = None,
) -> BatchResult:
    """Process every video under ``cfg.input_folder`` into ``cfg.output_folder``.

    Resumable: videos already marked complete in the manifest are skipped.
    """
    if not cfg.input_folder or not cfg.output_folder:
        raise ValueError("config.input_folder and config.output_folder are required")

    input_root = Path(cfg.input_folder)
    out_dir = Path(cfg.output_folder)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / cfg.csv_name
    manifest_path = out_dir / cfg.manifest_name
    manifest = Manifest(manifest_path, input_root)
    csv_writer = CsvWriter(csv_path)
    existing_ids = csv_writer.existing_event_ids()

    # Build the detector once (model loaded a single time); for 'none' a no-op.
    detector = get_detector(cfg)
    ffmpeg = resolve_ffmpeg(cfg)

    videos = discover_videos(input_root, cfg.extensions)
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

    for video in iterator:
        result = VideoResult(video=video, info=None)

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
            events, rows = process_video(video, cfg, info, detector, ffmpeg)

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
