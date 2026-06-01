"""Detector factory (SPEC §3 Step 4).

``get_detector`` maps a config detector name to an instance. Only the selected
detector is imported, so ``detector='none'`` (the v1 default) never pulls in
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
    options = dict(cfg.detector_options)
    if name == DETECTOR_NONE:
        from .none_detector import NoneDetector

        return NoneDetector(**options)
    if name == DETECTOR_GENERIC:
        from .generic_detector import GenericDetector

        return GenericDetector(**options)
    if name == DETECTOR_MARINE:
        from .marine_detector import MarineDetector

        return MarineDetector(**options)
    raise ValueError(f"Unknown detector: {name!r}")
