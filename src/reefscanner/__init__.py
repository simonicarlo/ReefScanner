"""ReefScanner — recall-oriented motion triage for static-camera (BRUV) video.

v1 is deliberately motion-only (no ML): it surfaces "worth a look" moments from
long underwater videos so a human watches minutes instead of hours, and every
emitted event doubles as a pre-labeled training candidate for a future
fine-tuned detector (SPEC §10).

Library entry points:

    from reefscanner import ReefScannerConfig, process_folder
    cfg = ReefScannerConfig(input_folder="/drive/in", output_folder="/drive/out")
    batch = process_folder(cfg)

See ``reefscanner.cli`` for the command-line interface.
"""

from __future__ import annotations

from .config import (
    DEFAULT_EXTENSIONS,
    DETECTOR_GENERIC,
    DETECTOR_MARINE,
    DETECTOR_NONE,
    VALID_DETECTORS,
    ReefScannerConfig,
)
from .detection import Detection
from .discovery import discover_videos
from .events import Candidate, Event, MotionCandidate, aggregate_events
from .motion import MotionGate
from .pipeline import BatchResult, VideoResult, process_folder, process_video
from .report import FpReport, fp_report
from .videoio import VideoInfo, probe_video

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "ReefScannerConfig",
    "DEFAULT_EXTENSIONS",
    "DETECTOR_NONE",
    "DETECTOR_GENERIC",
    "DETECTOR_MARINE",
    "VALID_DETECTORS",
    "process_folder",
    "process_video",
    "BatchResult",
    "VideoResult",
    "discover_videos",
    "probe_video",
    "VideoInfo",
    "MotionGate",
    "MotionCandidate",
    "Candidate",
    "Detection",
    "Event",
    "aggregate_events",
    "fp_report",
    "FpReport",
]
