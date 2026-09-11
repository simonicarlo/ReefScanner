"""Detector factory.

Only the selected detector's dependencies are imported, so building a config
never costs a torch import until a detector is actually constructed.
"""

from __future__ import annotations

from ..config import DETECTOR_GENERIC, DETECTOR_MARINE, ReefScannerConfig
from .base import Detector

__all__ = ["Detector", "get_detector"]


def get_detector(cfg: ReefScannerConfig) -> Detector:
    name = cfg.detector
    if name == DETECTOR_MARINE:
        from .marine_detector import build_marine

        return build_marine(cfg)
    if name == DETECTOR_GENERIC:
        from .generic_detector import build_generic

        return build_generic(cfg)
    raise ValueError(f"Unknown detector: {name!r}")
