"""Experimental ``generic`` detector (SPEC §3 Step 4).

Runs a pretrained COCO/YOLO detector as a coarse "large animal-like object
present?" confirmer using *objectness / large-object* heuristics, NOT class
labels (COCO has no shark/ray classes). Off by default.

⚠️ Expect this to *hurt* recall on underwater footage (severe domain shift).
Provided only for experimentation. The heavy ``ultralytics`` import is
deferred to ``__init__`` so importing this module never requires torch.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..motion import MotionCandidate


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2, bx2, by2 = ax + aw, ay + ah, bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class GenericDetector:
    name = "generic"

    def __init__(
        self,
        model: str = "yolov8n.pt",
        iou_match: float = 0.1,
        **_options,
    ) -> None:
        # Deferred heavy import: only paid when detector=generic is selected.
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise ImportError(
                "detector='generic' requires the optional 'ml' extra: "
                "pip install 'reefscanner[ml]'"
            ) from exc
        self._model = YOLO(model)
        self._iou_match = iou_match

    def confirm(
        self, frame: np.ndarray, candidate: MotionCandidate
    ) -> Optional[float]:
        """Confidence that *some* sizeable object overlaps the motion bbox.

        We ignore class labels entirely and use the detector purely as an
        objectness prior: the best-overlapping detection's confidence.
        """
        results = self._model.predict(frame, verbose=False)
        best = 0.0
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            for xyxy, conf in zip(
                boxes.xyxy.tolist(), boxes.conf.tolist()
            ):
                x1, y1, x2, y2 = xyxy
                det = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
                if _iou(candidate.bbox, det) >= self._iou_match:
                    best = max(best, float(conf))
        return best
