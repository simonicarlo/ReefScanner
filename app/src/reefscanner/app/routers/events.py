"""Events and reviews — the triage loop, on Camtrap DP observations.

An "event" here is a run's machine observation with its sidecar row (where in
the footage, which detector class) and, once reviewed, the human observation
on the same Camtrap event. A review writes or replaces that human observation,
following the verdict table in docs/specs/v3/features/ (data-model note).

The list endpoint carries the filters the review UI needs (class, confidence
floor, reviewed-or-not) plus the counts it shows above the grid, so the grid is
one request rather than one per widget.
"""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement
from sqlalchemy.orm import aliased
from sqlmodel import Session, and_, func, select

from reefscanner.core.camtrap import (
    VERDICT_FP,
    VERDICT_FP_OTHER,
    VERDICT_OBSERVATION_TYPE,
    VERDICT_TP,
    Observation,
    ObservationExtra,
    verdict_from_tags,
    verdict_tag,
)
from .. import metadata
from ..deps import get_session
from ..models import Job, scan_id
from ..schemas import EventPage, EventRead, ReviewRead, ReviewWrite, RunSummary

router = APIRouter(prefix="/api", tags=["events"])

Human = aliased(Observation)


def _human_join() -> ColumnElement[bool]:
    """Join condition: the human observation on the same Camtrap event."""
    return and_(
        Human.eventID == Observation.eventID,
        Human.classificationMethod == "human",
    )


def _frame_url(event_id: str) -> str:
    return f"/api/media/frame/{event_id}"


def _box(o: Observation | None) -> list[float] | None:
    if o is None or o.bboxX is None:
        return None
    return [o.bboxX, o.bboxY, o.bboxWidth, o.bboxHeight]


def _review(human: Observation | None) -> ReviewRead | None:
    if human is None:
        return None
    return ReviewRead(
        verdict=verdict_from_tags(human.observationTags) or "unsure",
        scientific_name=human.scientificName,
        notes=human.observationComments,
        bbox=_box(human),
        reviewed_at=human.classificationTimestamp,
    )


def _job_id(extra: ObservationExtra) -> int:
    return int((extra.scanID or "scan-0").removeprefix("scan-"))


def _clip_start(extra: ObservationExtra, start: float) -> float | None:
    """Where the event's clip starts in the source video, as core's
    extract_clip cuts it: the event start less the run's padding."""
    pad = (extra.detectorConfig or {}).get("pad_seconds")
    if not isinstance(pad, (int, float)) or isinstance(pad, bool):
        return None
    return max(0.0, start - float(pad))


def _event_read(
    machine: Observation, extra: ObservationExtra, human: Observation | None
) -> EventRead:
    start = extra.videoStartSeconds or 0.0
    end = extra.videoEndSeconds or start
    return EventRead(
        id=machine.eventID,
        job_id=_job_id(extra),
        source_video=extra.sourceVideo or "",
        start_seconds=start,
        end_seconds=end,
        duration_seconds=end - start,
        peak_seconds=extra.peakSeconds or start,
        clip_start_seconds=_clip_start(extra, start),
        start_time=machine.eventStart,
        confidence=machine.classificationProbability,
        detected_class=extra.detectorClass,
        scientific_name=machine.scientificName,
        bbox=_box(machine),
        clip_url=f"/api/media/clip/{machine.eventID}",
        frame_url=_frame_url(machine.eventID),
        review=_review(human),
    )


def _machine(session: Session, event_id: str) -> tuple[Observation, ObservationExtra]:
    machine = session.get(Observation, f"{event_id}:machine")
    extra = session.get(ObservationExtra, f"{event_id}:machine")
    if machine is None or extra is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return machine, extra


@router.get("/jobs/{job_id}/events", response_model=EventPage)
def list_events(
    job_id: int,
    session: Session = Depends(get_session),
    detected_class: str | None = None,
    min_confidence: float | None = None,
    labeled: bool | None = Query(
        default=None,
        description="True = only reviewed events, False = only the queue.",
    ),
    verdict: str | None = None,
    source_video: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> EventPage:
    if session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    # Outer join so unreviewed events — the ones actually needing review — are
    # the default result, not the missing one.
    base = (
        select(Observation, ObservationExtra, Human)
        .join(ObservationExtra, ObservationExtra.observationID == Observation.observationID)
        .join(Human, _human_join(), isouter=True)
        .where(ObservationExtra.scanID == scan_id(job_id))
        .where(Observation.classificationMethod == "machine")
    )
    if detected_class:
        base = base.where(ObservationExtra.detectorClass == detected_class)
    if min_confidence is not None:
        base = base.where(Observation.classificationProbability >= min_confidence)
    if source_video:
        base = base.where(ObservationExtra.sourceVideo == source_video)
    if labeled is True:
        base = base.where(Human.observationID.is_not(None))
    elif labeled is False:
        base = base.where(Human.observationID.is_(None))
    if verdict:
        base = base.where(Human.observationTags == verdict_tag(verdict))

    total = session.exec(select(func.count()).select_from(base.subquery())).one()
    rows = session.exec(
        base.order_by(ObservationExtra.sourceVideo, ObservationExtra.videoStartSeconds)
        .offset(offset)
        .limit(limit)
    ).all()

    # Counts describe the whole run, not the filtered page — they're a progress
    # readout ("340 of 900 reviewed"), so a filter must not move them.
    return EventPage(
        items=[_event_read(m, e, h) for m, e, h in rows],
        total=total,
        limit=limit,
        offset=offset,
        n_labeled=_reviewed(session, job_id),
        n_tp=_reviewed(session, job_id, VERDICT_TP),
        n_fp=_reviewed(session, job_id, VERDICT_FP, VERDICT_FP_OTHER),
    )


def _machine_in_run(job_id: int):
    """A run's machine observations, with their sidecar rows."""
    return (
        select(Observation)
        .join(ObservationExtra, ObservationExtra.observationID == Observation.observationID)
        .where(ObservationExtra.scanID == scan_id(job_id))
        .where(Observation.classificationMethod == "machine")
    )


def _reviewed(session: Session, job_id: int, *verdicts: str) -> int:
    """How many of a run's events have a verdict, or one of ``verdicts``."""
    stmt = _machine_in_run(job_id).join(Human, _human_join())
    if verdicts:
        stmt = stmt.where(Human.observationTags.in_([verdict_tag(v) for v in verdicts]))
    return session.exec(select(func.count()).select_from(stmt.subquery())).one()


def run_summary(session: Session, job: Job) -> RunSummary:
    """Where the review of one run stands, and the frame that stands for it."""
    events = session.exec(
        select(func.count()).select_from(_machine_in_run(job.id).subquery())
    ).one()
    cover = session.exec(
        _machine_in_run(job.id)
        .join(Human, _human_join())
        .where(Human.observationTags == verdict_tag(VERDICT_TP))
        .order_by(Observation.eventStart.desc())
        .limit(1)
    ).first() or session.exec(
        _machine_in_run(job.id)
        .order_by(ObservationExtra.sourceVideo, ObservationExtra.videoStartSeconds)
        .limit(1)
    ).first()
    return RunSummary(
        job_id=job.id,
        events=events,
        reviewed=_reviewed(session, job.id),
        confirmed=_reviewed(session, job.id, VERDICT_TP),
        rejected=_reviewed(session, job.id, VERDICT_FP, VERDICT_FP_OTHER),
        cover_url=_frame_url(cover.eventID) if cover else None,
    )


@router.get("/jobs/{job_id}/classes", response_model=list[str])
def list_classes(job_id: int, session: Session = Depends(get_session)) -> list[str]:
    """Distinct detector classes in this run — populates the filter dropdown."""
    rows = session.exec(
        select(ObservationExtra.detectorClass)
        .where(ObservationExtra.scanID == scan_id(job_id))
        .where(ObservationExtra.detectorClass.is_not(None))
        .distinct()
    ).all()
    return sorted(r for r in rows if r)


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(event_id: str, session: Session = Depends(get_session)) -> EventRead:
    machine, extra = _machine(session, event_id)
    return _event_read(machine, extra, session.get(Observation, f"{event_id}:human"))


@router.put("/events/{event_id}/review", response_model=EventRead)
def put_review(
    event_id: str,
    payload: ReviewWrite,
    session: Session = Depends(get_session),
) -> EventRead:
    """Record (or revise) the verdict on an event, as a human observation.

    Revised in place rather than appended: reviewers change their minds, and
    the current opinion is the thing that matters.
    """
    machine, extra = _machine(session, event_id)
    human = session.get(Observation, f"{event_id}:human") or Observation(
        observationID=f"{event_id}:human",
        deploymentID=machine.deploymentID,
        mediaID=machine.mediaID,
        eventID=machine.eventID,
        eventStart=machine.eventStart,
        eventEnd=machine.eventEnd,
        observationLevel=machine.observationLevel,
        observationType="unclassified",
    )

    verdict = payload.verdict
    human.observationType = VERDICT_OBSERVATION_TYPE[verdict]
    # A TP keeps the detector's taxon unless the reviewer names the species;
    # an FP-other names what it was instead, if anyone knows.
    if verdict == VERDICT_TP:
        human.scientificName = payload.scientific_name or machine.scientificName
    elif verdict == VERDICT_FP_OTHER:
        human.scientificName = payload.scientific_name
    else:
        human.scientificName = None
    # A box only means something where there is something to box.
    box = (payload.bbox or _box(machine)) if verdict in (VERDICT_TP, VERDICT_FP_OTHER) else None
    human.bboxX, human.bboxY, human.bboxWidth, human.bboxHeight = box or (None,) * 4
    human.classificationMethod = "human"
    human.classifiedBy = metadata.signed_as(session)
    human.classificationTimestamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    human.classificationProbability = None
    human.observationTags = verdict_tag(verdict)
    human.observationComments = payload.notes or None

    session.add(human)
    session.commit()
    session.refresh(human)
    return _event_read(machine, extra, human)


@router.delete("/events/{event_id}/review", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(event_id: str, session: Session = Depends(get_session)) -> None:
    """Un-review an event, putting it back in the queue."""
    human = session.get(Observation, f"{event_id}:human")
    if human is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event is not reviewed")
    session.delete(human)
    session.commit()


@router.get("/jobs/{job_id}/species", response_model=list[str])
def list_species(job_id: int, session: Session = Depends(get_session)) -> list[str]:
    """Scientific names already used in this run's reviews, for suggestions.

    Reusing what's been typed before is what keeps a free-text field from
    turning into 'Carcharhinus', 'carcharhinus' and 'Carcharinus'.
    """
    rows = session.exec(
        select(Human.scientificName)
        .join(Observation, _human_join())
        .join(ObservationExtra, ObservationExtra.observationID == Observation.observationID)
        .where(ObservationExtra.scanID == scan_id(job_id))
        .where(Human.scientificName.is_not(None))
        .distinct()
    ).all()
    return sorted({r.strip() for r in rows if r and r.strip()})
