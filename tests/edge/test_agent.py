"""The whole agent, replaying synthetic footage with the stub detector."""

from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path

import pytest

from camtrap_check import assert_valid_camtrap
from conftest import StubDetector, make_video
from reefscanner.core.camtrap import read_package
from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.events import Event
from reefscanner.core.videoio import probe_video
from reefscanner.edge.config import AgentConfig, AgentSettings, ConfigError, DeploymentConfig
from reefscanner.edge.replay import compare_events, replay


def _config(**agent: object) -> AgentConfig:
    settings = dict(pre_roll_seconds=3.0, post_roll_seconds=1.0, idle_fps=1.0,
                    burst_seconds=2.0, segment_seconds=1.0, detect_width=0)
    settings.update(agent)
    return AgentConfig(
        deployment=DeploymentConfig(
            id="dep1", latitude=-23.85, longitude=35.55,
            camera_timezone="Africa/Maputo", camera_clock="local",
        ),
        project_title="Test survey",
        contributors=[{"title": "Tester", "role": "contributor"}],
        agent=AgentSettings(**settings),
        detector=ReefScannerConfig(frame_sample_fps=1.0),
    )


@pytest.fixture
def videos(tmp_path: Path) -> list[Path]:
    folder = tmp_path / "in"
    folder.mkdir()
    return [
        make_video(folder / "dive01.mp4", seconds=12, animal_start_s=4, animal_end_s=8),
        make_video(folder / "dive02.mp4", seconds=10, animal_start_s=2, animal_end_s=5, seed=1),
    ]


def test_a_replay_finds_every_laptop_scan_event_and_writes_a_valid_package(
    videos: list[Path], tmp_path: Path
) -> None:
    out = tmp_path / "pkg"
    report = replay(videos, _config(), out, detector=StubDetector())

    assert report.passed, report.missed
    assert [e.event_id for e in report.agent.events] == ["dive01_001", "dive02_001"]
    assert_valid_camtrap(out)
    assert not (out / ".buffer").exists()

    package = read_package(out)
    assert {o.eventID for o in package.observations} == {
        "dep1:agent:dive01_001", "dep1:agent:dive02_001",
    }
    for media in package.media:
        assert (out / media.filePath).is_file()
    assert (out / "thumbnails" / "dive01_001.jpg").is_file()


def test_events_are_filed_under_their_own_file_with_its_times(
    videos: list[Path], tmp_path: Path
) -> None:
    report = replay(videos, _config(), tmp_path / "pkg", detector=StubDetector())
    second = next(e for e in report.agent.events if e.source_video == "dive02.mp4")
    # The animal is on screen from 2 s to 5 s into the second file, not into
    # the stream (which has the first file's 12 s before it).
    assert 1.5 <= second.start_seconds <= 2.5
    assert 4.5 <= second.end_seconds <= 5.5

    extras = {x.sourceVideo: x for x in read_package(tmp_path / "pkg").observation_extras}
    assert extras["dive02.mp4"].videoStartSeconds == pytest.approx(second.start_seconds)


def test_a_clip_holds_the_pre_roll_and_the_post_roll(videos: list[Path], tmp_path: Path) -> None:
    out = tmp_path / "pkg"
    report = replay(videos[:1], _config(), out, detector=StubDetector())
    (event,) = report.agent.events
    clip = probe_video(out / "clips" / "dive01_001.mp4")
    wanted = (event.end_seconds + 1.0) - (event.start_seconds - 3.0)
    assert clip.duration_seconds >= wanted - 0.25
    # Snapping to 1 s segments adds at most a segment at each end.
    assert clip.duration_seconds <= wanted + 2.25

    media = {m.mediaID: m for m in read_package(out).media}
    clip_row = media["dep1:agent:dive01_001:clip"]
    obs = read_package(out).observations[0]
    assert clip_row.timestamp <= obs.eventStart - _dt.timedelta(seconds=3)


def test_timestamps_follow_the_file_the_event_is_in(videos: list[Path], tmp_path: Path) -> None:
    out = tmp_path / "pkg"
    replay(videos, _config(), out, detector=StubDetector())
    package = read_package(out)
    (deployment,) = package.deployments
    assert deployment.deploymentStart.utcoffset() == _dt.timedelta(hours=2)  # Maputo
    # Synthetic files carry no creation time, so it was guessed.
    assert deployment.timestampIssues is True
    for obs in package.observations:
        assert deployment.deploymentStart <= obs.eventStart <= deployment.deploymentEnd


def test_without_animals_the_package_is_still_valid(tmp_path: Path) -> None:
    video = make_video(tmp_path / "empty.mp4", seconds=6, with_animal=False)
    report = replay([video], _config(), tmp_path / "pkg", detector=StubDetector())
    assert report.passed and report.agent.events == []
    assert_valid_camtrap(tmp_path / "pkg")


class SlowDetector(StubDetector):
    def detect(self, frame):  # noqa: ANN001, ANN201 - matches the protocol
        time.sleep(0.03)
        return super().detect(frame)


def test_in_real_time_a_busy_detector_drops_frames_but_finds_the_animal(
    videos: list[Path], tmp_path: Path
) -> None:
    # 5 fps footage played 4x is a frame every 50 ms; bursting on every frame
    # with a 30 ms detector (plus encoding) can't keep up everywhere.
    report = replay(
        videos[:1], _config(burst_seconds=5.0), tmp_path / "pkg",
        speed=4.0, detector=SlowDetector(),
    )
    assert report.passed, report.missed
    assert report.agent.detected > 0


def test_the_diff_reports_a_missed_event() -> None:
    def ev(eid: str, start: float, end: float) -> Event:
        return Event(eid, "a.mp4", start, end, start, 0.9, (0, 0, 1, 1), None, 0.9,
                     "shark", ("shark",), 1)

    found, missed, extra = compare_events(
        {"a.mp4": [ev("r1", 1, 3), ev("r2", 10, 12)]},
        {"a.mp4": [ev("a1", 2, 4), ev("a2", 20, 21)]},
    )
    assert [r.event_id for _, r, _ in found] == ["r1"]
    assert [r.event_id for _, r in missed] == ["r2"]
    assert [e.event_id for _, e in extra] == ["a2"]


def test_a_config_reports_every_problem_at_once() -> None:
    with pytest.raises(ConfigError) as err:
        AgentConfig.from_dict({
            "deployment": {"id": "../escape", "latitude": 95, "longitude": 0,
                           "camera_timezone": "Mars/Base"},
            "project": {},
            "agent": {"idle_fps": 0},
        })
    text = "\n".join(err.value.problems)
    for expected in ("deployment.id", "latitude", "camera_timezone",
                     "project.title", "contributors", "idle_fps"):
        assert expected in text
