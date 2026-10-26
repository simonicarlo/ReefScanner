"""Turning review verdicts into a confidence recommendation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import aliased
from sqlmodel import Session, and_, select

from reefscanner.core.camtrap import (
    VERDICT_FP,
    VERDICT_FP_OTHER,
    Observation,
    ObservationExtra,
    verdict_from_tags,
)
from ..analysis import analyse_thresholds
from ..deps import get_session
from ..models import Job, Project, scan_id

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/jobs/{job_id}/threshold-analysis")
def threshold_analysis(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    human = aliased(Observation)
    rows = session.exec(
        select(Observation.classificationProbability, human.observationTags)
        .join(ObservationExtra, ObservationExtra.observationID == Observation.observationID)
        .join(human, and_(
            human.eventID == Observation.eventID,
            human.classificationMethod == "human",
        ))
        .where(ObservationExtra.scanID == scan_id(job_id))
        .where(Observation.classificationMethod == "machine")
    ).all()

    # Either kind of false positive is a detection that shouldn't have fired.
    def verdict(tags: str | None) -> str:
        v = verdict_from_tags(tags) or "unsure"
        return VERDICT_FP if v == VERDICT_FP_OTHER else v

    # The threshold the scan actually ran at bounds what can be simulated:
    # nothing below it was ever emitted, so nothing below it can be analysed.
    project = session.get(Project, job.project_id)
    scan_threshold = None
    if project is not None:
        from ..jobs import config_for

        scan_threshold = config_for(project).ml_confidence_threshold

    result = analyse_thresholds(
        [(p, verdict(t)) for p, t in rows], scan_threshold=scan_threshold
    )
    return {
        "labeled": result.labeled,
        "confirmed": result.confirmed,
        "rejected": result.rejected,
        "undecided": result.undecided,
        "unscored": result.unscored,
        "reliable": result.reliable,
        "scan_threshold": result.scan_threshold,
        "recommended": result.recommended,
        "recommendation": result.recommendation,
        "points": [
            {
                "threshold": p.threshold,
                "kept": p.kept,
                "confirmed_kept": p.confirmed_kept,
                "rejected_kept": p.rejected_kept,
                "confirmed_lost": p.confirmed_lost,
                "precision": p.precision,
            }
            for p in result.points
        ],
    }
