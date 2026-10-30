"""End-to-end test of the service: project -> run -> events -> review -> export.

Uses the real engine on a synthetic video rather than a mocked pipeline, so
this covers the seam that actually breaks: engine events becoming Camtrap DP
rows with media the API can serve and a package that validates.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from reefscanner.app.main import create_app
from reefscanner.app.models import JOB_DONE, JOB_FAILED

from conftest import make_video


#: The synthetic clip is 12s at 5fps, so engine defaults (10 warm-up frames at
#: 1 sampled fps) would spend the whole video learning the background and emit
#: nothing. These are the same tunings the engine tests use.
TEST_CONFIG = {
    # Required on every project. The synthetic videos carry no creation time,
    # so their start comes from the file and is flagged as a guess.
    "camera_timezone": "Africa/Maputo",
    "frame_sample_fps": 2.0,
    "warmup_frames": 3,
    "min_blob_area": 300,
    "persistence_frames": 2,
    "min_event_seconds": 1.0,
    "pad_seconds": 1.0,
    "reencode_clips": True,
    # A real detector is the default now, so tests must name one explicitly and
    # let the stub stand in for it. Otherwise the suite quietly downloads model
    # weights and runs actual YOLO inference over synthetic footage — slow, and
    # passing only for as long as the model keeps firing on noise.
    "detector": "generic",
    "ml_confidence_threshold": 0.2,
}

DEPLOYMENT = {"latitude": -23.85, "longitude": 35.55, "camera_depth": 18, "bait_use": True}


@pytest.fixture
def client(tmp_path: Path, stub_detector) -> TestClient:
    """A service on a temporary database, with the detector stubbed out.

    ``stub_detector`` patches the pipeline's factory, so the background job
    thread builds the stub rather than loading real weights. It also makes
    confidences deterministic (0.9), which the threshold tests depend on.
    """
    app = create_app(db_path=tmp_path / "test.db")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project_dirs(tmp_path: Path) -> tuple[Path, Path]:
    in_dir = tmp_path / "footage"
    in_dir.mkdir()
    make_video(in_dir / "dive01.mp4")
    return in_dir, tmp_path / "results"


def _project_body(in_dir: Path, out_dir: Path, name: str = "Reef survey", **overrides) -> dict:
    return {
        "name": name,
        "input_folder": str(in_dir),
        "output_folder": str(out_dir),
        "config": TEST_CONFIG,
        "deployment": DEPLOYMENT,
        **overrides,
    }


def _wait_for_job(client: TestClient, job_id: int, timeout: float = 120.0) -> dict:
    """Poll until the job leaves the running state.

    Polling rather than the WebSocket: this test is about the pipeline, and a
    socket would make a timing-sensitive test out of a deterministic one.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in (JOB_DONE, JOB_FAILED, "cancelled"):
            return job
        time.sleep(0.1)
    pytest.fail(f"job {job_id} did not finish within {timeout}s")


def _project_with_job(client: TestClient, in_dir, out_dir, name: str) -> tuple[int, int]:
    """Create a project, run one job to completion; return (project id, job id)."""
    project_id = client.post("/api/projects", json=_project_body(in_dir, out_dir, name)).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    assert _wait_for_job(client, job_id)["status"] == JOB_DONE
    return project_id, job_id


def _events(client: TestClient, job_id: int, **params) -> dict:
    return client.get(f"/api/jobs/{job_id}/events", params=params).json()


def _review(client: TestClient, event: dict, **body: object) -> Response:
    return client.put(f"/api/events/{quote(event['id'])}/review", json=body)


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


def test_config_defaults_match_engine(client: TestClient) -> None:
    from reefscanner.core import ReefScannerConfig

    defaults = client.get("/api/projects/defaults").json()
    engine_defaults = ReefScannerConfig().to_dict()
    # The folders live on the project, not in the config blob.
    assert "input_folder" not in defaults
    assert defaults["frame_sample_fps"] == engine_defaults["frame_sample_fps"]


def test_create_project_rejects_missing_folder(client: TestClient, tmp_path) -> None:
    body = _project_body(tmp_path / "does-not-exist", tmp_path / "out")
    assert client.post("/api/projects", json=body).status_code == 400


def test_create_project_rejects_unknown_config_key(client, project_dirs) -> None:
    body = _project_body(*project_dirs, config={**TEST_CONFIG, "frame_sample_fpz": 2.0})
    # The engine's typo protection must survive the trip through the API.
    assert client.post("/api/projects", json=body).status_code == 422


def test_a_project_is_a_deployment(client: TestClient, project_dirs) -> None:
    """Coordinates are required; start and end come from the footage."""
    body = _project_body(*project_dirs)
    no_place = {**body, "deployment": {"camera_depth": 18}}
    assert client.post("/api/projects", json=no_place).status_code == 422
    off_the_map = {**body, "deployment": {**DEPLOYMENT, "latitude": 95}}
    assert client.post("/api/projects", json=off_the_map).status_code == 422

    project = client.post("/api/projects", json=body).json()
    deployment = project["deployment"]
    assert deployment["deployment_id"].startswith("reef-survey-")
    assert deployment["latitude"] == -23.85 and deployment["location_name"] == "Reef survey"
    assert deployment["start"] is None, "nothing scanned yet"

    job_id = client.post(f"/api/projects/{project['id']}/jobs").json()["id"]
    _wait_for_job(client, job_id)
    deployment = client.get(f"/api/projects/{project['id']}").json()["deployment"]
    assert deployment["start"] and deployment["end"]
    assert deployment["start"].endswith("+02:00"), "times are in the camera's zone"
    # The synthetic video has no recorded start, so it had to be guessed.
    assert deployment["timestamp_issues"] is True


def test_full_triage_loop(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    created = client.post("/api/projects", json=_project_body(in_dir, out_dir))
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    started = client.post(f"/api/projects/{project_id}/jobs")
    assert started.status_code == 201, started.text
    job_id = started.json()["id"]

    # A second run while the first is in flight must be refused.
    assert client.post(f"/api/projects/{project_id}/jobs").status_code == 409

    job = _wait_for_job(client, job_id)
    assert job["status"] == JOB_DONE, job.get("error")
    assert job["progress"] == 1.0
    assert job["videos_done"] == 1

    page = _events(client, job_id)
    assert page["total"] >= 1, "the synthetic animal should produce an event"
    assert page["n_labeled"] == 0
    event = page["items"][0]
    assert event["source_video"] == "dive01.mp4"
    assert event["detected_class"] == "shark"
    assert event["confidence"] == pytest.approx(0.9)
    assert all(0 <= v <= 1 for v in event["bbox"]), "boxes are relative to the frame"

    # Media must actually be served, not just referenced.
    assert client.get(event["frame_url"]).status_code == 200
    assert client.get(event["clip_url"]).status_code == 200

    # Unreviewed filter starts as the whole set.
    assert _events(client, job_id, labeled=False)["total"] == page["total"]

    reviewed = _review(
        client, event, verdict="TP", scientific_name="Carcharhinus melanopterus",
        notes="clear pass across frame", bbox=[0.1, 0.2, 0.3, 0.25],
    )
    assert reviewed.status_code == 200, reviewed.text
    review = reviewed.json()["review"]
    assert review["verdict"] == "TP"
    assert review["scientific_name"] == "Carcharhinus melanopterus"
    assert review["bbox"] == [0.1, 0.2, 0.3, 0.25]

    after = _events(client, job_id)
    assert (after["n_labeled"], after["n_tp"], after["n_fp"]) == (1, 1, 0)
    assert _events(client, job_id, verdict="TP")["total"] == 1

    # The name just used becomes a suggestion for the next event.
    assert "Carcharhinus melanopterus" in client.get(f"/api/jobs/{job_id}/species").json()

    # Re-reviewing updates in place rather than creating a second verdict.
    _review(client, event, verdict="FP")
    again = _events(client, job_id)
    assert (again["n_labeled"], again["n_fp"]) == (1, 1)

    # Un-reviewing puts it back in the queue.
    assert client.delete(f"/api/events/{quote(event['id'])}/review").status_code == 204
    assert _events(client, job_id)["n_labeled"] == 0


def test_verdicts_become_camtrap_observations(client: TestClient, project_dirs) -> None:
    """The verdict table from the data-model design note."""
    from reefscanner.core.camtrap import Observation

    _, job_id = _project_with_job(client, *project_dirs, "verdicts")
    event = _events(client, job_id)["items"][0]

    def human() -> Observation:
        with client.app.state.db.session() as session:
            return session.get(Observation, f"{event['id']}:human")

    _review(client, event, verdict="TP")
    obs = human()
    assert obs.observationType == "animal"
    assert obs.classificationMethod == "human" and obs.observationTags == "verdict:TP"
    assert obs.bboxX is not None, "a TP keeps the detector's box"

    _review(client, event, verdict="FP")
    obs = human()
    assert (obs.observationType, obs.scientificName, obs.bboxX) == ("blank", None, None)

    _review(client, event, verdict="FP-other", scientific_name="Caranx ignobilis")
    obs = human()
    assert (obs.observationType, obs.scientificName) == ("animal", "Caranx ignobilis")
    assert obs.observationTags == "verdict:FP-other"

    _review(client, event, verdict="unsure", notes="murky")
    obs = human()
    assert (obs.observationType, obs.observationComments) == ("unknown", "murky")

    # Both kinds of false positive count as false positives.
    _review(client, event, verdict="FP-other")
    assert _events(client, job_id)["n_fp"] == 1


def test_review_validation(client: TestClient, project_dirs) -> None:
    _, job_id = _project_with_job(client, *project_dirs, "v")
    event = _events(client, job_id)["items"][0]
    assert _review(client, event, verdict="maybe").status_code == 422
    assert _review(client, event, verdict="TP", bbox=[0.1, 0.2, 0, 0.4]).status_code == 422
    assert _review(client, event, verdict="TP", bbox=[10, 20, 40, 30]).status_code == 422
    assert client.get("/api/events/nope:scan-1:x_001").status_code == 404


def test_each_run_keeps_its_own_files(client: TestClient, project_dirs) -> None:
    """A rescan never overwrites an earlier run's clips."""
    in_dir, out_dir = project_dirs
    project_id, first = _project_with_job(client, in_dir, out_dir, "runs")
    client.patch(
        f"/api/projects/{project_id}",
        json={"config": {**TEST_CONFIG, "frame_sample_fps": 3.0}},
    )
    second = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, second)

    assert (out_dir / f"scan-{first}" / "clips").is_dir()
    assert (out_dir / f"scan-{second}" / "clips").is_dir()
    a, b = _events(client, first)["items"], _events(client, second)["items"]
    assert a and b and {e["id"] for e in a}.isdisjoint({e["id"] for e in b})


def test_package_export_is_valid_camtrap_dp(client: TestClient, project_dirs) -> None:
    from reefscanner.core.camtrap import read_package

    from camtrap_check import assert_valid_camtrap

    in_dir, out_dir = project_dirs
    _, job_id = _project_with_job(client, in_dir, out_dir, "package")
    event = _events(client, job_id)["items"][0]
    _review(client, event, verdict="TP", scientific_name="Carcharhinus amblyrhynchos")

    resp = client.post(f"/api/jobs/{job_id}/package")
    assert resp.status_code == 200, resp.text
    folder = Path(resp.json()["path"])
    assert folder == out_dir / f"scan-{job_id}"
    assert_valid_camtrap(folder)

    package = read_package(folder)
    assert len(package.deployments) == 1
    kinds = {o.classificationMethod for o in package.observations}
    assert kinds == {"machine", "human"}
    # Every media file the package names is really there, inside the package.
    for media in package.media:
        assert (folder / media.filePath).is_file(), media.filePath
    assert package.detections, "the per-frame confidence series travels too"


def test_exports(client: TestClient, project_dirs) -> None:
    _, job_id = _project_with_job(client, *project_dirs, "export")
    events = _events(client, job_id)["items"]
    _review(client, events[0], verdict="TP", scientific_name="Carcharhinus amblyrhynchos")

    coco = json.loads(client.get(f"/api/jobs/{job_id}/export/coco").text)
    assert len(coco["images"]) == 1
    assert coco["categories"][0]["name"] == "Carcharhinus amblyrhynchos"
    width = coco["images"][0]["width"]
    x = coco["annotations"][0]["bbox"][0]
    assert x == round(events[0]["bbox"][0] * width), "boxes back in pixels for COCO"

    yolo = client.get(f"/api/jobs/{job_id}/export/yolo")
    assert yolo.status_code == 200
    assert yolo.headers["content-type"] == "application/zip"


def test_media_rejects_path_outside_project(client, project_dirs, tmp_path) -> None:
    """The media endpoint must not serve a path outside the output folder."""
    from reefscanner.core.camtrap import Media

    _, job_id = _project_with_job(client, *project_dirs, "sec")
    event = _events(client, job_id)["items"][0]
    secret = tmp_path / "secret.txt"
    secret.write_text("not yours")

    # Tamper with the stored path the way a corrupted DB or a hostile package would.
    with client.app.state.db.session() as session:
        media = session.get(Media, f"{event['id']}:frame")
        media.filePath = "../../secret.txt"
        session.add(media)
        session.commit()

    assert client.get(event["frame_url"]).status_code == 403
    assert client.get(f"/api/media/thumbnail/{quote(event['id'])}").status_code == 404


def test_delete_project_cascades(client: TestClient, project_dirs) -> None:
    from sqlmodel import select

    from reefscanner.core.camtrap import Deployment, Observation

    project_id, job_id = _project_with_job(client, *project_dirs, "gone")
    assert client.delete(f"/api/projects/{project_id}").status_code == 204
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    with client.app.state.db.session() as session:
        assert session.exec(select(Deployment)).all() == []
        assert session.exec(select(Observation)).all() == []


def test_threshold_analysis(client: TestClient, project_dirs) -> None:
    """Reviews must turn into a confidence recommendation."""
    _, job_id = _project_with_job(client, *project_dirs, "thresholds")
    _review(client, _events(client, job_id)["items"][0], verdict="TP")

    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["confirmed"] == 1
    assert body["reliable"] is False, "one review is not evidence"
    assert body["scan_threshold"] == TEST_CONFIG["ml_confidence_threshold"]
    # The stub detects at a fixed 0.9, so that is the only sweep point.
    assert [p["threshold"] for p in body["points"]] == [0.9]
    assert body["recommended"] == 0.9


def test_threshold_analysis_counts_fp_other_as_rejected(client, project_dirs) -> None:
    _, job_id = _project_with_job(client, *project_dirs, "fp-other")
    _review(client, _events(client, job_id)["items"][0], verdict="FP-other")
    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert (body["confirmed"], body["rejected"]) == (0, 1)


def test_threshold_analysis_without_reviews(client: TestClient, project_dirs) -> None:
    _, job_id = _project_with_job(client, *project_dirs, "noreviews")
    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["recommended"] is None
    assert body["points"] == []
    assert body["labeled"] == 0


def test_threshold_analysis_excludes_unsure(client: TestClient, project_dirs) -> None:
    """An undecided verdict must not be counted as evidence either way."""
    _, job_id = _project_with_job(client, *project_dirs, "unsure")
    _review(client, _events(client, job_id)["items"][0], verdict="unsure")

    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["undecided"] == 1
    assert body["confirmed"] == 0
    assert body["rejected"] == 0
    assert body["recommended"] is None


def test_threshold_analysis_unknown_job(client: TestClient) -> None:
    assert client.get("/api/jobs/999/threshold-analysis").status_code == 404


def test_clean_frame_is_served(client: TestClient, project_dirs) -> None:
    _, job_id = _project_with_job(client, *project_dirs, "frames")
    event = _events(client, job_id)["items"][0]
    resp = client.get(event["frame_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_yolo_export_ships_clean_images(client: TestClient, project_dirs) -> None:
    """A YOLO zip is only a dataset if it carries images — the clean ones."""
    import io
    import zipfile

    import cv2
    import numpy as np

    _, job_id = _project_with_job(client, *project_dirs, "yolo-images")
    event = _events(client, job_id)["items"][0]
    _review(client, event, verdict="TP")

    archive = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/jobs/{job_id}/export/yolo").content)
    )
    names = archive.namelist()
    labels = [n for n in names if n.startswith("labels/")]
    images = [n for n in names if n.startswith("images/")]
    assert len(labels) == 1 and len(images) == 1, names
    stem = lambda n: n.rsplit("/", 1)[1].rsplit(".", 1)[0]  # noqa: E731
    assert stem(labels[0]) == stem(images[0]), "a label pairs with its image by name"

    # Same red-box test as the pipeline: the exported image must be clean.
    img = cv2.imdecode(np.frombuffer(archive.read(images[0]), np.uint8), cv2.IMREAD_COLOR)
    b, g, r = (img[:, :, i].astype(int) for i in range(3))
    assert not np.any((r > 180) & (g < 80) & (b < 80)), "export shipped the annotated thumbnail"


def test_spa_route_does_not_serve_files_outside_the_build(
    monkeypatch, tmp_path: Path
) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html>index")
    (static / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("do not serve")
    monkeypatch.setattr("reefscanner.app.main.STATIC_DIR", static)

    with TestClient(create_app(db_path=tmp_path / "test.db")) as c:
        assert c.get("/favicon.svg").text == "<svg/>"
        # Percent-encoded so the client doesn't normalise the dots away.
        for url in ("/..%2fsecret.txt", "/%2e%2e/secret.txt"):
            resp = c.get(url)
            assert resp.status_code == 200
            assert "do not serve" not in resp.text
            assert resp.text == "<!doctype html>index"


def test_project_needs_a_camera_timezone(client: TestClient, project_dirs) -> None:
    """Files can't be trusted about their timezone, so a project must say."""
    body = _project_body(*project_dirs, "no zone")
    no_zone = {**body, "config": {"frame_sample_fps": 2.0}}
    assert client.post("/api/projects", json=no_zone).status_code == 422

    created = client.post("/api/projects", json=body).json()
    # A config update replaces the stored one, so it can't drop the zone either.
    resp = client.patch(f"/api/projects/{created['id']}", json={"config": {"frame_sample_fps": 1.0}})
    assert resp.status_code == 422


def test_a_new_run_rescans_everything_so_its_package_is_complete(client, project_dirs) -> None:
    """Runs don't share the 'already scanned' record: no run silently misses videos."""
    in_dir, out_dir = project_dirs
    project_id, first = _project_with_job(client, in_dir, out_dir, "complete")
    second = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    job = _wait_for_job(client, second)

    assert job["events_found"] == client.get(f"/api/jobs/{first}").json()["events_found"] > 0
    assert (out_dir / f"scan-{second}" / "reefscanner_manifest.json").is_file()
    assert not (out_dir / "reefscanner_manifest.json").exists(), "no shared manifest"


def test_resume_finishes_a_run_without_rescanning_or_duplicating(client, project_dirs) -> None:
    from sqlmodel import select

    from reefscanner.core.camtrap import Detection, Media, Observation, ObservationExtra

    in_dir, out_dir = project_dirs
    make_video(in_dir / "dive02.mp4", seed=2)
    _, job_id = _project_with_job(client, in_dir, out_dir, "resume")
    complete = _events(client, job_id)["total"]
    assert {e["source_video"] for e in _events(client, job_id)["items"]} == {"dive01.mp4", "dive02.mp4"}

    # Simulate an interruption before dive02: the run failed, dive02 isn't in
    # its manifest, and none of dive02's rows were written.
    manifest = out_dir / f"scan-{job_id}" / "reefscanner_manifest.json"
    data = json.loads(manifest.read_text())
    data["videos"].pop("dive02.mp4")
    manifest.write_text(json.dumps(data))
    with client.app.state.db.session() as session:
        extras = session.exec(
            select(ObservationExtra).where(ObservationExtra.sourceVideo == "dive02.mp4")
        ).all()
        events = [e.observationID.removesuffix(":machine") for e in extras]
        for model, column in ((Detection, Detection.observationID), (ObservationExtra, ObservationExtra.observationID)):
            for row in session.exec(select(model).where(column.in_([f"{e}:machine" for e in events]))):
                session.delete(row)
        session.flush()
        for row in session.exec(select(Observation).where(Observation.eventID.in_(events))):
            session.delete(row)
        session.flush()
        for row in session.exec(select(Media).where(Media.mediaID.in_(
            [f"{e}:{k}" for e in events for k in ("clip", "frame")]
        ))):
            session.delete(row)
        from reefscanner.app.models import Job

        job = session.get(Job, job_id)
        job.status = "failed"
        session.add(job)
        session.commit()
    assert _events(client, job_id)["total"] < complete

    resumed = client.post(f"/api/jobs/{job_id}/resume")
    assert resumed.status_code == 200, resumed.text
    job = _wait_for_job(client, job_id)
    assert job["status"] == JOB_DONE
    assert "1 video(s) scanned before the resume" in job["message"]
    assert _events(client, job_id)["total"] == job["events_found"] == complete


def test_only_a_stopped_run_can_resume(client, project_dirs) -> None:
    _, job_id = _project_with_job(client, *project_dirs, "done")
    assert client.post(f"/api/jobs/{job_id}/resume").status_code == 409
    assert client.post("/api/jobs/999/resume").status_code == 404


def test_event_says_where_its_clip_starts(client, project_dirs) -> None:
    project_id, job_id = _project_with_job(client, *project_dirs, "clipstart")
    pad = {
        **client.get("/api/projects/defaults").json(),
        **client.get(f"/api/projects/{project_id}").json()["config"],
    }["pad_seconds"]
    for event in _events(client, job_id)["items"]:
        assert event["clip_start_seconds"] == max(0.0, event["start_seconds"] - pad)


def test_project_shows_its_latest_run_review(client, project_dirs) -> None:
    project_id, job_id = _project_with_job(client, *project_dirs, "summary")
    events = _events(client, job_id)["items"]
    assert events, "the fixture footage has events"

    summary = client.get(f"/api/projects/{project_id}").json()["latest_run"]
    assert summary == {
        "job_id": job_id, "events": len(events), "reviewed": 0,
        "confirmed": 0, "rejected": 0, "cover_url": events[0]["frame_url"],
    }

    # A confirmed event becomes the cover; a rejection only counts.
    _review(client, events[-1], verdict="TP")
    if len(events) > 1:
        _review(client, events[0], verdict="FP")
    summary = client.get("/api/projects").json()[0]["latest_run"]
    assert summary["cover_url"] == events[-1]["frame_url"]
    assert summary["confirmed"] == 1
    assert summary["reviewed"] == min(2, len(events))
    assert summary["rejected"] == (1 if len(events) > 1 else 0)


def test_appearance_defaults_and_saves(client) -> None:
    assert client.get("/api/settings/appearance").json() == {
        "mode": "system", "translucency": True,
    }
    saved = client.put("/api/settings/appearance", json={"mode": "dark", "translucency": False})
    assert saved.status_code == 200
    assert client.get("/api/settings/appearance").json() == {
        "mode": "dark", "translucency": False,
    }
    assert client.put("/api/settings/appearance", json={"mode": "sepia"}).status_code == 422
    # The person's details are saved separately and stay as they were.
    assert client.get("/api/settings").json()["name"] is None


def test_settings_sign_reviews_and_start_new_projects(client, project_dirs) -> None:
    from reefscanner.core.camtrap import Observation

    you = client.get("/api/settings").json()
    assert you["name"] is None and you["signed_as"], "the login name stands in"

    resp = client.put("/api/settings", json={
        "name": "  Ana Reef ", "email": "ana@example.org", "organization": "MMF",
    })
    assert resp.status_code == 200 and resp.json()["signed_as"] == "Ana Reef"
    assert client.put("/api/settings", json={"email": "Ana Reef"}).status_code == 422

    project_id, job_id = _project_with_job(client, *project_dirs, "signed")
    meta = client.get(f"/api/projects/{project_id}").json()["package_metadata"]
    assert meta == {
        "project": {"title": "signed", "description": None},
        "contributors": [{"title": "Ana Reef", "email": "ana@example.org",
                          "organization": "MMF", "role": "contributor"}],
    }
    event = _events(client, job_id)["items"][0]
    _review(client, event, verdict="TP")
    with client.app.state.db.session() as session:
        assert session.get(Observation, f"{event['id']}:human").classifiedBy == "Ana Reef"


def test_project_metadata_is_edited_and_exported(client, project_dirs) -> None:
    from reefscanner.core.camtrap import read_package

    in_dir, out_dir = project_dirs
    project_id, job_id = _project_with_job(client, in_dir, out_dir, "meta")
    team = {
        "project": {"title": "Tofo megafauna", "description": "Baited reef cameras"},
        "contributors": [
            {"title": "A. Lead", "role": "principalInvestigator", "email": "lead@example.org"},
            {"title": "Marine Megafauna Foundation", "role": "rightsHolder"},
        ],
    }
    resp = client.patch(f"/api/projects/{project_id}", json={"package_metadata": team})
    assert resp.status_code == 200, resp.text

    for bad in (
        {**team, "contributors": []},  # Camtrap needs one
        {**team, "contributors": [{"title": "X", "role": "boss"}]},
        {**team, "project": {"title": ""}},
    ):
        resp = client.patch(f"/api/projects/{project_id}", json={"package_metadata": bad})
        assert resp.status_code == 422, bad

    folder = Path(client.post(f"/api/jobs/{job_id}/package").json()["path"])
    meta = read_package(folder).metadata
    assert team["project"].items() <= meta["project"].items()  # core adds required defaults
    assert [c["title"] for c in meta["contributors"]] == ["A. Lead", "Marine Megafauna Foundation"]
    assert "email" not in meta["contributors"][1], "unset fields are left out, not null"
