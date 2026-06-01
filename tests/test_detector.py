"""Detector-scans-frames (v2) end-to-end, via a stub detector (no ML dep).

We can't run YOLO/SharkTrack in CI (weights + torch), so a stub Detector stands
in for the model: it finds the synthetic "animal" (large bright blob) and labels
it "shark". This validates the v2 architecture — detector -> candidates ->
events -> clips/CSV with detected_class — independent of any real model.
"""

from __future__ import annotations

import csv

import cv2
import numpy as np

from reefscanner import (
    Candidate,
    Detection,
    ReefScannerConfig,
    process_folder,
)
from reefscanner.config import ReefScannerConfig as Cfg
from reefscanner.events import aggregate_events
from reefscanner.results import CSV_COLUMNS

from conftest import make_video


class StubSharkDetector:
    """Stand-in detector: flags large bright blobs as 'shark'."""

    name = "stub"
    class_names = ["shark"]

    def detect(self, frame: np.ndarray) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in contours:
            if cv2.contourArea(c) >= 1000:  # large blob = the "animal"
                out.append(
                    Detection(bbox=cv2.boundingRect(c), class_name="shark",
                              confidence=0.9)
                )
        return out


def _cfg(input_dir, output_dir, **over):
    base = dict(
        input_folder=str(input_dir),
        output_folder=str(output_dir),
        frame_sample_fps=2.0,
        warmup_frames=3,
        merge_gap_seconds=3.0,
        min_event_seconds=1.0,
        pad_seconds=1.0,
        detector="generic",  # valid config; get_detector is monkeypatched away
    )
    base.update(over)
    return ReefScannerConfig(**base)


def test_detector_mode_end_to_end(monkeypatch, input_dir, output_dir):
    import reefscanner.pipeline as pipeline

    # Inject the stub instead of building a real YOLO detector.
    monkeypatch.setattr(pipeline, "get_detector", lambda cfg: StubSharkDetector())

    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    batch = process_folder(_cfg(input_dir, output_dir), progress=False)

    assert batch.n_events >= 1
    with open(batch.csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == CSV_COLUMNS  # detected_class now in contract

    row = rows[0]
    assert row["detected_class"] == "shark"      # model class recorded
    assert row["ml_confidence"] != ""            # detector confidence present
    assert row["motion_score"] == ""             # motion not used as recall here
    assert row["species"] == ""                  # human-reserved, still blank


def test_detector_mode_motion_prefilter(monkeypatch, input_dir, output_dir):
    """motion_prefilter must not drop the moving animal (recall-safe skip)."""
    import reefscanner.pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_detector", lambda cfg: StubSharkDetector())
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)

    batch = process_folder(
        _cfg(input_dir, output_dir, motion_prefilter=True, min_blob_area=300),
        progress=False,
    )
    assert batch.n_events >= 1  # the moving shark still gets through


def test_aggregate_events_records_class_and_confidence():
    cfg = Cfg(merge_gap_seconds=3.0, min_event_seconds=0.0)
    cands = [
        Candidate(0, 0, 0.0, (0, 0, 10, 10), score=0.5, class_name="ray",
                  ml_confidence=0.5),
        Candidate(1, 5, 1.0, (0, 0, 20, 20), score=0.9, class_name="shark",
                  ml_confidence=0.9),
    ]
    events = aggregate_events(cands, cfg, video_stem="v", source_video="v.mp4")
    assert len(events) == 1
    ev = events[0]
    assert ev.peak_class == "shark"             # peak by score
    assert ev.classes == ("ray", "shark")        # all classes seen, sorted
    assert ev.peak_ml_confidence == 0.9
    assert ev.peak_motion_score is None          # detector mode: no motion score
