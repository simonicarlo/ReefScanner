"""The ``marine`` detector — the real v2 ML path (SPEC §3 Step 4, §10).

Loads a marine-megafauna detector into the YOLO wrapper. The recommended weights
are **SharkTrack** (YOLOv8, single `elasmobranch` class, trained on real BRUVS,
MIT-licensed) — see ``docs/model-research.md``. Any Ultralytics-compatible
`.pt` (e.g. a model fine-tuned on our own footage — the §10 data factory) drops
in the same way.

Weights are NOT bundled. Point ``detector_weights`` (or
``detector_options['weights']``) at a local/Drive path to a SharkTrack /
fine-tuned `.pt`. In Colab, download SharkTrack's release weights to Drive and
set the path there.
"""

from __future__ import annotations

from ..config import ReefScannerConfig
from .yolo import UltralyticsYoloDetector


def build_marine(cfg: ReefScannerConfig) -> UltralyticsYoloDetector:
    opts = dict(cfg.detector_options)
    weights = cfg.detector_weights or opts.pop("weights", None)
    if not weights:
        raise ValueError(
            "detector='marine' needs weights. Set config.detector_weights (or "
            "detector_options['weights']) to a SharkTrack / fine-tuned YOLO .pt "
            "path. SharkTrack: https://github.com/filippovarini/sharktrack "
            "(see docs/model-research.md)."
        )
    opts.pop("weights", None)
    return UltralyticsYoloDetector(
        name="marine",
        weights=weights,
        # Recall-first: keep the threshold low and all classes by default. A
        # false positive costs ~10s of triage; a missed animal is expensive.
        conf=cfg.ml_confidence_threshold,
        target_classes=cfg.target_classes,
        imgsz=opts.pop("imgsz", None),
        device=opts.pop("device", None),
        use_sahi=cfg.use_sahi,
        sahi_slice_height=cfg.sahi_slice_height,
        sahi_slice_width=cfg.sahi_slice_width,
        sahi_overlap=cfg.sahi_overlap,
        **opts,
    )
