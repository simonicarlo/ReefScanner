"""ReefScanner analysis engine — the headless video-processing core.

Everything in this subpackage is UI-agnostic: it reads video files, surfaces
"worth a look" moments, and writes clips/thumbnails/CSV. The desktop app
(``reefscanner.app``, ``reefscanner.desktop``) drives it but the engine never
imports from them, so the CLI and the library API work with no web deps
installed.

Two recall sources, chosen by ``ReefScannerConfig.detector``:
  * ``none`` — motion-only background subtraction (no ML deps).
  * ``marine`` / ``generic`` — a YOLO detector scans every sampled frame.

The public names are re-exported from the top-level ``reefscanner`` package, so
``from reefscanner import ReefScannerConfig, process_folder`` keeps working.
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
from .manifest import Manifest
from .motion import MotionGate
from .pipeline import (
    BatchResult,
    JobCancelled,
    VideoResult,
    process_folder,
    process_video,
)
from .report import FpReport, fp_report
from .results import CSV_COLUMNS, CsvWriter, event_to_row
from .videoio import VideoInfo, probe_video

__all__ = [
    "ReefScannerConfig",
    "DEFAULT_EXTENSIONS",
    "DETECTOR_NONE",
    "DETECTOR_GENERIC",
    "DETECTOR_MARINE",
    "VALID_DETECTORS",
    "process_folder",
    "process_video",
    "BatchResult",
    "JobCancelled",
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
    "Manifest",
    "CSV_COLUMNS",
    "CsvWriter",
    "event_to_row",
    "fp_report",
    "FpReport",
]
