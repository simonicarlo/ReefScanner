"""ReefScanner — a local desktop app for triaging static-camera (BRUV) video.

Long underwater recordings are mostly empty water. ReefScanner watches them for
you, surfaces the moments worth a look, and gives you a review UI to mark each
one true/false positive and tag the species — so you watch minutes instead of
hours, and every reviewed event becomes labeled training data for a better
detector later.

The package has three layers:

* ``reefscanner.engine`` — the headless analysis core (motion gate + pluggable
  YOLO detectors, clip/thumbnail extraction, CSV export). No web dependencies.
* ``reefscanner.app`` — the local FastAPI service and SQLite state store that
  the review UI talks to.
* ``reefscanner.desktop`` — the PyWebView shell that wraps the service in a
  native window.

Library entry points (unchanged since v1 — the engine move is transparent):

    from reefscanner import ReefScannerConfig, process_folder
    cfg = ReefScannerConfig(input_folder="~/footage", output_folder="~/results")
    batch = process_folder(cfg)

See ``reefscanner.cli`` for the command line: ``process``, ``report``,
``serve``, ``desktop``.
"""

from __future__ import annotations

from .engine import (
    CSV_COLUMNS,
    DEFAULT_EXTENSIONS,
    DETECTOR_GENERIC,
    DETECTOR_MARINE,
    DETECTOR_NONE,
    VALID_DETECTORS,
    BatchResult,
    Candidate,
    CsvWriter,
    Detection,
    Event,
    FpReport,
    Manifest,
    MotionCandidate,
    MotionGate,
    ReefScannerConfig,
    VideoInfo,
    VideoResult,
    aggregate_events,
    discover_videos,
    event_to_row,
    fp_report,
    probe_video,
    process_folder,
    process_video,
)

__version__ = "2.0.0.dev0"

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
    "Manifest",
    "CSV_COLUMNS",
    "CsvWriter",
    "event_to_row",
    "fp_report",
    "FpReport",
]
