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
            "ffmpeg not found. Install it (macOS: `brew install ffmpeg`; "
            "Debian/Ubuntu: `apt install ffmpeg`), set config.ffmpeg_path, "
            "or `pip install imageio-ffmpeg` for a bundled fallback binary."
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


def read_peak_frame(event: Event, info: VideoInfo):
    """Decode the event's peak frame once. Callers may write it many ways."""
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
        return frame
    finally:
        cap.release()


def save_clean_frame(
    event: Event,
    info: VideoInfo,
    cfg: ReefScannerConfig,
    out_dir: Path,
    frame=None,
) -> Path:
    """Write the peak frame with nothing drawn on it — the training image.

    The annotation exporters point at this rather than the thumbnail: a model
    trained on the thumbnails would learn the red rectangle.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{event.event_id}{cfg.thumbnail_ext}"
    if frame is None:
        frame = read_peak_frame(event, info)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Failed to write frame: {path}")
    return path


def save_thumbnail(
    event: Event,
    info: VideoInfo,
    cfg: ReefScannerConfig,
    out_dir: Path,
    draw_bbox: bool = True,
    frame=None,
) -> Path:
    """Save the peak frame with the detection box drawn, for human triage."""
    out_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = out_dir / f"{event.event_id}{cfg.thumbnail_ext}"

    if frame is None:
        frame = read_peak_frame(event, info)
    # Copy before drawing: cv2.rectangle mutates in place, and the caller is
    # very likely holding this same array to write the clean frame.
    frame = frame.copy()

    if draw_bbox and event.peak_bbox:
        x, y, w, h = event.peak_bbox
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)

    if not cv2.imwrite(str(thumb_path), frame):
        raise RuntimeError(f"Failed to write thumbnail: {thumb_path}")
    return thumb_path
