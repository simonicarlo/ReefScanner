"""SAHI-style tiled inference around any detector.

Small, distant animals shrink to a few pixels once a 1080p frame is scaled
down to the model's 640 px input. Running the detector on overlapping tiles as
well finds them at a scale it can see (the missed-distant-shark failure mode).

This mirrors ``sahi.predict.get_sliced_prediction`` (0.12) with its defaults,
so the Ultralytics backend running ``sahi`` itself serves as the reference
(``scripts/check_onnx_parity.py --sahi``). It needs only NumPy, so it runs on
the rig with any backend. Design:
docs/specs/v3/features/2026-10-27-onnx-sahi-design.md.
"""

from __future__ import annotations

import numpy as np

from ..detection import Detection
from .base import Detector

#: ``sahi``'s defaults: merge boxes covering half of the smaller one.
MATCH_THRESHOLD = 0.5
#: Below this confidence ``sahi`` suppresses (NMS on IoU) instead of merging,
#: since merging many weak boxes inflates them.
LOW_CONFIDENCE = 0.1


def slice_boxes(
    height: int, width: int, slice_height: int, slice_width: int, overlap: float
) -> list[tuple[int, int, int, int]]:
    """Tiles covering the frame, as (x1, y1, x2, y2); ``sahi``'s ``get_slice_bboxes``.

    Tiles step by the slice size less the overlap. One that would run past an
    edge is moved back inside, so every tile is full-size (unless the frame is
    smaller than a tile).
    """
    y_overlap = int(overlap * slice_height)
    x_overlap = int(overlap * slice_width)
    boxes = []
    y_min = y_max = 0
    while y_max < height:
        x_min = x_max = 0
        y_max = y_min + slice_height
        while x_max < width:
            x_max = x_min + slice_width
            if y_max > height or x_max > width:
                x_max = min(width, x_max)
                y_max = min(height, y_max)
                x_min = max(0, x_max - slice_width)
                y_min = max(0, y_max - slice_height)
            boxes.append((x_min, y_min, x_max, y_max))
            x_min = x_max - x_overlap
        y_min = y_max - y_overlap
    return boxes


def _xyxy(d: Detection) -> np.ndarray:
    x, y, w, h = d.bbox
    return np.array([x, y, x + w, y + h], dtype=np.float64)


def _area(b: np.ndarray) -> float:
    return float((b[2] - b[0]) * (b[3] - b[1]))


def _intersection(a: np.ndarray, b: np.ndarray) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return float(max(w, 0) * max(h, 0))


def _overlap(a: np.ndarray, b: np.ndarray, metric: str) -> float:
    inter = _intersection(a, b)
    if metric == "IOS":
        smaller = min(_area(a), _area(b))
        return inter / smaller if smaller > 0 else 0.0
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _by_score(dets: list[Detection]) -> list[int]:
    """Indices by score, highest first; ties broken by position as ``sahi`` does."""
    boxes = np.array([_xyxy(d) for d in dets])
    scores = np.array([d.confidence for d in dets])
    return np.lexsort(
        (boxes[:, 3], boxes[:, 2], boxes[:, 1], boxes[:, 0], -scores)
    ).tolist()


def greedy_merge(dets: list[Detection], threshold: float = MATCH_THRESHOLD) -> list[Detection]:
    """``sahi``'s greedy non-maximum merging (IoS), within one class.

    Each box, by score, absorbs the not-yet-absorbed lower-scored boxes it
    overlaps by ``threshold`` or more. An absorbed box widens the kept one to
    their union only if it still overlaps the (possibly grown) kept box by more
    than ``threshold``; the merged score is the higher one.
    """
    if not dets:
        return []
    order = _by_score(dets)
    boxes = [_xyxy(d) for d in dets]
    absorbed: set[int] = set()
    out = []
    for n, i in enumerate(order):
        if i in absorbed:
            continue
        merge = [
            j for j in order[n + 1:]
            if j not in absorbed and _overlap(boxes[i], boxes[j], "IOS") >= threshold
        ]
        absorbed.update(merge)
        box, score = boxes[i].copy(), dets[i].confidence
        for j in merge:
            if _overlap(box, boxes[j], "IOS") > threshold:
                box = np.concatenate([np.minimum(box[:2], boxes[j][:2]),
                                      np.maximum(box[2:], boxes[j][2:])])
                score = max(score, dets[j].confidence)
        x1, y1, x2, y2 = (int(round(v)) for v in box)
        out.append(Detection(bbox=(x1, y1, x2 - x1, y2 - y1),
                             class_name=dets[i].class_name, confidence=score))
    return out


def suppress(dets: list[Detection], threshold: float = MATCH_THRESHOLD) -> list[Detection]:
    """Plain NMS on IoU within one class: what ``sahi`` does at low confidence."""
    boxes = [_xyxy(d) for d in dets]
    keep: list[int] = []
    for i in _by_score(dets) if dets else []:
        if all(_overlap(boxes[i], boxes[k], "IOU") <= threshold for k in keep):
            keep.append(i)
    return [dets[i] for i in keep]


class TiledDetector:
    """Runs ``inner`` on overlapping tiles and the whole frame, then merges."""

    def __init__(
        self,
        inner: Detector,
        slice_height: int = 512,
        slice_width: int = 512,
        overlap: float = 0.2,
    ) -> None:
        self._inner = inner
        self.name = inner.name
        self.class_names = inner.class_names
        self.slice_height = slice_height
        self.slice_width = slice_width
        self.overlap = overlap
        conf = getattr(inner, "conf", None)
        self._merge = suppress if conf is not None and conf < LOW_CONFIDENCE else greedy_merge

    def detect(self, frame: np.ndarray) -> list[Detection]:
        h, w = frame.shape[:2]
        tiles = slice_boxes(h, w, self.slice_height, self.slice_width, self.overlap)
        found: list[Detection] = []
        for x1, y1, x2, y2 in tiles:
            for d in self._inner.detect(frame[y1:y2, x1:x2]):
                x, y, bw, bh = d.bbox
                if bw <= 0 or bh <= 0:
                    continue  # clipped flat at the tile's edge; sahi drops these
                found.append(Detection(bbox=(x + x1, y + y1, bw, bh),
                                       class_name=d.class_name, confidence=d.confidence))
        # The whole frame too, so an animal larger than a tile is found whole.
        if len(tiles) > 1:
            found += self._inner.detect(frame)

        by_class: dict[str, list[Detection]] = {}
        for d in found:
            by_class.setdefault(d.class_name, []).append(d)
        merged = [m for dets in by_class.values() for m in self._merge(dets)]
        return sorted(merged, key=lambda d: -d.confidence)
