"""Camtrap DP tables and vocabularies (reefscanner.core.camtrap)."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError
from sqlalchemy import event as sa_event
from sqlalchemy.exc import StatementError
from sqlmodel import Session, SQLModel, create_engine, select

from reefscanner.core.camtrap import (
    VERDICT_FP,
    VERDICT_FP_OTHER,
    VERDICT_OBSERVATION_TYPE,
    VERDICT_TP,
    VERDICT_UNSURE,
    Deployment,
    Detection,
    Media,
    Observation,
    ObservationExtra,
    taxon_for_class,
    verdict_from_tags,
    verdict_tag,
)

MOZ = dt.timezone(dt.timedelta(hours=2))  # Mozambique, UTC+2
T0 = dt.datetime(2026, 11, 3, 9, 30, tzinfo=MOZ)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @sa_event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(
        engine,
        tables=[m.__table__ for m in (Deployment, Media, Observation, ObservationExtra, Detection)],
    )
    with Session(engine) as s:
        yield s


def make_event(session) -> None:
    """A deployment with one event: peak frame, machine observation, extras.

    Flushed parents-first: there are no ORM relationships to order the inserts.
    """
    session.add(Deployment(
        deploymentID="tofo-1", latitude=-23.85, longitude=35.55,
        deploymentStart=T0, deploymentEnd=T0 + dt.timedelta(hours=24),
        cameraDepth=18.0, baitUse=True,
    ))
    session.flush()
    session.add(Media(
        mediaID="tofo-1/e1/frame", deploymentID="tofo-1",
        captureMethod="activityDetection", timestamp=T0,
        filePath="media/e1.jpg", fileMediatype="image/jpeg",
    ))
    session.flush()
    session.add(Observation(
        observationID="e1/machine", deploymentID="tofo-1",
        mediaID="tofo-1/e1/frame", eventID="tofo-1/e1",
        eventStart=T0, eventEnd=T0 + dt.timedelta(seconds=13),
        observationLevel="media", observationType="animal",
        scientificName="Elasmobranchii",
        bboxX=0.1, bboxY=0.2, bboxWidth=0.3, bboxHeight=0.1,
        classificationMethod="machine", classificationProbability=0.64,
    ))
    session.flush()
    session.add(ObservationExtra(
        observationID="e1/machine", modelName="SharkTrack",
        modelVersion="models-v1", detectorBackend="onnx",
        detectorConfig={"ml_confidence_threshold": 0.2},
    ))
    session.add(Detection(
        observationID="e1/machine", frameTimestamp=T0,
        bboxX=0.1, bboxY=0.2, bboxWidth=0.3, bboxHeight=0.1, confidence=0.64,
    ))
    session.commit()


def test_rows_round_trip_with_their_timezone(session):
    make_event(session)
    session.expire_all()
    obs = session.exec(select(Observation)).one()
    assert obs.eventStart == T0
    assert obs.eventStart.utcoffset() == dt.timedelta(hours=2)
    extra = session.get(ObservationExtra, "e1/machine")
    assert extra.detectorConfig == {"ml_confidence_threshold": 0.2}


def test_naive_timestamps_are_refused(session):
    session.add(Deployment(
        deploymentID="x", latitude=0, longitude=0,
        deploymentStart=dt.datetime(2026, 11, 3, 9, 30),  # no timezone
    ))
    with pytest.raises(StatementError, match="needs a timezone"):
        session.commit()


def test_deleting_a_deployment_deletes_everything_under_it(session):
    make_event(session)
    session.delete(session.get(Deployment, "tofo-1"))
    session.commit()
    for model in (Media, Observation, ObservationExtra, Detection):
        assert session.exec(select(model)).all() == [], model.__name__


def test_constraints_are_checked_by_model_validate():
    """Table classes skip validation in __init__; the writer validates instead."""
    with pytest.raises(ValidationError, match="latitude"):
        Deployment.model_validate({"deploymentID": "x", "latitude": 95, "longitude": 0})
    with pytest.raises(ValidationError, match="bboxWidth"):
        Observation.model_validate({
            "observationID": "o", "deploymentID": "d", "eventStart": T0,
            "eventEnd": T0, "observationLevel": "media",
            "observationType": "animal", "bboxWidth": 1.5,
        })


def test_verdicts_map_to_observation_types():
    assert VERDICT_OBSERVATION_TYPE == {
        VERDICT_TP: "animal",
        VERDICT_FP: "blank",
        VERDICT_FP_OTHER: "animal",
        VERDICT_UNSURE: "unknown",
    }


def test_verdict_tags_round_trip_among_other_tags():
    for verdict in (VERDICT_TP, VERDICT_FP, VERDICT_FP_OTHER, VERDICT_UNSURE):
        assert verdict_from_tags(f"reviewed:yes|{verdict_tag(verdict)}") == verdict
    assert verdict_from_tags(None) is None
    assert verdict_from_tags("verdict:maybe") is None
    with pytest.raises(ValueError):
        verdict_tag("maybe")


def test_detector_classes_map_to_scientific_names():
    assert taxon_for_class("elasmobranch") == "Elasmobranchii"
    assert taxon_for_class("Elasmobranch") == "Elasmobranchii"
    assert taxon_for_class("car") is None
