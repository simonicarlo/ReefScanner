"""Writing and reading Camtrap DP packages, checked by the official validators.

Every written package is validated the way another tool would: the descriptor
against the Camtrap DP profile (JSON Schema), and the tables against their
Table Schemas by Frictionless. Both run offline, from the copies of the schemas
in the repo.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
from pathlib import Path

import jsonschema
import pytest

from reefscanner.core.camtrap import (
    Deployment,
    Detection,
    Media,
    Observation,
    ObservationExtra,
    Package,
    PackageError,
    read_package,
    verdict_tag,
    write_package,
)
from reefscanner.core.camtrap.package import field_names, table_schema_url

from camtrap_check import assert_valid_camtrap
MOZ = dt.timezone(dt.timedelta(hours=2))
T0 = dt.datetime(2026, 11, 3, 9, 30, tzinfo=MOZ)


def sample_package() -> Package:
    """One deployment, one event: clip and frame, machine and human observations."""
    end = T0 + dt.timedelta(seconds=13)
    machine = dict(
        deploymentID="tofo-1", mediaID="tofo-1/e1/frame", eventID="tofo-1/e1",
        eventStart=T0, eventEnd=end, observationLevel="media",
        bboxX=0.1, bboxY=0.2, bboxWidth=0.3, bboxHeight=0.1,
    )
    return Package(
        deployments=[Deployment(
            deploymentID="tofo-1", locationName="Manta Reef",
            latitude=-23.85, longitude=35.55,
            deploymentStart=T0 - dt.timedelta(minutes=5),
            deploymentEnd=T0 + dt.timedelta(hours=1),
            cameraModel="GoPro HERO12", cameraDepth=18.0, baitUse=True,
        )],
        media=[
            Media(mediaID="tofo-1/e1/clip", deploymentID="tofo-1",
                  captureMethod="activityDetection", timestamp=T0,
                  filePath="media/e1.mp4", fileMediatype="video/mp4"),
            Media(mediaID="tofo-1/e1/frame", deploymentID="tofo-1",
                  captureMethod="activityDetection", timestamp=T0,
                  filePath="media/e1.jpg", fileMediatype="image/jpeg",
                  exifData={"Make": "GoPro"}),
        ],
        observations=[
            Observation(observationID="tofo-1/e1/machine", observationType="animal",
                        scientificName="Elasmobranchii",
                        classificationMethod="machine",
                        classifiedBy="SharkTrack (ONNX, models-v1)",
                        classificationTimestamp=T0,
                        classificationProbability=0.64, **machine),
            Observation(observationID="tofo-1/e1/human", observationType="animal",
                        scientificName="Carcharhinus amblyrhynchos",
                        classificationMethod="human", classifiedBy="A. Reviewer",
                        observationTags=verdict_tag("TP"), **machine),
        ],
        observation_extras=[ObservationExtra(
            observationID="tofo-1/e1/machine", modelName="SharkTrack",
            modelVersion="models-v1", detectorBackend="onnx",
            detectorConfig={"ml_confidence_threshold": 0.2},
        )],
        detections=[
            Detection(observationID="tofo-1/e1/machine",
                      frameTimestamp=T0 + dt.timedelta(seconds=s),
                      bboxX=0.1, bboxY=0.2, bboxWidth=0.3, bboxHeight=0.1,
                      confidence=c)
            for s, c in [(0, 0.41), (1, 0.64), (2, 0.38)]
        ],
        metadata={
            "title": "Tofo BRUV test",
            "project": {"title": "Tofo reef megafauna"},
            "contributors": [{"title": "A. Reviewer", "role": "contact"}],
        },
    )


def test_written_package_is_valid_camtrap_dp(tmp_path) -> None:
    write_package(tmp_path, sample_package())
    assert_valid_camtrap(tmp_path)


def test_package_round_trips(tmp_path) -> None:
    original = sample_package()
    write_package(tmp_path, original)
    back = read_package(tmp_path)

    for table in ("deployments", "media", "observations",
                  "reefscanner-observations"):
        assert [r.model_dump() for r in back.rows(table)] == [
            r.model_dump() for r in original.rows(table)
        ], table
    # Detections get their database id only once stored.
    assert [r.model_dump(exclude={"id"}) for r in back.detections] == [
        r.model_dump(exclude={"id"}) for r in original.detections
    ]
    assert back.deployments[0].deploymentStart.utcoffset() == dt.timedelta(hours=2)
    assert back.metadata["project"]["title"] == "Tofo reef megafauna"


def test_derived_metadata(tmp_path) -> None:
    write_package(tmp_path, sample_package())
    meta = json.loads((tmp_path / "datapackage.json").read_text())
    assert meta["profile"].endswith("/1.0.2/camtrap-dp-profile.json")
    assert meta["name"] == "reefscanner-tofo-1"
    assert meta["spatial"] == {"type": "Point", "coordinates": [35.55, -23.85]}
    assert meta["temporal"] == {"start": "2026-11-03", "end": "2026-11-03"}
    assert meta["taxonomic"] == [
        {"scientificName": "Carcharhinus amblyrhynchos"},
        {"scientificName": "Elasmobranchii"},
    ]
    # The design note's defaults fill the project block's required fields.
    assert meta["project"]["observationLevel"] == ["media"]
    assert {r["name"] for r in meta["resources"]} == {
        "deployments", "media", "observations",
        "reefscanner-observations", "reefscanner-detections",
    }
    assert meta["resources"][0]["schema"] == table_schema_url("deployments")


def test_several_deployments_span_a_polygon(tmp_path) -> None:
    package = sample_package()
    second = package.deployments[0].model_copy(
        update={"deploymentID": "tofo-2", "latitude": -23.9, "longitude": 35.6}
    )
    package.deployments.append(second)
    write_package(tmp_path, package)
    meta = json.loads((tmp_path / "datapackage.json").read_text())
    assert meta["spatial"]["type"] == "Polygon"
    assert meta["name"] == "reefscanner-tofo-1-and-1-more"
    assert_valid_camtrap(tmp_path)


def test_csv_columns_follow_the_standard(tmp_path) -> None:
    write_package(tmp_path, sample_package())
    for table in ("deployments", "media", "observations"):
        with open(tmp_path / f"{table}.csv", newline="") as fh:
            assert next(csv.reader(fh)) == field_names(table)


def test_timestamps_are_written_with_offset_and_whole_seconds(tmp_path) -> None:
    package = sample_package()
    package.media[0].timestamp = T0 + dt.timedelta(microseconds=250_000)
    write_package(tmp_path, package)
    with open(tmp_path / "media.csv", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["timestamp"] == "2026-11-03T09:30:00+02:00"


def test_empty_sidecars_are_left_out(tmp_path) -> None:
    package = sample_package()
    package.observation_extras.clear()
    package.detections.clear()
    write_package(tmp_path, package)
    names = {r["name"] for r in json.loads((tmp_path / "datapackage.json").read_text())["resources"]}
    assert names == {"deployments", "media", "observations"}
    assert not (tmp_path / "reefscanner-detections.csv").exists()
    assert_valid_camtrap(tmp_path)


@pytest.mark.parametrize("break_it, expected", [
    (lambda p: setattr(p.deployments[0], "deploymentEnd", None),
     "deploymentEnd is required"),
    (lambda p: setattr(p.observations[0], "observationType", "fish"),
     "observationType='fish' is not one of"),
    (lambda p: setattr(p.observations[0], "bboxWidth", 1.4),
     "bboxWidth=1.4 is above 1"),
    (lambda p: setattr(p.observations[0], "mediaID", "nope"),
     "mediaID 'nope' is not in media"),
    (lambda p: setattr(p.observations[1], "bboxHeight", None),
     "bounding box is partial"),
    (lambda p: setattr(p.detections[0], "observationID", "ghost"),
     "observationID 'ghost' is not in observations"),
    (lambda p: setattr(p.media[1], "mediaID", "tofo-1/e1/clip"),
     "duplicate mediaID"),
    (lambda p: setattr(p.deployments[0], "latitude", -95.0),
     "latitude=-95.0 is below -90"),
    (lambda p: p.metadata["project"].pop("title"),
     "project.title is required"),
    (lambda p: setattr(p.media[0], "timestamp", dt.datetime(2026, 11, 3, 9, 30)),
     "timestamp has no timezone"),
])
def test_invalid_packages_are_refused_before_writing(tmp_path, break_it, expected) -> None:
    package = sample_package()
    break_it(package)
    with pytest.raises(PackageError, match="problem") as info:
        write_package(tmp_path, package)
    assert any(expected in p for p in info.value.problems), info.value.problems
    assert not (tmp_path / "datapackage.json").exists()


def test_every_problem_is_reported_at_once(tmp_path) -> None:
    package = sample_package()
    package.deployments[0].deploymentEnd = None
    package.observations[0].observationType = "fish"
    with pytest.raises(PackageError) as info:
        write_package(tmp_path, package)
    assert len(info.value.problems) >= 2


def test_reader_refuses_another_version(tmp_path) -> None:
    write_package(tmp_path, sample_package())
    path = tmp_path / "datapackage.json"
    meta = json.loads(path.read_text())
    meta["profile"] = meta["profile"].replace("1.0.2", "1.0")
    path.write_text(json.dumps(meta))
    with pytest.raises(PackageError, match="Camtrap DP 1.0.2 only"):
        read_package(tmp_path)


def test_reader_handles_gzipped_tables(tmp_path) -> None:
    """The standard allows large tables as .csv.gz."""
    write_package(tmp_path, sample_package())
    src = tmp_path / "reefscanner-detections.csv"
    with open(src, "rb") as fh, gzip.open(str(src) + ".gz", "wb") as gz:
        gz.write(fh.read())
    src.unlink()
    path = tmp_path / "datapackage.json"
    meta = json.loads(path.read_text())
    for r in meta["resources"]:
        if r["name"] == "reefscanner-detections":
            r["path"] += ".gz"
    path.write_text(json.dumps(meta))
    assert len(read_package(tmp_path).detections) == 3


def test_reader_reports_bad_rows(tmp_path) -> None:
    write_package(tmp_path, sample_package())
    path = tmp_path / "media.csv"
    path.write_text(path.read_text().replace("2026-11-03T09:30:00+02:00", "2026-11-03T09:30:00"))
    with pytest.raises(PackageError, match="without a timezone"):
        read_package(tmp_path)


def test_the_validators_catch_a_broken_package(tmp_path) -> None:
    """Guards the guard: the outside validators must fail on bad data."""
    write_package(tmp_path, sample_package())
    obs = tmp_path / "observations.csv"
    obs.write_text(obs.read_text().replace(",animal,", ",fish,", 1))
    with pytest.raises(AssertionError):
        assert_valid_camtrap(tmp_path)

    write_package(tmp_path, sample_package())
    path = tmp_path / "datapackage.json"
    meta = json.loads(path.read_text())
    del meta["contributors"]
    path.write_text(json.dumps(meta))
    with pytest.raises(jsonschema.ValidationError, match="contributors"):
        assert_valid_camtrap(tmp_path)
