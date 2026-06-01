"""Motion gating: keep large slow movers, reject small baitfish noise (SPEC §8.3)."""

from __future__ import annotations

from pathlib import Path

from reefscanner import ReefScannerConfig, probe_video
from reefscanner.motion import MotionGate
from reefscanner.videoio import iter_sampled_frames

from conftest import make_video


def _run_gate(video: Path, cfg: ReefScannerConfig):
    info = probe_video(video)
    gate = MotionGate(cfg)
    return [
        c
        for s in iter_sampled_frames(info, cfg.frame_sample_fps)
        if (c := gate.process(s)) is not None
    ]


def test_large_animal_is_detected(tmp_path):
    video = make_video(tmp_path / "a.mp4", with_animal=True, baitfish=True)
    cfg = ReefScannerConfig(frame_sample_fps=2.0, warmup_frames=3,
                            min_blob_area=300, persistence_frames=2)
    cands = _run_gate(video, cfg)
    assert cands, "expected motion candidates for the large moving animal"
    # The animal spans ~4-8s; candidates should fall in that window.
    assert any(4.0 <= c.timestamp <= 8.5 for c in cands)


def test_baitfish_only_is_rejected(tmp_path):
    # No animal: only tiny flickery specks. Size + persistence should reject all.
    video = make_video(tmp_path / "b.mp4", with_animal=False, baitfish=True)
    cfg = ReefScannerConfig(frame_sample_fps=2.0, warmup_frames=3,
                            min_blob_area=300, persistence_frames=2)
    cands = _run_gate(video, cfg)
    assert cands == [], f"expected no candidates from baitfish noise, got {len(cands)}"


def test_warmup_suppresses_early_frames(tmp_path):
    video = make_video(tmp_path / "c.mp4", with_animal=True,
                       animal_start_s=0.0, animal_end_s=10.0, baitfish=False)
    cfg = ReefScannerConfig(frame_sample_fps=2.0, warmup_frames=6,
                            min_blob_area=300, persistence_frames=1)
    cands = _run_gate(video, cfg)
    # No candidate may have a sampled index inside the warm-up window.
    assert all(c.sampled_index >= cfg.warmup_frames for c in cands)


def test_bbox_scaled_to_original_resolution(tmp_path):
    video = make_video(tmp_path / "d.mp4", width=320, height=240)
    cfg = ReefScannerConfig(frame_sample_fps=2.0, warmup_frames=3,
                            detect_downscale=0.5, min_blob_area=100,
                            persistence_frames=1)
    cands = _run_gate(video, cfg)
    assert cands
    # bbox must be expressed in ORIGINAL coords (can exceed downscaled bounds).
    for c in cands:
        x, y, w, h = c.bbox
        assert 0 <= x <= 320 and 0 <= y <= 240
        assert w <= 320 and h <= 240
