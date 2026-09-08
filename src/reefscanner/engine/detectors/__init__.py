"""Detector factory (SPEC §3 Step 4).

``get_detector`` maps a config detector name to an instance. Only the selected
detector's dependencies are imported, so ``detector='none'`` never pulls in
torch/ultralytics (SPEC §8.5).
"""

from __future__ import annotations

from ..config import (
    DETECTOR_GENERIC,
    DETECTOR_MARINE,
    DETECTOR_NONE,
    ReefScannerConfig,
)
from .base import Detector

__all__ = ["Detector", "get_detector"]


def get_detector(cfg: ReefScannerConfig) -> Detector:
    name = cfg.detector
    if name == DETECTOR_NONE:
        from .none_detector import NoneDetector

        return NoneDetector(**cfg.detector_options)
    if name == DETECTOR_MARINE:
        from .marine_detector import build_marine

        return build_marine(cfg)
    if name == DETECTOR_GENERIC:
        from .generic_detector import build_generic

        return build_generic(cfg)
    raise ValueError(f"Unknown detector: {name!r}")
