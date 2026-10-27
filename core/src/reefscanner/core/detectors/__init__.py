"""Detector factory.

Only the selected detector's dependencies are imported, so building a config
never costs a torch import until a detector is actually constructed.
"""

from __future__ import annotations

from ..config import BACKEND_ONNX, DETECTOR_GENERIC, DETECTOR_MARINE, ReefScannerConfig
from .base import Detector

__all__ = ["Detector", "describe_model", "get_detector"]


def describe_model(cfg: ReefScannerConfig) -> tuple[str, str]:
    """(name, version) of the model a scan with ``cfg`` runs, for provenance."""
    from pathlib import Path

    weights = cfg.detector_weights or cfg.detector_options.get("weights")
    if weights:
        return Path(weights).stem, Path(weights).name
    if cfg.detector == DETECTOR_MARINE:
        # The ONNX export is the one published as the models-v1 release.
        onnx = cfg.detector_backend == BACKEND_ONNX
        return "SharkTrack", "models-v1" if onnx else "sharktrack.pt"
    return "yolov8n", "yolov8n.pt"


def get_detector(cfg: ReefScannerConfig) -> Detector:
    name = cfg.detector
    if name == DETECTOR_MARINE:
        from .marine_detector import build_marine

        detector = build_marine(cfg)
    elif name == DETECTOR_GENERIC:
        from .generic_detector import build_generic

        detector = build_generic(cfg)
    else:
        raise ValueError(f"Unknown detector: {name!r}")

    # The ultralytics backend tiles through the sahi package itself (the
    # reference); every other backend through core's own tiling.
    if cfg.use_sahi and cfg.detector_backend == BACKEND_ONNX:
        from .tiling import TiledDetector

        detector = TiledDetector(
            detector,
            slice_height=cfg.sahi_slice_height,
            slice_width=cfg.sahi_slice_width,
            overlap=cfg.sahi_overlap,
        )
    return detector
