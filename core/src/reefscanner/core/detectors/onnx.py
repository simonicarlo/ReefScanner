"""ONNX Runtime YOLO detector — the default backend (v3).

Runs a YOLOv8-style detection model exported to ONNX, with no torch and no
Ultralytics at runtime. That is what lets the same detector run on a laptop and
on an edge board: every board runtime (TensorRT, Hailo, RKNN) starts from the
same ONNX export, and ONNX Runtime itself runs anywhere with a CPU.

Pre- and post-processing mirror Ultralytics' own, so a model gives the same
detections here as through ``UltralyticsYoloDetector``:

* **Letterbox** — resize keeping aspect ratio so the long side fits the model
  size (640 for SharkTrack), then pad with grey (114), centred. A model
  exported with a dynamic input is padded only up to a multiple of its stride
  (a 16:9 frame becomes 640x384), exactly as Ultralytics runs a ``.pt``; a
  fixed-shape export, as board runtimes need, is padded to that shape.
* **Decode** — the output is ``(1, 4 + n_classes, n_anchors)``: centre-x,
  centre-y, width, height in input pixels, then one score per class. Each
  anchor takes its best class.
* **NMS** — per class, IoU 0.7 (Ultralytics' default), at most 300 boxes.

Recall-first, like the other backends: a low confidence threshold and no class
filter unless one is asked for.
"""

from __future__ import annotations

import ast
import logging
from typing import Sequence

import cv2
import numpy as np

from ..detection import Detection

logger = logging.getLogger("reefscanner")

#: Ultralytics' defaults, kept so both backends agree.
DEFAULT_IOU = 0.7
DEFAULT_MAX_DET = 300
PAD_VALUE = 114


def default_providers() -> list[str]:
    """Execution providers to try, best first, among those installed.

    CPU is always last, so a provider that fails to load a model still leaves
    one that works. CoreML is left out: with SharkTrack's dynamic input it was
    slower than the CPU on an M2 (26 vs 23 ms a frame) and shifts boxes by a
    pixel or two. Ask for it with ``detector_options={"providers": [...]}``.
    """
    import onnxruntime as ort  # type: ignore

    preferred = [
        "TensorrtExecutionProvider",
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    available = set(ort.get_available_providers())
    return [p for p in preferred if p in available] or ["CPUExecutionProvider"]


def letterbox(
    frame: np.ndarray, size: tuple[int, int], stride: int | None = None
) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Resize ``frame`` into ``size`` (h, w) keeping aspect ratio, padding the rest.

    With ``stride``, pad only up to the next multiple of it instead of all the
    way to ``size`` — for models that accept any input shape.

    Returns the padded image, the scale applied, and the (left, top) padding —
    what ``decode`` needs to map boxes back onto the original frame.
    """
    h, w = frame.shape[:2]
    new_h, new_w = size
    r = min(new_h / h, new_w / w)
    unpad_w, unpad_h = int(round(w * r)), int(round(h * r))
    if (unpad_w, unpad_h) != (w, h):
        frame = cv2.resize(frame, (unpad_w, unpad_h), interpolation=cv2.INTER_LINEAR)
    dw, dh = new_w - unpad_w, new_h - unpad_h
    if stride:
        dw, dh = dw % stride, dh % stride
    dw, dh = dw / 2, dh / 2
    # The ±0.1 splits an odd pixel of padding the same way Ultralytics does.
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    padded = cv2.copyMakeBorder(
        frame, top, bottom, left, right, cv2.BORDER_CONSTANT,
        value=(PAD_VALUE, PAD_VALUE, PAD_VALUE),
    )
    return padded, r, (left, top)


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> np.ndarray:
    """Greedy non-maximum suppression over xyxy boxes; indices of the kept ones."""
    order = np.argsort(-scores, kind="stable")
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    keep: list[int] = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        overlap = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[overlap <= iou]
    return np.asarray(keep, dtype=np.int64)


def decode(
    output: np.ndarray,
    *,
    conf: float,
    scale: float,
    pad: tuple[int, int],
    frame_shape: tuple[int, ...],
    iou: float = DEFAULT_IOU,
    max_det: int = DEFAULT_MAX_DET,
) -> list[tuple[np.ndarray, float, int]]:
    """Turn raw model output into (xyxy box, score, class id) on the original frame.

    ``output`` is one image's predictions, ``(4 + n_classes, n_anchors)``.
    """
    preds = output.T
    class_scores = preds[:, 4:]
    class_ids = class_scores.argmax(axis=1)
    scores = class_scores[np.arange(len(preds)), class_ids]
    mask = scores >= conf
    if not mask.any():
        return []
    preds, scores, class_ids = preds[mask], scores[mask], class_ids[mask]

    cx, cy, bw, bh = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)

    # Per-class NMS by shifting each class into its own coordinate range, the
    # same trick Ultralytics uses: boxes of different classes can never overlap.
    offsets = class_ids[:, None].astype(boxes.dtype) * 7680.0
    keep = nms(boxes + offsets, scores, iou)[:max_det]

    left, top = pad
    h, w = frame_shape[:2]
    boxes = boxes[keep]
    boxes[:, [0, 2]] = ((boxes[:, [0, 2]] - left) / scale).clip(0, w)
    boxes[:, [1, 3]] = ((boxes[:, [1, 3]] - top) / scale).clip(0, h)
    return [
        (boxes[k], float(scores[i]), int(class_ids[i]))
        for k, i in enumerate(keep)
    ]


def _xyxy_to_xywh(box: np.ndarray) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (float(v) for v in box)
    return (int(round(x1)), int(round(y1)), int(round(x2 - x1)), int(round(y2 - y1)))


class OnnxYoloDetector:
    """Run a YOLO detection model exported to ONNX, frame by frame."""

    def __init__(
        self,
        name: str,
        weights: str,
        conf: float = 0.25,
        target_classes: Sequence[str] | None = None,
        iou: float = DEFAULT_IOU,
        max_det: int = DEFAULT_MAX_DET,
        providers: Sequence[str] | None = None,
        session=None,
        **_options,
    ) -> None:
        if session is None:
            try:
                import onnxruntime as ort  # type: ignore
            except ImportError as exc:  # pragma: no cover - core dependency
                raise ImportError(
                    "detector_backend='onnx' needs onnxruntime: "
                    "pip install onnxruntime"
                ) from exc
            session = ort.InferenceSession(
                weights, providers=list(providers or default_providers())
            )
        self._session = session

        self.name = name
        self.conf = conf
        self.iou = iou
        self.max_det = max_det
        self._targets = (
            {c.lower() for c in target_classes} if target_classes else None
        )

        model_input = session.get_inputs()[0]
        self._input_name = model_input.name
        meta = session.get_modelmeta().custom_metadata_map
        self._size = _input_size(model_input.shape, meta)
        # A dynamic input takes any shape the stride divides, so only pad that far.
        dynamic = not all(isinstance(d, int) for d in model_input.shape[2:4])
        self._stride = int(meta.get("stride", 32)) if dynamic else None
        self.class_names = _class_names(meta)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        img, scale, pad = letterbox(frame, self._size, self._stride)
        # BGR -> RGB, HWC -> CHW, uint8 -> float in [0, 1].
        blob = np.ascontiguousarray(img[:, :, ::-1].transpose(2, 0, 1))[None]
        blob = blob.astype(np.float32) / 255.0
        output = self._session.run(None, {self._input_name: blob})[0][0]

        out: list[Detection] = []
        for box, score, cls in decode(
            output, conf=self.conf, scale=scale, pad=pad,
            frame_shape=frame.shape, iou=self.iou, max_det=self.max_det,
        ):
            cls_name = self.class_names[cls] if cls < len(self.class_names) else str(cls)
            if self._targets is not None and cls_name.lower() not in self._targets:
                continue
            out.append(
                Detection(bbox=_xyxy_to_xywh(box), class_name=cls_name, confidence=score)
            )
        return out


def _input_size(shape: Sequence, meta: dict[str, str]) -> tuple[int, int]:
    """The model's (h, w) input size: from the graph if fixed, else its metadata."""
    h, w = shape[2], shape[3]
    if isinstance(h, int) and isinstance(w, int):
        return h, w
    if "imgsz" in meta:
        size = ast.literal_eval(meta["imgsz"])
        return (size, size) if isinstance(size, int) else (int(size[0]), int(size[1]))
    return 640, 640


def _class_names(meta: dict[str, str]) -> list[str]:
    """Class names from the metadata Ultralytics writes into an export."""
    raw = meta.get("names")
    if not raw:
        return []
    names = ast.literal_eval(raw)  # "{0: 'elasmobranch'}"
    if isinstance(names, dict):
        return [str(names[k]) for k in sorted(names)]
    return [str(n) for n in names]
