"""The ONNX Runtime backend: pre/post-processing, without a real model.

A fake session stands in for ONNX Runtime and returns hand-written raw output,
so these tests pin down the maths (letterbox, decode, NMS, mapping boxes back)
that has to match Ultralytics. Parity on real footage is checked separately by
scripts/check_onnx_parity.py.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from reefscanner.core import weights
from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.detectors import get_detector
from reefscanner.core.detectors.onnx import OnnxYoloDetector, decode, letterbox, nms


class FakeInput:
    name = "images"
    shape = [1, 3, 640, 640]


class FakeMeta:
    custom_metadata_map = {"names": "{0: 'elasmobranch', 1: 'fish'}", "imgsz": "[640, 640]"}


class FakeSession:
    """Returns fixed raw predictions, (1, 4 + n_classes, n_anchors)."""

    def __init__(self, preds: list[tuple[float, float, float, float, float, float]]) -> None:
        # Each pred: cx, cy, w, h (model input pixels), score class 0, score class 1.
        self.output = np.asarray(preds, dtype=np.float32).T[None]
        self.last_input = None

    def get_inputs(self) -> list[FakeInput]:
        return [FakeInput()]

    def get_modelmeta(self) -> FakeMeta:
        return FakeMeta()

    def run(self, _outputs: object, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.last_input = feeds["images"]
        return [self.output]


def make_detector(preds, **kwargs) -> OnnxYoloDetector:
    return OnnxYoloDetector(
        name="marine", weights="unused.onnx", session=FakeSession(preds), **kwargs
    )


def test_letterbox_pads_a_wide_frame_top_and_bottom() -> None:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    img, scale, (left, top) = letterbox(frame, (640, 640))
    assert img.shape == (640, 640, 3)
    assert scale == pytest.approx(0.5)
    assert (left, top) == (0, 140)
    # Padding is Ultralytics' grey, the picture itself untouched.
    assert img[0, 0].tolist() == [114, 114, 114]
    assert img[320, 320].tolist() == [0, 0, 0]


def test_input_is_rgb_chw_float_in_unit_range() -> None:
    frame = np.zeros((640, 640, 3), dtype=np.uint8)
    frame[..., 0] = 255  # blue channel in BGR
    det = make_detector([(320, 320, 10, 10, 0.0, 0.0)])
    det.detect(frame)
    blob = det._session.last_input
    assert blob.shape == (1, 3, 640, 640) and blob.dtype == np.float32
    assert blob[0, 2].max() == pytest.approx(1.0)  # blue ends up last (RGB)
    assert blob[0, 0].max() == pytest.approx(0.0)


def test_boxes_map_back_to_original_frame_coordinates() -> None:
    # A 1280x720 frame is scaled by 0.5 and padded 140 px at the top, so a box
    # centred at (320, 320) in model input is centred at (640, 360) originally.
    det = make_detector([(320, 320, 100, 50, 0.9, 0.0)], conf=0.2)
    [d] = det.detect(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert d.class_name == "elasmobranch"
    assert d.confidence == pytest.approx(0.9)
    assert d.bbox == (540, 310, 200, 100)  # x, y, w, h


def test_low_confidence_dropped_and_threshold_inclusive() -> None:
    det = make_detector(
        [(100, 100, 20, 20, 0.2, 0.0), (300, 300, 20, 20, 0.19, 0.0)], conf=0.2
    )
    found = det.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert [d.confidence for d in found] == [pytest.approx(0.2)]


def test_nms_merges_overlaps_within_a_class_but_not_across() -> None:
    preds = [
        (100, 100, 50, 50, 0.9, 0.0),  # kept
        (102, 102, 50, 50, 0.8, 0.0),  # same class, heavy overlap -> dropped
        (101, 101, 50, 50, 0.0, 0.7),  # other class, same place -> kept
        (400, 400, 50, 50, 0.6, 0.0),  # same class, elsewhere -> kept
    ]
    det = make_detector(preds, conf=0.2)
    found = det.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert sorted((d.class_name, round(d.confidence, 2)) for d in found) == [
        ("elasmobranch", 0.6), ("elasmobranch", 0.9), ("fish", 0.7),
    ]


def test_target_classes_filter_case_insensitively() -> None:
    preds = [(100, 100, 50, 50, 0.9, 0.0), (400, 400, 50, 50, 0.0, 0.9)]
    det = make_detector(preds, conf=0.2, target_classes=["Fish"])
    found = det.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert [d.class_name for d in found] == ["fish"]


def test_max_det_keeps_the_highest_scores() -> None:
    preds = [(50 + 60 * i, 50, 20, 20, 0.3 + 0.05 * i, 0.0) for i in range(8)]
    out = decode(
        np.asarray(preds, dtype=np.float32).T, conf=0.2, scale=1.0, pad=(0, 0),
        frame_shape=(640, 640, 3), max_det=3,
    )
    assert [round(s, 2) for _, s, _ in out] == [0.65, 0.6, 0.55]


def test_nms_on_identical_boxes_keeps_the_best() -> None:
    boxes = np.array([[0, 0, 10, 10], [0, 0, 10, 10]], dtype=np.float32)
    assert nms(boxes, np.array([0.5, 0.9]), iou=0.7).tolist() == [1]


def test_class_names_come_from_export_metadata() -> None:
    det = make_detector([(1, 1, 1, 1, 0.0, 0.0)])
    assert det.class_names == ["elasmobranch", "fish"]


# -- configuration and wiring -------------------------------------------------

def test_onnx_is_the_default_backend() -> None:
    assert ReefScannerConfig().detector_backend == "onnx"


def test_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError, match="detector_backend"):
        ReefScannerConfig(detector_backend="tflite")


def test_onnx_backend_rejects_a_pt_checkpoint_with_a_way_out() -> None:
    with pytest.raises(ValueError, match="export-onnx"):
        ReefScannerConfig(detector_weights="my-model.pt")


def test_sahi_needs_the_ultralytics_backend() -> None:
    with pytest.raises(ValueError, match="use_sahi"):
        ReefScannerConfig(use_sahi=True)
    ReefScannerConfig(use_sahi=True, detector_backend="ultralytics")


def test_marine_builds_the_onnx_detector_from_given_weights(monkeypatch) -> None:
    built = {}

    def fake_session(path: str, providers: list[str]) -> FakeSession:
        built["path"] = path
        return FakeSession([(1, 1, 1, 1, 0.0, 0.0)])

    import onnxruntime

    monkeypatch.setattr(onnxruntime, "InferenceSession", fake_session)
    det = get_detector(ReefScannerConfig(detector_weights="/models/shark.onnx"))
    assert isinstance(det, OnnxYoloDetector)
    assert det.name == "marine"
    assert built["path"] == "/models/shark.onnx"


def test_generic_on_onnx_needs_explicit_weights() -> None:
    with pytest.raises(ValueError, match="export-onnx"):
        get_detector(ReefScannerConfig(detector="generic"))


# -- where the SharkTrack ONNX model comes from -------------------------------

def test_sharktrack_onnx_comes_from_the_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REEFSCANNER_CACHE", str(tmp_path))
    cached = tmp_path / weights.SHARKTRACK_ONNX_FILENAME
    cached.write_bytes(b"model")
    assert weights.ensure_sharktrack_onnx() == str(cached)


def fake_download(monkeypatch: pytest.MonkeyPatch, payload: bytes | None) -> list[str]:
    """Stand in for urlretrieve: write ``payload``, or fail like a network error."""
    calls = []

    def retrieve(url, dest) -> None:
        calls.append(url)
        if payload is None:
            raise OSError("network unreachable")
        Path(dest).write_bytes(payload)

    monkeypatch.setattr(weights.urllib.request, "urlretrieve", retrieve)
    return calls


def test_sharktrack_onnx_downloads_the_published_export(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REEFSCANNER_CACHE", str(tmp_path))
    payload = b"onnx model"
    monkeypatch.setattr(
        weights, "SHARKTRACK_ONNX_SHA256", hashlib.sha256(payload).hexdigest()
    )
    calls = fake_download(monkeypatch, payload)

    path = weights.ensure_sharktrack_onnx()
    assert calls == [weights.SHARKTRACK_ONNX_URL]
    assert Path(path).read_bytes() == payload
    # Cached: a second call doesn't download again.
    assert weights.ensure_sharktrack_onnx() == path and len(calls) == 1


def test_sharktrack_onnx_with_a_wrong_hash_is_refused_and_not_kept(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("REEFSCANNER_CACHE", str(tmp_path))
    fake_download(monkeypatch, b"tampered")
    no_ultralytics(monkeypatch)

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        weights.ensure_sharktrack_onnx()
    assert list(tmp_path.iterdir()) == []


def test_sharktrack_onnx_download_failure_explains_how_to_get_it(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("REEFSCANNER_CACHE", str(tmp_path))
    fake_download(monkeypatch, None)
    no_ultralytics(monkeypatch)

    with pytest.raises(RuntimeError, match="export-onnx"):
        weights.ensure_sharktrack_onnx()


def test_sharktrack_onnx_falls_back_to_a_local_export(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REEFSCANNER_CACHE", str(tmp_path))
    fake_download(monkeypatch, None)
    monkeypatch.setattr(weights, "ensure_sharktrack_weights", lambda: "shark.pt")
    exported = {}

    def export(src: str, dest: Path, imgsz: int) -> str:
        exported.update(src=src, dest=dest, imgsz=imgsz)
        return str(dest)

    monkeypatch.setattr(weights, "export_onnx", export)
    path = weights.ensure_sharktrack_onnx()
    assert exported == {
        "src": "shark.pt", "dest": tmp_path / "sharktrack.onnx", "imgsz": 640,
    }
    assert path == str(tmp_path / "sharktrack.onnx")


def no_ultralytics(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: object, **kwargs: object) -> object:
        if name == "ultralytics":
            raise ImportError("no ultralytics here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)


def test_dynamic_models_pad_only_to_the_stride() -> None:
    """A 16:9 frame becomes 640x384, as Ultralytics runs a .pt — not 640x640."""
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img, scale, (left, top) = letterbox(frame, (640, 640), stride=32)
    assert img.shape == (384, 640, 3)
    assert (left, top) == (0, 12)


class FakeDynamicInput(FakeInput):
    shape = ["batch", 3, "height", "width"]


def test_detector_uses_stride_padding_for_a_dynamic_model() -> None:
    session = FakeSession([(1, 1, 1, 1, 0.0, 0.0)])
    session.get_inputs = lambda: [FakeDynamicInput()]
    det = OnnxYoloDetector(name="marine", weights="unused.onnx", session=session)
    det.detect(np.zeros((1080, 1920, 3), dtype=np.uint8))
    assert session.last_input.shape == (1, 3, 384, 640)
