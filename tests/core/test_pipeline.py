"""End-to-end pipeline, resumability and reporting (SPEC §8.1, §8.2, §8.4, §8.6)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from reefscanner.core import ReefScannerConfig, process_folder
from reefscanner.core.results import CSV_COLUMNS

from conftest import make_video


def _cfg(input_dir: Path, output_dir: Path, **over) -> ReefScannerConfig:
    base = dict(
        input_folder=str(input_dir),
        output_folder=str(output_dir),
        frame_sample_fps=2.0,
        # Motion-gate setting, kept only because it participates in
        # scan_fingerprint() and test_changing_settings_reprocesses_instead_of
        # _skipping asserts on that. motion_prefilter is off, so it gates
        # nothing here — the stub detector's own area floor decides what counts.
        min_blob_area=300,
        merge_gap_seconds=3.0,
        min_event_seconds=1.0,
        pad_seconds=1.0,
        # Detector mode: get_detector is patched to the stub by the
        # stub_detector fixture, so no weights are ever loaded.
        detector="generic",
    )
    base.update(over)
    return ReefScannerConfig(**base)


def test_end_to_end_produces_csv_clips_thumbnails(stub_detector, input_dir, output_dir):
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


def test_event_ids_unique_across_batch(stub_detector, input_dir, output_dir):
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    make_video(input_dir / "dive02.mp4", with_animal=True)
    batch = process_folder(_cfg(input_dir, output_dir), progress=False)

    ids = [e.event_id for r in batch.results for e in r.events]
    assert len(ids) == len(set(ids)), "event_ids must be unique across the batch"


def test_resume_skips_completed_videos(stub_detector, input_dir, output_dir):
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


def test_on_frame_reports_progress_within_a_video(stub_detector, input_dir, output_dir):
    """The per-frame hook is what lets a UI move during one long video."""
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)

    seen = []

    def on_frame(video, index, total, fraction):
        seen.append((video.name, index, total, fraction))

    process_folder(_cfg(input_dir, output_dir), progress=False, on_frame=on_frame)

    assert seen, "on_frame never fired"
    assert {s[0] for s in seen} == {"dive01.mp4"}
    assert all(s[2] == 1 for s in seen), "total should count videos"
    fractions = [s[3] for s in seen]
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert fractions == sorted(fractions), "progress must not go backwards"
    assert fractions[-1] > fractions[0], "progress must actually advance"


def test_should_cancel_stops_the_run(stub_detector, input_dir, output_dir):
    """Cancelling mid-video leaves the batch partial, not failed."""
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    make_video(input_dir / "dive02.mp4", with_animal=True)

    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 3  # bail a few frames into the first video

    batch = process_folder(
        _cfg(input_dir, output_dir), progress=False, should_cancel=should_cancel
    )

    assert batch.cancelled is True
    assert batch.n_events == 0
    # No video was completed, so nothing is marked done and a rerun redoes it.
    assert not any(r.error for r in batch.results)


def test_cancelled_video_is_not_marked_complete(stub_detector, input_dir, output_dir):
    """A cancelled run must be safely resumable — the manifest stays honest."""
    import json

    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    cfg = _cfg(input_dir, output_dir)

    calls = {"n": 0}
    process_folder(
        cfg,
        progress=False,
        should_cancel=lambda: (calls.update(n=calls["n"] + 1), calls["n"] > 2)[1],
    )

    # The manifest is only written when something is marked complete, so an
    # absent file is itself the "nothing finished" signal.
    manifest_path = output_dir / cfg.manifest_name
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        completed = manifest.get("videos", manifest)
        assert not completed, "an interrupted video must not be marked complete"

    # Resuming reprocesses it and finds the animal.
    batch = process_folder(cfg, progress=False)
    assert batch.n_events >= 1


def test_changing_settings_reprocesses_instead_of_skipping(stub_detector, input_dir, output_dir):
    """Changing a detection setting must invalidate the manifest.

    Otherwise the second run skips every video, finishes instantly and reports
    no events — which looks exactly like a broken scan rather than a cache hit.
    """
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)

    first = process_folder(_cfg(input_dir, output_dir), progress=False)
    assert first.n_events >= 1

    # Same settings: correctly skipped, which is the resumability guarantee.
    again = process_folder(_cfg(input_dir, output_dir), progress=False)
    assert all(r.skipped for r in again.results)

    # A different threshold is a different question; it must be re-asked.
    changed = process_folder(
        _cfg(input_dir, output_dir, min_blob_area=50), progress=False
    )
    assert not any(r.skipped for r in changed.results), (
        "changing min_blob_area must force a rescan"
    )
    assert changed.n_events >= 1


def test_output_paths_do_not_invalidate_the_manifest(stub_detector, input_dir, output_dir, tmp_path):
    """Renaming the clips folder isn't a reason to redo hours of analysis."""
    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)

    process_folder(_cfg(input_dir, output_dir), progress=False)
    again = process_folder(
        _cfg(input_dir, output_dir, clips_dirname="videos"), progress=False
    )
    assert all(r.skipped for r in again.results)


def test_writes_clean_frame_beside_annotated_thumbnail(
    stub_detector, input_dir, output_dir
):
    """Training images must not have the detection box burned into them."""
    import cv2
    import numpy as np

    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    cfg = _cfg(input_dir, output_dir)

    batch = process_folder(cfg, progress=False)
    assert batch.n_events >= 1
    event_id = batch.results[0].events[0].event_id

    thumb = output_dir / cfg.thumbnails_dirname / f"{event_id}{cfg.thumbnail_ext}"
    frame = output_dir / cfg.frames_dirname / f"{event_id}{cfg.thumbnail_ext}"
    assert thumb.exists(), "annotated thumbnail still needed for triage"
    assert frame.exists(), "clean frame needed for training"

    # The box is drawn in pure red (BGR 0,0,255); the synthetic footage is grey,
    # so a strongly red pixel can only have come from the annotation.
    def has_red(path):
        img = cv2.imread(str(path)).astype(int)
        b, g, r = img[:, :, 0], img[:, :, 1], img[:, :, 2]
        return bool(np.any((r > 180) & (g < 80) & (b < 80)))

    assert has_red(thumb), "thumbnail should carry the drawn box"
    assert not has_red(frame), "clean frame must have no annotation"
