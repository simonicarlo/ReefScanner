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
    from reefscanner import ReefScannerConfig

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
            "config": {"frame_sample_fpz": 2.0},
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
    from reefscanner.engine.results import CSV_COLUMNS

    header = csv_body.text.splitlines()[0]
    assert header == ",".join(CSV_COLUMNS), "v1 CSV contract must be preserved"
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


def test_csv_import_bridge(client: TestClient, tmp_path) -> None:
    """A v1 output folder can be adopted into a project without re-running.

    The input folder is deliberately empty: the point is to attach existing
    results, not to reanalyse footage that may not even be on this machine any
    more.
    """
    from reefscanner.engine.results import CSV_COLUMNS

    in_dir = tmp_path / "legacy_in"
    in_dir.mkdir()
    out_dir = tmp_path / "legacy_out"
    out_dir.mkdir()
    (out_dir / "reefscanner_results.csv").write_text(
        ",".join(CSV_COLUMNS)
        + "\n"
        + "dive01_001,/x/dive01.mp4,4.0,8.0,4.0,,1200.0,,,,,yes,whitetip,seen it\n"
    )

    project_id = client.post(
        "/api/projects",
        json={
            "name": "legacy",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, job_id)

    resp = client.post(f"/api/jobs/{job_id}/import/csv")
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1

    # Re-importing is a no-op rather than a duplicate.
    assert client.post(f"/api/jobs/{job_id}/import/csv").json()["imported"] == 0

    page = client.get(f"/api/jobs/{job_id}/events").json()
    imported = [e for e in page["items"] if e["event_id"] == "dive01_001"]
    assert len(imported) == 1
    # The hand-typed 'yes' should have been carried over as a TP verdict.
    assert imported[0]["label"]["verdict"] == "TP"
    assert imported[0]["label"]["species"] == "whitetip"


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
