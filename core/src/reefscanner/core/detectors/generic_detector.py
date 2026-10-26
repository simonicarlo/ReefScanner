"""Experimental ``generic`` detector (SPEC §3 Step 4).

Runs a stock COCO-pretrained YOLO as a coarse objectness proposer. COCO has NO
shark/ray/whale classes, so this can only ever flag generic "object-like"
things and will suffer severe underwater domain shift.

⚠️ Expect it to *hurt* recall on underwater footage — provided only for
experimentation. For real use, prefer ``detector='marine'`` with SharkTrack /
fine-tuned weights.
"""

from __future__ import annotations

from ..config import BACKEND_ONNX, ReefScannerConfig
from .base import Detector


def build_generic(cfg: ReefScannerConfig) -> Detector:
    opts = dict(cfg.detector_options)

    if cfg.detector_backend == BACKEND_ONNX:
        from .onnx import OnnxYoloDetector

        weights = cfg.detector_weights or opts.pop("weights", None)
        opts.pop("weights", None)
        if not weights:
            raise ValueError(
                "detector='generic' on the onnx backend needs an exported model: "
                "run `reefscanner export-onnx --weights yolov8n.pt --out "
                "yolov8n.onnx` and set detector_weights to it, or use "
                "detector_backend='ultralytics'."
            )
        return OnnxYoloDetector(
            name="generic",
            weights=weights,
            conf=cfg.ml_confidence_threshold,
            target_classes=cfg.target_classes,  # None = keep all (objectness proposer)
            **opts,
        )

    from .yolo import UltralyticsYoloDetector

    weights = cfg.detector_weights or opts.pop("weights", "yolov8n.pt")
    opts.pop("weights", None)
    return UltralyticsYoloDetector(
        name="generic",
        weights=weights,  # Ultralytics auto-downloads this on first use
        conf=cfg.ml_confidence_threshold,
        target_classes=cfg.target_classes,  # None = keep all (objectness proposer)
        imgsz=opts.pop("imgsz", None),
        device=opts.pop("device", None),
        use_sahi=cfg.use_sahi,
        sahi_slice_height=cfg.sahi_slice_height,
        sahi_slice_width=cfg.sahi_slice_width,
        sahi_overlap=cfg.sahi_overlap,
        **opts,
    )
