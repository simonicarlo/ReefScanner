"""Config validation, (de)serialisation and the detector factory (SPEC §4, §3.4)."""

from __future__ import annotations

import pytest

from reefscanner.core import ReefScannerConfig


def test_defaults_are_recall_favoring() -> None:
    cfg = ReefScannerConfig()
    assert cfg.detector == "marine"        # detector-first default
    assert cfg.frame_sample_fps == 1.0
    assert cfg.detect_shadows is True
    assert cfg.reencode_clips is False     # stream-copy default


def test_detector_defaults_to_marine() -> None:
    """A detector-first tool must not default to something that finds nothing."""
    assert ReefScannerConfig().detector == "marine"


def test_invalid_detector_rejected() -> None:
    with pytest.raises(ValueError):
        ReefScannerConfig(detector="sharknet")


def test_unknown_config_key_rejected() -> None:
    with pytest.raises(ValueError):
        ReefScannerConfig.from_dict({"not_a_real_key": 1})


def test_extensions_normalised() -> None:
    cfg = ReefScannerConfig.from_dict({"extensions": ["MP4", ".MOV"]})
    assert cfg.extensions == (".mp4", ".mov")


def test_roundtrip_dict() -> None:
    cfg = ReefScannerConfig(min_blob_area=42, detector="generic")
    cfg2 = ReefScannerConfig.from_dict(cfg.to_dict())
    assert cfg2.min_blob_area == 42


def test_marine_without_weights_is_allowed() -> None:
    # No explicit weights is fine now — the marine builder auto-downloads
    # SharkTrack weights at runtime (no ValueError at config construction).
    cfg = ReefScannerConfig(detector="marine")
    assert cfg.detector == "marine"
    assert cfg.detector_weights is None
