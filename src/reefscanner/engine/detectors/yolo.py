"""Ultralytics YOLO detector wrapper (v2, SPEC §3 Step 4).

Backs both the ``marine`` detector (SharkTrack / fine-tuned megafauna weights)
and the experimental ``generic`` detector (stock COCO weights as a coarse
objectness proposer). Heavy imports (ultralytics/torch, sahi) are deferred to
construction so importing this module never requires them.

Recall-first by design: a low confidence threshold and no class filter keep
borderline animals for human triage. Optional SAHI tiled inference improves
recall on distant/small animals (the missed-distant-shark failure mode).
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import numpy as np

from ..detection import Detection

logger = logging.getLogger("reefscanner")


def _xyxy_to_xywh(x1: float, y1: float, x2: float, y2: float) -> tuple[int, int, int, int]:
    return (int(round(x1)), int(round(y1)), int(round(x2 - x1)), int(round(y2 - y1)))


class UltralyticsYoloDetector:
    """Run an Ultralytics YOLO model frame-by-frame, optionally tiled via SAHI."""

    def __init__(
        self,
        name: str,
        weights: str,
        conf: float = 0.25,
        target_classes: Optional[Sequence[str]] = None,
        imgsz: Optional[int] = None,
        device: Optional[str] = None,
        use_sahi: bool = False,
        sahi_slice_height: int = 512,
        sahi_slice_width: int = 512,
        sahi_overlap: float = 0.2,
        **_options,
    ) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                f"detector={name!r} requires the optional 'ml' extra: "
                "pip install 'reefscanner[ml]' (or `pip install ultralytics`). "
                "The v1 default detector='none' needs no ML dependencies."
            ) from exc

        self.name = name
        self.conf = conf
        self.imgsz = imgsz
        self.device = device
        #: lower-cased target class names to keep, or None to keep all (recall).
        self._targets = (
            {c.lower() for c in target_classes} if target_classes else None
        )

        self._model = YOLO(weights)
        names = getattr(self._model, "names", {}) or {}
        self.class_names = [str(v) for v in (names.values() if isinstance(names, dict) else names)]

        self._sahi = None
        if use_sahi:
            self._sahi = self._build_sahi(weights, conf, device)
            self._sahi_kwargs = dict(
                slice_height=sahi_slice_height,
                slice_width=sahi_slice_width,
                overlap_height_ratio=sahi_overlap,
                overlap_width_ratio=sahi_overlap,
            )

    def _build_sahi(self, weights: str, conf: float, device):
        try:
            from sahi import AutoDetectionModel  # type: ignore

            return AutoDetectionModel.from_pretrained(
                model_type="ultralytics",
                model_path=weights,
                confidence_threshold=conf,
                device=device,
            )
        except ImportError:  # pragma: no cover - optional dep
            logger.warning(
                "use_sahi=True but 'sahi' is not installed; falling back to "
                "plain inference. Install with `pip install sahi` for tiled "
                "small-object detection."
            )
            return None

    def _keep(self, class_name: str) -> bool:
        return self._targets is None or class_name.lower() in self._targets

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._sahi is not None:
            return self._detect_sahi(frame)
        return self._detect_plain(frame)

    def _detect_plain(self, frame: np.ndarray) -> list[Detection]:
        kwargs = {"conf": self.conf, "verbose": False}
        if self.imgsz:
            kwargs["imgsz"] = self.imgsz
        if self.device:
            kwargs["device"] = self.device
        results = self._model.predict(frame, **kwargs)

        out: list[Detection] = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            names = r.names if getattr(r, "names", None) else {}
            for xyxy, conf, cls in zip(
                boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()
            ):
                cls_name = str(names.get(int(cls), int(cls)))
                if not self._keep(cls_name):
                    continue
                out.append(
                    Detection(
                        bbox=_xyxy_to_xywh(*xyxy),
                        class_name=cls_name,
                        confidence=float(conf),
                    )
                )
        return out

    def _detect_sahi(self, frame: np.ndarray) -> list[Detection]:
        from sahi.predict import get_sliced_prediction  # type: ignore

        result = get_sliced_prediction(
            frame, self._sahi, verbose=0, **self._sahi_kwargs
        )
        out: list[Detection] = []
        for obj in result.object_prediction_list:
            cls_name = str(obj.category.name)
            if not self._keep(cls_name):
                continue
            box = obj.bbox  # minx, miny, maxx, maxy
            out.append(
                Detection(
                    bbox=_xyxy_to_xywh(box.minx, box.miny, box.maxx, box.maxy),
                    class_name=cls_name,
                    confidence=float(obj.score.value),
                )
            )
        return out
