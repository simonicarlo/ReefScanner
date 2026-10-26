"""Event wall-clock times: the camera's timezone, not the file's label."""

from __future__ import annotations

import datetime as dt

import pytest

from reefscanner.core import ReefScannerConfig
from reefscanner.core.events import derive_timestamp

#: What a GoPro HERO5 writes: its local clock reading, labelled UTC.
GOPRO_CREATION = dt.datetime(2024, 5, 10, 17, 16, 24, tzinfo=dt.timezone.utc)


def test_file_time_is_read_as_a_clock_reading_in_the_camera_zone():
    # 17:16:24 on the camera's clock in Mozambique is 17:16:24+02:00,
    # not 17:16:24 UTC (which would be 19:16 local).
    assert derive_timestamp(GOPRO_CREATION, 0.0, "Africa/Maputo") == (
        "2024-05-10T17:16:24+02:00"
    )


def test_event_offset_is_added_to_the_clock_reading():
    assert derive_timestamp(GOPRO_CREATION, 90.5, "Africa/Maputo") == (
        "2024-05-10T17:17:54.500000+02:00"
    )


def test_daylight_saving_follows_the_zone():
    winter = dt.datetime(2024, 1, 10, 12, 0, tzinfo=dt.timezone.utc)
    summer = dt.datetime(2024, 7, 10, 12, 0, tzinfo=dt.timezone.utc)
    assert derive_timestamp(winter, 0, "Europe/Berlin").endswith("+01:00")
    assert derive_timestamp(summer, 0, "Europe/Berlin").endswith("+02:00")


def test_no_timezone_means_no_timestamp_rather_than_a_guess():
    assert derive_timestamp(GOPRO_CREATION, 0, None) == ""
    assert derive_timestamp(None, 0, "Africa/Maputo") == ""


def test_config_rejects_an_unknown_timezone():
    with pytest.raises(ValueError, match="IANA timezone"):
        ReefScannerConfig(camera_timezone="Mozambique Time")
    ReefScannerConfig(camera_timezone="Africa/Maputo")


def test_changing_the_timezone_rescans():
    """Timestamps are written at scan time, so a new zone needs new rows."""
    a = ReefScannerConfig(camera_timezone="Africa/Maputo").scan_fingerprint()
    b = ReefScannerConfig(camera_timezone="UTC").scan_fingerprint()
    assert a != b


def test_a_camera_that_records_true_utc_is_converted_into_the_zone():
    """Phones and GPS-synced cameras store real UTC: 17:16 UTC is 19:16 in Maputo."""
    assert derive_timestamp(GOPRO_CREATION, 0, "Africa/Maputo", "utc") == (
        "2024-05-10T19:16:24+02:00"
    )


def test_config_rejects_an_unknown_clock_kind():
    with pytest.raises(ValueError, match="camera_clock"):
        ReefScannerConfig(camera_clock="gps")
