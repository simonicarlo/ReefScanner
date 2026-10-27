"""Importing Camtrap DP packages: from the rig into the review flow, and back out.

The rig's package is made by the real edge agent replaying synthetic footage,
so this covers the actual handover from rig to laptop.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from camtrap_check import assert_valid_camtrap
from conftest import StubDetector, make_video
from reefscanner.app.main import create_app
from reefscanner.app.models import JOB_DONE, JOB_FAILED
from reefscanner.core.camtrap import read_package
from reefscanner.core.config import ReefScannerConfig
from reefscanner.edge.config import AgentConfig, AgentSettings, DeploymentConfig
from reefscanner.edge.replay import replay


@pytest.fixture
def client(tmp_path: Path, stub_detector) -> TestClient:
    with TestClient(create_app(db_path=tmp_path / "test.db")) as c:
        yield c


@pytest.fixture
def rig_package(tmp_path: Path) -> Path:
    """A package as the rig writes it, from two synthetic dives."""
    footage = tmp_path / "footage"
    footage.mkdir()
    videos = [
        make_video(footage / "dive01.mp4", seconds=12, animal_start_s=4, animal_end_s=8),
        make_video(footage / "dive02.mp4", seconds=10, animal_start_s=2, animal_end_s=5, seed=1),
    ]
    config = AgentConfig(
        deployment=DeploymentConfig(
            id="tofo-a", latitude=-23.85, longitude=35.55,
            camera_timezone="Africa/Maputo", camera_clock="local",
            location_name="Manta Reef",
        ),
        project_title="Tofo survey",
        contributors=[{"title": "Rig", "role": "contributor"}],
        agent=AgentSettings(pre_roll_seconds=2, post_roll_seconds=1, idle_fps=1,
                            segment_seconds=1, detect_width=0),
        detector=ReefScannerConfig(detector="generic"),
    )
    out = tmp_path / "sdcard" / "tofo-a"
    report = replay(videos, config, out, compare=False, detector=StubDetector())
    assert len(report.agent.events) == 2
    return out


def _wait(client: TestClient, job_id: int, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in (JOB_DONE, JOB_FAILED, "cancelled"):
            return job
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not finish within {timeout}s")


def _import(client: TestClient, folder: Path, out: Path) -> tuple[dict, dict]:
    resp = client.post(
        "/api/projects/import",
        json={"package_folder": str(folder), "output_folder": str(out)},
    )
    assert resp.status_code == 201, resp.text
    project = resp.json()
    (job,) = client.get(f"/api/projects/{project['id']}/jobs").json()
    return project, _wait(client, job["id"])


def test_a_rig_package_lands_in_the_review_flow(client, rig_package, tmp_path) -> None:
    project, job = _import(client, rig_package, tmp_path / "results")
    assert job["status"] == JOB_DONE, job
    assert job["source"] == str(rig_package.resolve())
    assert job["events_found"] == 2
    assert project["name"] == "Manta Reef"
    assert project["deployment"]["deployment_id"] == "tofo-a"
    assert project["config"]["camera_timezone"] == "Africa/Maputo"

    events = client.get(f"/api/jobs/{job['id']}/events").json()["items"]
    assert {e["source_video"] for e in events} == {"dive01.mp4", "dive02.mp4"}
    for event in events:
        # Served from the run folder copy, so the SD card can go back in the rig.
        assert client.get(event["clip_url"]).status_code == 200
        assert client.get(event["frame_url"]).status_code == 200
    assert (tmp_path / "results" / f"scan-{job['id']}" / "clips").is_dir()


def test_an_imported_run_reviews_and_exports_like_a_scan(client, rig_package, tmp_path) -> None:
    _, job = _import(client, rig_package, tmp_path / "results")
    event = client.get(f"/api/jobs/{job['id']}/events").json()["items"][0]
    resp = client.put(f"/api/events/{quote(event['id'])}/review",
                      json={"verdict": "TP", "scientific_name": "Manta alfredi"})
    assert resp.status_code == 200, resp.text

    folder = Path(client.post(f"/api/jobs/{job['id']}/package").json()["path"])
    assert_valid_camtrap(folder)
    package = read_package(folder)
    assert {o.classificationMethod for o in package.observations} == {"machine", "human"}
    assert len(package.media) == 4


def test_reviews_travel_with_an_exported_package(client, rig_package, tmp_path) -> None:
    _, job = _import(client, rig_package, tmp_path / "a")
    event = client.get(f"/api/jobs/{job['id']}/events").json()["items"][0]
    client.put(f"/api/events/{quote(event['id'])}/review", json={"verdict": "FP"})
    exported = Path(client.post(f"/api/jobs/{job['id']}/package").json()["path"])

    # Another laptop: a fresh database.
    with TestClient(create_app(db_path=tmp_path / "other.db")) as other:
        _, job2 = _import(other, exported, tmp_path / "b")
        assert job2["status"] == JOB_DONE, job2
        page = other.get(f"/api/jobs/{job2['id']}/events").json()
        assert page["n_labeled"] == 1 and page["n_fp"] == 1


def test_the_same_deployment_cannot_be_imported_twice(client, rig_package, tmp_path) -> None:
    _import(client, rig_package, tmp_path / "results")
    resp = client.post("/api/projects/import", json={
        "package_folder": str(rig_package), "output_folder": str(tmp_path / "again"),
    })
    assert resp.status_code == 409


def _rewrite_media_path(folder: Path, new_path: str) -> None:
    path = folder / "media.csv"
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["filePath"] = new_path
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("hostile", ["../../secret.txt", "/etc/hosts", "clips/link.mp4"])
def test_a_package_cannot_reach_files_outside_itself(client, rig_package, tmp_path, hostile) -> None:
    (tmp_path / "secret.txt").write_text("not yours")
    (rig_package / "clips" / "link.mp4").symlink_to(tmp_path / "secret.txt")
    _rewrite_media_path(rig_package, hostile)

    resp = client.post("/api/projects/import", json={
        "package_folder": str(rig_package), "output_folder": str(tmp_path / "results"),
    })
    assert resp.status_code == 422
    problems = resp.json()["detail"]["problems"]
    assert any("not a file in the package" in p for p in problems)
    assert not (tmp_path / "results").exists()


def test_every_problem_in_a_package_is_reported(client, rig_package, tmp_path) -> None:
    for clip in (rig_package / "clips").iterdir():
        clip.unlink()
    extras = rig_package / "reefscanner-observations.csv"
    header = extras.read_text().splitlines()[0]
    extras.write_text(header + "\n")
    descriptor = json.loads((rig_package / "datapackage.json").read_text())
    descriptor["resources"] = [r for r in descriptor["resources"]
                               if r["name"] != "reefscanner-detections"]
    (rig_package / "datapackage.json").write_text(json.dumps(descriptor))

    resp = client.post("/api/projects/import", json={
        "package_folder": str(rig_package), "output_folder": str(tmp_path / "results"),
    })
    assert resp.status_code == 422
    problems = resp.json()["detail"]["problems"]
    assert sum("not a file in the package" in p for p in problems) == 2  # both clips
    assert sum("no reefscanner-observations row" in p for p in problems) == 2
    assert any("camera timezone" in p for p in problems)


def test_a_folder_that_is_not_a_package_is_refused(client, tmp_path) -> None:
    resp = client.post("/api/projects/import", json={
        "package_folder": str(tmp_path), "output_folder": str(tmp_path / "out"),
    })
    assert resp.status_code == 422
    assert "datapackage.json" in resp.json()["detail"]["problems"][0]


def test_a_package_cannot_choose_what_a_rescan_runs(client, rig_package, tmp_path) -> None:
    """Only tuning settings come from a package; programs, models and file
    names stay at this laptop's defaults (a rescan would run ffmpeg_path)."""
    path = rig_package / "reefscanner-observations.csv"
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        config = json.loads(row["detectorConfig"])
        config.update(
            ffmpeg_path="/tmp/evil.sh", detector_weights="/tmp/evil.onnx",
            detector_options={"weights": "/tmp/evil.onnx"}, clips_dirname="../../out",
            thumbnail_ext="/../../x.jpg", merge_gap_seconds=5.0,
        )
        row["detectorConfig"] = json.dumps(config)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    project, job = _import(client, rig_package, tmp_path / "results")
    assert job["status"] == JOB_DONE, job
    defaults = ReefScannerConfig().to_dict()
    for key in ("ffmpeg_path", "detector_weights", "detector_options",
                "clips_dirname", "thumbnail_ext"):
        assert project["config"].get(key, defaults[key]) == defaults[key], key
    assert project["config"]["merge_gap_seconds"] == 5.0  # tuning still comes along


@pytest.mark.parametrize("swap", ["file", "folder"])
def test_a_link_swapped_in_after_the_check_is_not_followed(rig_package, tmp_path, swap) -> None:
    """Checked once, copied later: the copy must not follow a link that
    appeared in between (time-of-check to time-of-use)."""
    from reefscanner.app import imports

    checked = imports.check_package(rig_package)
    outside = tmp_path / "outside"
    outside.mkdir()
    clips = rig_package / "clips"
    for clip in clips.iterdir():
        (outside / clip.name).write_text("not yours")
    if swap == "file":
        clip = next(clips.iterdir())
        clip.unlink()
        clip.symlink_to(outside / clip.name)
    else:
        shutil.rmtree(clips)
        clips.symlink_to(outside, target_is_directory=True)

    dest = tmp_path / "copy"
    with pytest.raises(OSError):
        imports.copy_files(checked, dest)
    copied = [p for p in dest.rglob("*") if p.is_file()]
    assert all(p.read_bytes() != b"not yours" for p in copied)


def test_rows_go_only_to_the_deployment_that_was_checked(rig_package) -> None:
    """The import job rereads the package; if it has become another deployment
    meanwhile, it must not write into that one (perhaps another project's)."""
    from reefscanner.app import imports
    from reefscanner.core.camtrap import PackageError

    checked = imports.check_package(rig_package)
    with pytest.raises(PackageError):
        # Refused before the session is touched, so none is needed.
        imports.insert_rows(None, checked, "scan-1", "someone-elses-deployment")


def test_a_fifo_in_the_package_is_refused_without_hanging(client, rig_package, tmp_path) -> None:
    """Opening a FIFO for reading waits for a writer; the check must not."""
    clip = next((rig_package / "clips").iterdir())
    clip.unlink()
    os.mkfifo(clip)
    resp = client.post("/api/projects/import", json={
        "package_folder": str(rig_package), "output_folder": str(tmp_path / "results"),
    })
    assert resp.status_code == 422
    assert any(clip.name in p for p in resp.json()["detail"]["problems"])


def test_an_import_brings_the_package_team(client, rig_package, tmp_path) -> None:
    project, _ = _import(client, rig_package, tmp_path / "results")
    meta = project["package_metadata"]
    assert meta["project"]["title"] == "Tofo survey"
    assert [c["title"] for c in meta["contributors"]] == ["Rig"]


def test_package_metadata_is_checked_like_any_input(client, rig_package, tmp_path) -> None:
    path = rig_package / "datapackage.json"
    descriptor = json.loads(path.read_text())
    descriptor["project"] = {"title": "x" * 10_000, "acronym": "dropped"}
    descriptor["contributors"] = [{"title": "Rig", "role": "overlord"}]
    path.write_text(json.dumps(descriptor))

    resp = client.post("/api/projects/import", json={
        "package_folder": str(rig_package), "output_folder": str(tmp_path / "results"),
    })
    assert resp.status_code == 422
    problems = resp.json()["detail"]["problems"]
    assert any("project.title" in p for p in problems), problems
    assert any("contributors.0.role" in p for p in problems), problems
