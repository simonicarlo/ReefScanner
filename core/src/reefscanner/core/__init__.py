"""ReefScanner core — the headless detection engine.

Everything in this package is UI-agnostic: it reads video, surfaces "worth a
look" moments, and writes clips/thumbnails/CSV. The field app
(``reefscanner.app``, ``reefscanner.desktop``) and the on-rig agent
(``reefscanner.edge``) drive it, but core never imports from them, so the CLI
and the library API work with no web dependencies installed.

The detector (``marine`` or ``generic``) scans every sampled frame and is the
recall source, chosen by ``ReefScannerConfig.detector``. Motion (``MotionGate``)
survives only as an optional cheap pre-skip of dead-static frames
(``motion_prefilter``), not as a recall source of its own.

    from reefscanner.core import ReefScannerConfig, process_folder
    cfg = ReefScannerConfig(input_folder="~/footage", output_folder="~/results")
    batch = process_folder(cfg)

See ``reefscanner.core.cli`` for the command line: ``process``, ``report``,
``serve``, ``desktop``, ``export-onnx``.
"""

from __future__ import annotations

from .config import (
    DEFAULT_EXTENSIONS,
    DETECTOR_GENERIC,
    DETECTOR_MARINE,
    VALID_DETECTORS,
    ReefScannerConfig,
)
from .detection import Detection
from .discovery import discover_videos
from .events import Candidate, Event, aggregate_events
from .manifest import Manifest
from .motion import MotionGate
from .pipeline import (
    BatchResult,
    JobCancelled,
    VideoResult,
    process_folder,
    process_video,
)
from .results import CSV_COLUMNS, CsvWriter, event_to_row
from .videoio import VideoInfo, probe_video

__version__ = "3.0.0.dev0"

__all__ = [
    "__version__",
    "ReefScannerConfig",
    "DEFAULT_EXTENSIONS",
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
    "Candidate",
    "Detection",
    "Event",
    "aggregate_events",
    "Manifest",
    "CSV_COLUMNS",
    "CsvWriter",
    "event_to_row",
]
