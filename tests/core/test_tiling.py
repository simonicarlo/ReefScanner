"""SAHI-style tiling around a detector, with no model and no sahi needed.

Where the ``sahi`` package is installed (the dev install has it), the tile
grid and the merging are also checked against sahi's own functions, since the
Ultralytics backend running sahi is the reference the ONNX backend must match.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.detection import Detection
from reefscanner.core.detectors import get_detector
from reefscanner.core.detectors.tiling import TiledDetector, greedy_merge, slice_boxes

from test_onnx import FakeSession


class ScriptedDetector:
    """Finds whatever is drawn in the frame: each non-black blob is a box.

    Records the crop sizes it was asked about, so tests can see the tiling.
    """

    name = "marine"
    class_names = ["elasmobranch"]

    def __init__(self, conf: float = 0.2, score: float = 0.5) -> None:
        self.conf = conf
        self.score = score
        self.calls: list[tuple[int, int]] = []

    def detect(self, frame: np.ndarray) -> list[Detection]:
        self.calls.append(frame.shape[:2])
        ys, xs = np.nonzero(frame[:, :, 0])
        if not len(xs):
            return []
        x1, y1, x2, y2 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        return [Detection(bbox=(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                          class_name="elasmobranch", confidence=self.score)]


def _det(x1: int, y1: int, x2: int, y2: int, score: float, cls: str = "a") -> Detection:
    return Detection(bbox=(x1, y1, x2 - x1, y2 - y1), class_name=cls, confidence=score)


@pytest.mark.parametrize("h,w,size,overlap", [
    (1080, 1920, 512, 0.2), (720, 1280, 640, 0.1), (300, 400, 512, 0.2), (1000, 1000, 250, 0.5),
])
def test_tiles_match_sahi(h, w, size, overlap) -> None:
    slicing = pytest.importorskip("sahi.slicing")
    expected = slicing.get_slice_bboxes(h, w, size, size, False, overlap, overlap)
    assert [list(b) for b in slice_boxes(h, w, size, size, overlap)] == expected


def test_tiles_cover_the_whole_frame_at_full_size() -> None:
    tiles = slice_boxes(1080, 1920, 512, 512, 0.2)
    covered = np.zeros((1080, 1920), dtype=bool)
    for x1, y1, x2, y2 in tiles:
        assert (x2 - x1, y2 - y1) == (512, 512)
        covered[y1:y2, x1:x2] = True
    assert covered.all()


def test_merging_matches_sahi_on_random_boxes() -> None:
    pytest.importorskip("sahi")
    from sahi.postprocess.combine import GreedyNMMPostprocess
    from sahi.prediction import ObjectPrediction

    rng = random.Random(7)
    merge = GreedyNMMPostprocess(match_threshold=0.5, match_metric="IOS", class_agnostic=False)
    for _ in range(200):
        dets = []
        for _ in range(rng.randint(1, 12)):
            x, y = rng.randint(0, 200), rng.randint(0, 200)
            dets.append(_det(x, y, x + rng.randint(5, 80), y + rng.randint(5, 80),
                             round(rng.uniform(0.2, 0.9), 2), rng.choice("ab")))
        preds = [
            ObjectPrediction(bbox=[d.bbox[0], d.bbox[1], d.bbox[0] + d.bbox[2], d.bbox[1] + d.bbox[3]],
                             category_id=ord(d.class_name), category_name=d.class_name,
                             score=d.confidence)
            for d in dets
        ]
        theirs = sorted(
            (p.category.name, *(round(v) for v in p.bbox.to_xyxy()), round(p.score.value, 4))
            for p in merge(preds)
        )
        ours = sorted(
            (d.class_name, d.bbox[0], d.bbox[1], d.bbox[0] + d.bbox[2], d.bbox[1] + d.bbox[3],
             round(d.confidence, 4))
            for cls in "ab" for d in greedy_merge([d for d in dets if d.class_name == cls])
        )
        assert ours == theirs, dets


def test_a_small_animal_in_one_tile_comes_back_in_frame_coordinates() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[900:920, 1700:1730] = 255  # a distant shark, bottom right
    inner = ScriptedDetector()
    found = TiledDetector(inner, 512, 512, 0.2).detect(frame)
    assert [d.bbox for d in found] == [(1700, 900, 30, 20)], "duplicates from overlapping tiles merge"
    assert (1080, 1920) in inner.calls, "the whole frame is searched too"
    assert inner.calls.count((512, 512)) == len(slice_boxes(1080, 1920, 512, 512, 0.2))


def test_an_animal_split_across_tiles_is_merged_whole() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[100:400, 300:900] = 255  # larger than a tile

    class SeesMoreWhole(ScriptedDetector):
        """Pieces cut by tile edges score lower than the whole animal."""

        def detect(self, crop):
            self.score = 0.9 if crop.shape == frame.shape else 0.5
            return super().detect(crop)

    (found,) = TiledDetector(SeesMoreWhole(), 512, 512, 0.2).detect(frame)
    assert found.bbox == (300, 100, 600, 300)
    assert found.confidence == 0.9


def test_a_frame_smaller_than_a_tile_is_run_once() -> None:
    inner = ScriptedDetector()
    TiledDetector(inner, 512, 512, 0.2).detect(np.zeros((300, 400, 3), dtype=np.uint8))
    assert inner.calls == [(300, 400)]


def test_below_a_confidence_of_0_1_overlaps_are_suppressed_not_merged() -> None:
    """As sahi does: merging many weak boxes would inflate them."""
    class TwoBoxes(ScriptedDetector):
        def detect(self, frame):
            self.calls.append(frame.shape[:2])
            return [_det(0, 0, 100, 100, 0.08, "elasmobranch"),
                    _det(10, 10, 110, 110, 0.06, "elasmobranch")]

    small = np.zeros((300, 300, 3), dtype=np.uint8)
    (kept,) = TiledDetector(TwoBoxes(conf=0.05), 512, 512, 0.2).detect(small)
    assert kept.bbox == (0, 0, 100, 100)
    (merged,) = TiledDetector(TwoBoxes(conf=0.2), 512, 512, 0.2).detect(small)
    assert merged.bbox == (0, 0, 110, 110)


def test_use_sahi_tiles_the_onnx_backend(monkeypatch) -> None:
    import onnxruntime

    monkeypatch.setattr(onnxruntime, "InferenceSession",
                        lambda path, providers: FakeSession([(1, 1, 1, 1, 0.0, 0.0)]))
    det = get_detector(ReefScannerConfig(
        detector_weights="/models/shark.onnx", use_sahi=True, sahi_slice_width=640,
    ))
    assert isinstance(det, TiledDetector)
    assert (det.slice_width, det.slice_height, det.name) == (640, 512, "marine")


@pytest.mark.parametrize("bad", [
    {"sahi_slice_height": 8}, {"sahi_slice_width": 100_000}, {"sahi_slice_width": 512.5},
    {"sahi_overlap": 0.9}, {"sahi_overlap": -0.1},
])
def test_tile_settings_are_bounded(bad) -> None:
    """They can come from an imported package; tiny tiles would mean millions of runs."""
    with pytest.raises(ValueError, match="sahi_"):
        ReefScannerConfig(**bad)
