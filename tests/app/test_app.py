"""End-to-end test of the service: project -> job -> events -> label -> export.

Uses the real engine on a synthetic video rather than a mocked pipeline, so
this covers the seam that actually breaks: engine events being translated into
database rows with usable clip and thumbnail paths.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefscanner.app.main import create_app
from reefscanner.app.models import JOB_DONE, JOB_FAILED

from conftest import make_video


#: The synthetic clip is 12s at 5fps, so engine defaults (10 warm-up frames at
#: 1 sampled fps) would spend the whole video learning the background and emit
#: nothing. These are the same tunings the engine tests use.
TEST_CONFIG = {
    # Required on every project; the synthetic videos carry no creation time.
    "camera_timezone": "UTC",
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
    resp = client.post(
        "/api/projects",
        json={
            "name": "nope",
            "input_folder": str(tmp_path / "does-not-exist"),
            "output_folder": str(tmp_path / "out"),
            "config": TEST_CONFIG,
        },
    )
    assert resp.status_code == 400


def test_create_project_rejects_unknown_config_key(client, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    resp = client.post(
        "/api/projects",
        json={
            "name": "typo",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": {"frame_sample_fpz": 2.0, "camera_timezone": "UTC"},
        },
    )
    # The engine's typo protection must survive the trip through the API.
    assert resp.status_code == 422


def test_full_triage_loop(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs

    created = client.post(
        "/api/projects",
        json={
            "name": "Reef survey",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    )
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

    page = client.get(f"/api/jobs/{job_id}/events").json()
    assert page["total"] >= 1, "the synthetic animal should produce an event"
    assert page["n_labeled"] == 0
    event = page["items"][0]
    assert event["thumbnail_url"] and event["clip_url"]

    # Media must actually be served, not just referenced.
    assert client.get(event["thumbnail_url"]).status_code == 200
    assert client.get(event["clip_url"]).status_code == 200

    # Unlabeled filter starts as the whole set.
    unlabeled = client.get(
        f"/api/jobs/{job_id}/events", params={"labeled": False}
    ).json()
    assert unlabeled["total"] == page["total"]

    labeled = client.put(
        f"/api/events/{event['id']}/label",
        json={
            "verdict": "TP",
            "species": "Carcharhinus melanopterus",
            "notes": "clear pass across frame",
            "tight_bbox": [10, 20, 40, 30],
        },
    )
    assert labeled.status_code == 200, labeled.text
    assert labeled.json()["label"]["verdict"] == "TP"

    after = client.get(f"/api/jobs/{job_id}/events").json()
    assert after["n_labeled"] == 1
    assert after["n_tp"] == 1
    assert after["n_fp"] == 0

    # The species just used becomes a suggestion for the next event.
    assert "Carcharhinus melanopterus" in client.get(
        f"/api/jobs/{job_id}/species"
    ).json()

    # Re-labeling updates in place rather than creating a second verdict.
    client.put(f"/api/events/{event['id']}/label", json={"verdict": "FP"})
    again = client.get(f"/api/jobs/{job_id}/events").json()
    assert again["n_labeled"] == 1
    assert again["n_fp"] == 1


def test_label_validation(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    project_id = client.post(
        "/api/projects",
        json={
            "name": "v",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, job_id)
    events = client.get(f"/api/jobs/{job_id}/events").json()["items"]
    if not events:
        pytest.skip("no events produced; nothing to validate against")
    eid = events[0]["id"]

    assert client.put(
        f"/api/events/{eid}/label", json={"verdict": "maybe"}
    ).status_code == 422
    assert client.put(
        f"/api/events/{eid}/label",
        json={"verdict": "TP", "tight_bbox": [1, 2, 0, 4]},
    ).status_code == 422


def test_exports(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    project_id = client.post(
        "/api/projects",
        json={
            "name": "export",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    assert _wait_for_job(client, job_id)["status"] == JOB_DONE

    events = client.get(f"/api/jobs/{job_id}/events").json()["items"]
    assert events
    client.put(
        f"/api/events/{events[0]['id']}/label",
        json={"verdict": "TP", "species": "reef shark"},
    )

    csv_body = client.get(f"/api/jobs/{job_id}/export/csv")
    assert csv_body.status_code == 200
    from reefscanner.core.results import CSV_COLUMNS

    header = csv_body.text.splitlines()[0]
    assert header == ",".join(CSV_COLUMNS), "CSV columns must match the engine's"
    assert "reef shark" in csv_body.text

    coco = json.loads(client.get(f"/api/jobs/{job_id}/export/coco").text)
    assert len(coco["images"]) == 1
    assert coco["categories"][0]["name"] == "reef shark"
    ann = coco["annotations"][0]
    assert ann["bbox"] == list(events[0]["peak_bbox"])

    yolo = client.get(f"/api/jobs/{job_id}/export/yolo")
    assert yolo.status_code == 200
    assert yolo.headers["content-type"] == "application/zip"

    # Only confirmed events are exportable — an unlabeled one is not training data.
    assert len(coco["images"]) < len(events) or len(events) == 1


def test_media_rejects_path_outside_project(client, project_dirs, tmp_path) -> None:
    """The media endpoint must not serve a path outside the output folder."""
    in_dir, out_dir = project_dirs
    project_id = client.post(
        "/api/projects",
        json={
            "name": "sec",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, job_id)

    secret = tmp_path / "secret.txt"
    secret.write_text("not yours")

    # Tamper with the stored path the way a corrupted DB (or a bug) would.
    from reefscanner.app.models import Event

    db = client.app.state.db
    with db.session() as session:
        from sqlmodel import select

        event = session.exec(select(Event)).first()
        if event is None:
            pytest.skip("no events produced")
        event.thumbnail_path = str(secret)
        session.add(event)
        session.commit()
        event_id = event.id

    assert client.get(f"/api/media/thumbnail/{event_id}").status_code == 403


def test_delete_project_cascades(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    project_id = client.post(
        "/api/projects",
        json={
            "name": "gone",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, job_id)

    assert client.delete(f"/api/projects/{project_id}").status_code == 204
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def _project_with_job(client: TestClient, in_dir, out_dir, name: str) -> int:
    """Create a project, run one job to completion, return the job id."""
    project_id = client.post(
        "/api/projects",
        json={
            "name": name,
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, job_id)
    return job_id


def test_threshold_analysis(client: TestClient, project_dirs) -> None:
    """Labels must turn into a confidence recommendation."""
    in_dir, out_dir = project_dirs
    job_id = _project_with_job(client, in_dir, out_dir, "thresholds")

    events = client.get(f"/api/jobs/{job_id}/events").json()["items"]
    assert events, "need at least one event to analyse"
    client.put(f"/api/events/{events[0]['id']}/label", json={"verdict": "TP"})

    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["confirmed"] == 1
    assert body["reliable"] is False, "one label is not evidence"
    assert body["scan_threshold"] == TEST_CONFIG["ml_confidence_threshold"]
    # The stub detects at a fixed 0.9, so that is the only sweep point.
    assert [p["threshold"] for p in body["points"]] == [0.9]
    assert body["recommended"] == 0.9


def test_threshold_analysis_without_labels(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    job_id = _project_with_job(client, in_dir, out_dir, "nolabels")

    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["recommended"] is None
    assert body["points"] == []
    assert body["labeled"] == 0


def test_threshold_analysis_excludes_unsure(client: TestClient, project_dirs) -> None:
    """An undecided verdict must not be counted as evidence either way."""
    in_dir, out_dir = project_dirs
    job_id = _project_with_job(client, in_dir, out_dir, "unsure")

    events = client.get(f"/api/jobs/{job_id}/events").json()["items"]
    client.put(f"/api/events/{events[0]['id']}/label", json={"verdict": "unsure"})

    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["undecided"] == 1
    assert body["confirmed"] == 0
    assert body["rejected"] == 0
    assert body["recommended"] is None


def test_threshold_analysis_unknown_job(client: TestClient) -> None:
    assert client.get("/api/jobs/999/threshold-analysis").status_code == 404


def test_clean_frame_is_served(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    job_id = _project_with_job(client, in_dir, out_dir, "frames")

    event = client.get(f"/api/jobs/{job_id}/events").json()["items"][0]
    assert event["frame_url"], "new scans must record a clean frame"
    resp = client.get(event["frame_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_yolo_export_ships_clean_images(client: TestClient, project_dirs) -> None:
    """A YOLO zip is only a dataset if it carries images — the clean ones."""
    import io
    import zipfile

    import cv2
    import numpy as np

    in_dir, out_dir = project_dirs
    job_id = _project_with_job(client, in_dir, out_dir, "yolo-images")
    event = client.get(f"/api/jobs/{job_id}/events").json()["items"][0]
    client.put(f"/api/events/{event['id']}/label", json={"verdict": "TP"})

    archive = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/jobs/{job_id}/export/yolo").content)
    )
    names = archive.namelist()
    label = f"labels/{event['event_id']}.txt"
    images = [n for n in names if n.startswith("images/")]
    assert label in names
    assert len(images) == 1, f"one image per label file, got {names}"
    assert images[0].rsplit("/", 1)[1].rsplit(".", 1)[0] == event["event_id"]

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
    in_dir, out_dir = project_dirs
    body = {"name": "no zone", "input_folder": str(in_dir), "output_folder": str(out_dir)}
    assert client.post("/api/projects", json=body).status_code == 422
    resp = client.post("/api/projects", json={**body, "config": {"frame_sample_fps": 2.0}})
    assert resp.status_code == 422 and "camera_timezone" in resp.text

    created = client.post("/api/projects", json={**body, "config": TEST_CONFIG}).json()
    # A config update replaces the stored one, so it can't drop the zone either.
    resp = client.patch(f"/api/projects/{created['id']}", json={"config": {"frame_sample_fps": 1.0}})
    assert resp.status_code == 422
