"""End-to-end pipeline, resumability and reporting (SPEC §8.1, §8.2, §8.4, §8.6)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from reefscanner import ReefScannerConfig, fp_report, process_folder
from reefscanner.results import CSV_COLUMNS

from conftest import make_video


def _cfg(input_dir: Path, output_dir: Path, **over) -> ReefScannerConfig:
    base = dict(
        input_folder=str(input_dir),
        output_folder=str(output_dir),
        frame_sample_fps=2.0,
        warmup_frames=3,
        min_blob_area=300,
        persistence_frames=2,
        merge_gap_seconds=3.0,
        min_event_seconds=1.0,
        pad_seconds=1.0,
    )
    base.update(over)
    return ReefScannerConfig(**base)


def test_end_to_end_produces_csv_clips_thumbnails(input_dir, output_dir):
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    cfg = _cfg(input_dir, output_dir)

    batch = process_folder(cfg, progress=False)

    assert batch.n_events >= 1
    assert batch.csv_path.exists()

    with open(batch.csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
        assert list(rows[0].keys()) == CSV_COLUMNS  # column contract (SPEC §6)
    assert len(rows) == batch.n_events

    for row in rows:
        assert Path(row["clip_path"]).exists(), "clip missing"
        assert Path(row["thumbnail_path"]).exists(), "thumbnail missing"
        # Reserved labeling columns must be empty (SPEC §9, §10).
        assert row["label"] == "" and row["species"] == "" and row["notes"] == ""
        # event_id uses the {video_stem}_NNN scheme (SPEC §3 Step 6).
        assert row["event_id"].startswith("dive01_")


def test_event_ids_unique_across_batch(input_dir, output_dir):
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    make_video(input_dir / "dive02.mp4", with_animal=True)
    batch = process_folder(_cfg(input_dir, output_dir), progress=False)

    ids = [e.event_id for r in batch.results for e in r.events]
    assert len(ids) == len(set(ids)), "event_ids must be unique across the batch"


def test_resume_skips_completed_videos(input_dir, output_dir):
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    cfg = _cfg(input_dir, output_dir)

    first = process_folder(cfg, progress=False)
    assert first.n_videos_processed == 1
    n_events_first = first.n_events

    # Second run: manifest marks it complete -> skipped, no duplicate rows.
    second = process_folder(cfg, progress=False)
    assert second.results[0].skipped is True
    assert second.n_videos_processed == 0

    with open(cfg.output_folder + "/" + cfg.csv_name, newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == n_events_first, "resume must not duplicate CSV rows"


def test_report_fp_rate_from_labels(input_dir, output_dir):
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    cfg = _cfg(input_dir, output_dir)
    batch = process_folder(cfg, progress=False)
    assert batch.n_events >= 1

    # Before labeling: nothing labeled.
    rep = fp_report(batch.csv_path)
    assert rep.total_events == batch.n_events
    assert rep.labeled == 0

    # Simulate a human labeling the first event FP, rest TP.
    with open(batch.csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["label"] = "FP"
    for r in rows[1:]:
        r["label"] = "TP"
    with open(batch.csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    rep2 = fp_report(batch.csv_path)
    assert rep2.labeled == len(rows)
    assert rep2.false_positives == 1
    assert rep2.false_positive_rate == pytest.approx(1 / len(rows))


def test_detector_none_imports_no_torch(input_dir, output_dir):
    """detector=none must not import torch/ultralytics (SPEC §8.5)."""
    import sys

    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    process_folder(_cfg(input_dir, output_dir, detector="none"), progress=False)

    assert "torch" not in sys.modules
    assert "ultralytics" not in sys.modules
