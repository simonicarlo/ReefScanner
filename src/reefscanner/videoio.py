"""Video metadata detection and sampled-frame iteration (SPEC §2, §3 Step 2).

Format/framerate are auto-detected. We sample frames at a target fps rather
than decoding every frame — the main compute saving in v1.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import cv2


@dataclass
class VideoInfo:
    """Auto-detected metadata for a single source video."""

    path: Path
    fps: float
    frame_count: int
    width: int
    height: int
    #: Duration in seconds (from frame_count / fps when available).
    duration_seconds: float
    #: Wall-clock creation time from container metadata, if discoverable.
    creation_time: Optional[_dt.datetime] = None


def probe_video(path: str | Path) -> VideoInfo:
    """Detect fps, resolution, duration and (best-effort) creation time.

    Uses OpenCV for the core properties (always available) and an optional
    ``ffprobe`` call for the container creation timestamp (left blank if
    ffprobe is missing or the tag is absent — SPEC §3 allows a blank
    ``start_timestamp``).
    """
    path = Path(path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open video: {path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()

    if fps <= 0:
        # Some containers don't report fps via OpenCV; fall back to ffprobe.
        fps = _ffprobe_fps(path) or 0.0

    duration = (frame_count / fps) if (fps > 0 and frame_count > 0) else 0.0
    creation = _ffprobe_creation_time(path)
    return VideoInfo(
        path=path,
        fps=fps,
        frame_count=frame_count,
        width=width,
        height=height,
        duration_seconds=duration,
        creation_time=creation,
    )


@dataclass
class SampledFrame:
    """A single sampled frame handed to the motion stage."""

    index: int  #: Sampled-frame index (0-based, counts only sampled frames).
    source_frame: int  #: Frame index in the original video.
    timestamp: float  #: Seconds into the source video.
    frame: "cv2.typing.MatLike"  #: BGR frame at original resolution.


def iter_sampled_frames(
    info: VideoInfo, sample_fps: float
) -> Iterator[SampledFrame]:
    """Yield frames sampled at ~``sample_fps`` from the source video.

    We seek by source-frame index so the effective sample rate is honoured
    regardless of the source framerate. Frames are yielded at original
    resolution; downscaling for detection happens downstream so clip
    extraction can still use full resolution.
    """
    if info.fps <= 0:
        raise ValueError(
            f"Cannot sample {info.path}: source fps unknown/zero. "
            "Re-encode the file or set fps metadata."
        )
    # Stride in source frames between samples (>=1).
    stride = max(1, int(round(info.fps / float(sample_fps))))

    cap = cv2.VideoCapture(str(info.path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open video: {info.path}")
    try:
        sampled_index = 0
        source_frame = 0
        while True:
            # Grab-and-skip is faster and more robust across codecs than
            # CAP_PROP_POS_FRAMES seeking for sequential sampling.
            grabbed = cap.grab()
            if not grabbed:
                break
            if source_frame % stride == 0:
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    break
                yield SampledFrame(
                    index=sampled_index,
                    source_frame=source_frame,
                    timestamp=source_frame / info.fps,
                    frame=frame,
                )
                sampled_index += 1
            source_frame += 1
    finally:
        cap.release()


# --- ffprobe helpers (optional; degrade gracefully if absent) -------------
def _ffprobe_path() -> Optional[str]:
    return shutil.which("ffprobe")


def _ffprobe_fps(path: Path) -> Optional[float]:
    exe = _ffprobe_path()
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        token = out.stdout.strip()
        if "/" in token:
            num, den = token.split("/")
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(token) if token else None
    except (subprocess.SubprocessError, ValueError):
        return None


def _ffprobe_creation_time(path: Path) -> Optional[_dt.datetime]:
    exe = _ffprobe_path()
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout or "{}")
        tag = (data.get("format", {}).get("tags", {}) or {}).get("creation_time")
        if not tag:
            return None
        # ISO-8601, often with a trailing Z.
        return _dt.datetime.fromisoformat(tag.replace("Z", "+00:00"))
    except (subprocess.SubprocessError, ValueError, KeyError):
        return None
