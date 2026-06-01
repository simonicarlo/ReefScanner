"""Config validation, (de)serialisation and the detector factory (SPEC §4, §3.4)."""

from __future__ import annotations

import pytest

from reefscanner import ReefScannerConfig
from reefscanner.detectors import get_detector


def test_defaults_are_recall_favoring():
    cfg = ReefScannerConfig()
    assert cfg.detector == "none"          # v1 default (SPEC §4)
    assert cfg.frame_sample_fps == 1.0
    assert cfg.detect_shadows is True
    assert cfg.reencode_clips is False     # stream-copy default


def test_invalid_detector_rejected():
    with pytest.raises(ValueError):
        ReefScannerConfig(detector="sharknet")


def test_unknown_config_key_rejected():
    with pytest.raises(ValueError):
        ReefScannerConfig.from_dict({"not_a_real_key": 1})


def test_extensions_normalised():
    cfg = ReefScannerConfig.from_dict({"extensions": ["MP4", ".MOV"]})
    assert cfg.extensions == (".mp4", ".mov")


def test_roundtrip_dict():
    cfg = ReefScannerConfig(min_blob_area=42, detector="none")
    cfg2 = ReefScannerConfig.from_dict(cfg.to_dict())
    assert cfg2.min_blob_area == 42


def test_get_detector_none_finds_nothing():
    import numpy as np

    det = get_detector(ReefScannerConfig(detector="none"))
    assert det.name == "none"
    # No ML: the none detector finds nothing (pipeline uses motion mode).
    assert det.detect(np.zeros((4, 4, 3), dtype=np.uint8)) == []


def test_marine_without_weights_is_allowed():
    # No explicit weights is fine now — the marine builder auto-downloads
    # SharkTrack weights at runtime (no ValueError at config construction).
    cfg = ReefScannerConfig(detector="marine")
    assert cfg.detector == "marine"
    assert cfg.detector_weights is None


def test_marine_with_weights_needs_ultralytics():
    # With weights set, building the marine detector tries to import ultralytics,
    # which isn't installed in the v1 test env -> ImportError (graceful).
    cfg = ReefScannerConfig(detector="marine", detector_weights="sharktrack.pt")
    with pytest.raises(ImportError):
        get_detector(cfg)
