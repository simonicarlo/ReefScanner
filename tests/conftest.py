"""Shared test fixtures: synthetic BRUV-style videos generated on the fly.

No real footage lives in the repo (SPEC §1), so tests fabricate videos with a
known-good motion signal: a static noisy background, a large slow-moving blob
(the "animal") and tiny flickery specks (the "baitfish" noise the size filter
must reject).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest


def make_video(
    path: Path,
    *,
    fps: int = 5,
    seconds: int = 12,
    width: int = 320,
    height: int = 240,
    with_animal: bool = True,
    animal_start_s: float = 4.0,
    animal_end_s: float = 8.0,
    baitfish: bool = True,
    seed: int = 0,
) -> Path:
    """Write a synthetic video and return its path.

    The "animal" is a large bright rectangle that tracks across the frame
    between ``animal_start_s`` and ``animal_end_s``. Baitfish are 2-3px specks
    that flicker every frame (small + non-persistent -> should be rejected).
    """
    rng = np.random.default_rng(seed)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    assert writer.isOpened(), "Could not open VideoWriter (codec issue?)"

    total = fps * seconds
    for i in range(total):
        t = i / fps
        # Static-ish background with mild sensor noise.
        frame = (rng.integers(40, 60, (height, width, 3))).astype(np.uint8)

        if baitfish:
            for _ in range(15):
                x = int(rng.integers(0, width - 3))
                y = int(rng.integers(0, height - 3))
                frame[y:y + 3, x:x + 3] = 220  # tiny, flickery, non-persistent

        if with_animal and animal_start_s <= t <= animal_end_s:
            frac = (t - animal_start_s) / max(1e-6, animal_end_s - animal_start_s)
            cx = int(20 + frac * (width - 80))
            cy = height // 2
            cv2.rectangle(frame, (cx, cy - 30), (cx + 60, cy + 30),
                          (230, 230, 230), thickness=-1)

        writer.write(frame)
    writer.release()
    assert path.exists() and path.stat().st_size > 0
    return path


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    return make_video(in_dir / "dive01.mp4")


@pytest.fixture
def input_dir(tmp_path: Path) -> Path:
    return tmp_path / "in"


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "out"


class StubDetector:
    """Stand-in detector: flags large bright blobs as 'shark'.

    Lets pipeline tests exercise the real detector code path without model
    weights, a download, or GPU time. The synthetic 'animal' is a bright
    rectangle, so a brightness threshold plus an area floor finds exactly it.
    """

    name = "stub"
    class_names = ["shark"]

    def __init__(self, confidence: float = 0.9, min_area: int = 1000):
        self.confidence = confidence
        self.min_area = min_area

    def detect(self, frame):
        from reefscanner.engine.detection import Detection

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return [
            Detection(
                bbox=cv2.boundingRect(c),
                class_name="shark",
                confidence=self.confidence,
            )
            for c in contours
            if cv2.contourArea(c) >= self.min_area
        ]


@pytest.fixture
def stub_detector(monkeypatch):
    """Patch the pipeline's detector factory to return the stub."""
    import reefscanner.engine.pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_detector", lambda cfg: StubDetector())
    return StubDetector()
