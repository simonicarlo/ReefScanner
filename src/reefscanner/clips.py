"""Step 6 — Clip + thumbnail output (SPEC §3 Step 6).

One clip per event via ffmpeg, padded by pad_seconds. Default stream-copy
(-c copy) for speed; re-encode switchable. Thumbnails (peak frame) saved via
OpenCV with the motion bbox drawn for quick human triage.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

import cv2

from .config import ReefScannerConfig
from .events import Event
from .videoio import VideoInfo


def resolve_ffmpeg(cfg: ReefScannerConfig) -> str:
    """Locate the ffmpeg binary: config path, then PATH, then imageio fallback."""
    if cfg.ffmpeg_path:
        return cfg.ffmpeg_path
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # optional convenience for environments without a system ffmpeg
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg (Colab has it preinstalled), "
            "set config.ffmpeg_path, or `pip install imageio-ffmpeg`."
        ) from exc


def extract_clip(
    event: Event,
    info: VideoInfo,
    cfg: ReefScannerConfig,
    out_dir: Path,
    ffmpeg: Optional[str] = None,
) -> Path:
    """Extract one padded clip for ``event``; returns the clip path.

    Padding absorbs keyframe drift from stream-copy (SPEC §3 Step 6). Start is
    clamped to 0; end to the video duration when known.
    """
    ffmpeg = ffmpeg or resolve_ffmpeg(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)

    start = max(0.0, event.start_seconds - cfg.pad_seconds)
    end = event.end_seconds + cfg.pad_seconds
    if info.duration_seconds > 0:
        end = min(end, info.duration_seconds)
    duration = max(0.1, end - start)

    ext = info.path.suffix or ".mp4"
    clip_path = out_dir / f"{event.event_id}{ext}"

    cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", str(info.path),
           "-t", f"{duration:.3f}"]
    if cfg.reencode_clips:
        # Accurate boundaries; needed more often than "rarely" (SPEC §3).
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac"]
    else:
        cmd += ["-c", "copy"]
    cmd.append(str(clip_path))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not clip_path.exists():
        raise RuntimeError(
            f"ffmpeg failed for event {event.event_id}:\n{proc.stderr[-2000:]}"
        )
    return clip_path


def save_thumbnail(
    event: Event,
    info: VideoInfo,
    cfg: ReefScannerConfig,
    out_dir: Path,
    draw_bbox: bool = True,
) -> Path:
    """Save the peak frame as a thumbnail, optionally with the motion bbox.

    Doubles as a pre-labeled training frame later (SPEC §10).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = out_dir / f"{event.event_id}{cfg.thumbnail_ext}"

    cap = cv2.VideoCapture(str(info.path))
    try:
        if info.fps > 0:
            frame_idx = int(round(event.peak_timestamp * info.fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            # Fallback: timestamp seek.
            cap.set(cv2.CAP_PROP_POS_MSEC, event.peak_timestamp * 1000.0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(
                f"Could not read peak frame for event {event.event_id}"
            )
    finally:
        cap.release()

    if draw_bbox and event.peak_bbox:
        x, y, w, h = event.peak_bbox
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)

    if not cv2.imwrite(str(thumb_path), frame):
        raise RuntimeError(f"Failed to write thumbnail: {thumb_path}")
    return thumb_path
