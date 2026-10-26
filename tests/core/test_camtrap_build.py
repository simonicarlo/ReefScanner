"""Engine events to Camtrap DP rows: the mapping the app and the rig share."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from reefscanner.core.camtrap import Deployment, Package, validate
from reefscanner.core.camtrap.build import ScanContext, relative_bbox, rows_for_video
from reefscanner.core.events import Candidate, Event
from reefscanner.core.videoio import VideoInfo

#: A GoPro writes its local clock reading, labelled UTC.
GOPRO_START = dt.datetime(2024, 5, 10, 17, 12, 46, tzinfo=dt.timezone.utc)


def context(**overrides) -> ScanContext:
    return ScanContext(**{
        "deployment_id": "tofo-1", "scan_id": "scan-3",
        "camera_timezone": "Africa/Maputo", "camera_clock": "local",
        "clips_dir": "clips", "frames_dir": "frames", "frame_ext": ".jpg",
        "pad_seconds": 2.0, "model_name": "SharkTrack", "model_version": "models-v1",
        "detector_backend": "onnx", **overrides,
    })


def video(tmp_path: Path, creation_time=GOPRO_START) -> VideoInfo:
    path = tmp_path / "GP140102.MP4"
    path.write_bytes(b"")
    return VideoInfo(path=path, fps=30.0, frame_count=900, width=1920, height=1080,
                     duration_seconds=30.0, creation_time=creation_time)


def hit(t: float, conf: float, cls: str = "elasmobranch") -> Candidate:
    return Candidate(sampled_index=int(t), source_frame=int(t * 30), timestamp=t,
                     bbox=(960, 540, 192, 108), score=conf, class_name=cls,
                     ml_confidence=conf)


def event(cls: str = "elasmobranch") -> Event:
    members = (hit(10.0, 0.41, cls), hit(11.0, 0.64, cls), hit(12.0, 0.38, cls))
    return Event(event_id="GP140102_001", source_video="GP140102.MP4",
                 start_seconds=10.0, end_seconds=12.0, peak_timestamp=11.0,
                 peak_score=0.64, peak_bbox=(960, 540, 192, 108),
                 peak_motion_score=None, peak_ml_confidence=0.64, peak_class=cls,
                 classes=(cls,), n_candidates=3, members=members)


def test_an_event_becomes_clip_frame_machine_observation_and_detections(tmp_path) -> None:
    rows = rows_for_video(context(), video(tmp_path), [event()])

    clip, frame = rows.media
    assert clip.mediaID == "tofo-1:scan-3:GP140102_001:clip"
    assert clip.filePath == "clips/GP140102_001.mp4" and clip.fileMediatype == "video/mp4"
    assert frame.filePath == "frames/GP140102_001.jpg"

    [obs] = rows.observations
    assert obs.eventID == "tofo-1:scan-3:GP140102_001"
    assert obs.mediaID == frame.mediaID, "the box lives on the clean frame"
    assert (obs.observationType, obs.scientificName) == ("animal", "Elasmobranchii")
    assert obs.classificationProbability == pytest.approx(0.64)
    assert obs.classifiedBy == "SharkTrack (onnx, models-v1)"
    assert [obs.bboxX, obs.bboxY, obs.bboxWidth, obs.bboxHeight] == [0.5, 0.5, 0.1, 0.1]

    [extra] = rows.extras
    assert (extra.scanID, extra.sourceVideo, extra.detectorClass) == (
        "scan-3", "GP140102.MP4", "elasmobranch")
    assert [d.confidence for d in rows.detections] == [0.41, 0.64, 0.38]


def test_times_follow_the_camera_clock_and_zone(tmp_path) -> None:
    rows = rows_for_video(context(), video(tmp_path), [event()])
    [obs] = rows.observations
    # 17:12:46 on the camera's clock, +10 s into the video, in Maputo time.
    assert obs.eventStart.isoformat() == "2024-05-10T17:12:56+02:00"
    assert obs.eventEnd.isoformat() == "2024-05-10T17:12:58+02:00"
    # The clip starts pad_seconds before the event.
    assert rows.media[0].timestamp.isoformat() == "2024-05-10T17:12:54+02:00"
    assert rows.timestamp_issues is False

    utc = rows_for_video(context(camera_clock="utc"), video(tmp_path), [event()])
    assert utc.observations[0].eventStart.isoformat() == "2024-05-10T19:12:56+02:00"


def test_a_video_without_a_recorded_start_is_flagged(tmp_path) -> None:
    rows = rows_for_video(context(), video(tmp_path, creation_time=None), [event()])
    assert rows.timestamp_issues is True
    assert rows.observations[0].eventStart.utcoffset() == dt.timedelta(hours=2)


def test_a_class_without_a_scientific_name_is_still_reviewable(tmp_path) -> None:
    rows = rows_for_video(context(), video(tmp_path), [event(cls="boat")])
    obs = rows.observations[0]
    assert (obs.observationType, obs.scientificName) == ("unknown", None)
    assert rows.extras[0].detectorClass == "boat"


def test_rows_make_a_valid_package(tmp_path) -> None:
    rows = rows_for_video(context(), video(tmp_path), [event()])
    package = Package(
        deployments=[Deployment(deploymentID="tofo-1", latitude=-23.85, longitude=35.55,
                                deploymentStart=rows.video_start, deploymentEnd=rows.video_end)],
        media=rows.media, observations=rows.observations,
        observation_extras=rows.extras, detections=rows.detections,
        metadata={"project": {"title": "t"}, "contributors": [{"title": "me"}]},
    )
    assert validate(package) == []


def test_relative_boxes_are_clipped_to_the_frame() -> None:
    assert relative_bbox((1900, 1000, 100, 200), 1920, 1080) == {
        "bboxX": pytest.approx(0.989583), "bboxY": pytest.approx(0.925926),
        "bboxWidth": pytest.approx(0.010417), "bboxHeight": pytest.approx(0.074074),
    }
    assert relative_bbox(None, 1920, 1080)["bboxX"] is None
