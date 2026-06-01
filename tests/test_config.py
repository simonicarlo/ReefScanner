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


def test_get_detector_none_is_abstaining():
    det = get_detector(ReefScannerConfig(detector="none"))
    assert det.name == "none"
    assert det.confirm(None, None) is None


def test_get_detector_marine_is_v2_hook():
    with pytest.raises(NotImplementedError):
        get_detector(ReefScannerConfig(detector="marine"))
