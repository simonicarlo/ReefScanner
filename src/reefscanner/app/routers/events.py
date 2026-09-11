"""Events and labels — the triage loop.

The list endpoint carries the filters the review UI needs (class, confidence
floor, labeled-or-not) plus the counts it shows above the grid, so the grid is
one request rather than one-per-widget.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, func, select

from ..deps import get_session
from ..models import VERDICT_FP, VERDICT_TP, Event, Job, Label
from ..schemas import EventPage, EventRead, LabelRead, LabelWrite

router = APIRouter(prefix="/api", tags=["events"])


def _label_read(label: Optional[Label]) -> Optional[LabelRead]:
    if label is None:
        return None
    return LabelRead(
        verdict=label.verdict,
        species=label.species,
        notes=label.notes,
        tight_bbox=label.tight_bbox,
        updated_at=label.updated_at,
    )


def _event_read(event: Event, label: Optional[Label]) -> EventRead:
    return EventRead(
        id=event.id,
        job_id=event.job_id,
        event_id=event.event_id,
        source_video=event.source_video,
        start_seconds=event.start_seconds,
        end_seconds=event.end_seconds,
        duration_seconds=event.duration_seconds,
        peak_timestamp=event.peak_timestamp,
        peak_score=event.peak_score,
        peak_bbox=event.peak_bbox,
        motion_score=event.motion_score,
        ml_confidence=event.ml_confidence,
        detected_class=event.detected_class,
        start_timestamp=event.start_timestamp,
        frame_width=event.frame_width,
        frame_height=event.frame_height,
        clip_url=f"/api/media/clip/{event.id}" if event.clip_path else None,
        thumbnail_url=f"/api/media/thumbnail/{event.id}" if event.thumbnail_path else None,
        frame_url=f"/api/media/frame/{event.id}" if event.frame_path else None,
        label=_label_read(label),
    )


@router.get("/jobs/{job_id}/events", response_model=EventPage)
def list_events(
    job_id: int,
    session: Session = Depends(get_session),
    detected_class: Optional[str] = None,
    min_confidence: Optional[float] = None,
    labeled: Optional[bool] = Query(
        default=None,
        description="True = only reviewed events, False = only the queue.",
    ),
    verdict: Optional[str] = None,
    source_video: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> EventPage:
    if session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    # Outer join so unlabeled events — the ones actually needing review — are
    # the default result, not the missing one.
    base = (
        select(Event, Label)
        .join(Label, Label.event_id == Event.id, isouter=True)
        .where(Event.job_id == job_id)
    )
    if detected_class:
        base = base.where(Event.detected_class == detected_class)
    if min_confidence is not None:
        base = base.where(Event.ml_confidence >= min_confidence)
    if source_video:
        base = base.where(Event.source_video == source_video)
    if labeled is True:
        base = base.where(Label.id.is_not(None))
    elif labeled is False:
        base = base.where(Label.id.is_(None))
    if verdict:
        base = base.where(Label.verdict == verdict)

    total = len(session.exec(base).all())
    rows = session.exec(
        base.order_by(Event.source_video, Event.start_seconds)
        .offset(offset)
        .limit(limit)
    ).all()

    # Counts describe the whole job, not the filtered page — they're a progress
    # readout ("340 of 900 reviewed"), so a filter must not move them.
    def _count(*conditions) -> int:
        stmt = (
            select(func.count())
            .select_from(Event)
            .join(Label, Label.event_id == Event.id)
            .where(Event.job_id == job_id)
        )
        for cond in conditions:
            stmt = stmt.where(cond)
        return session.exec(stmt).one()

    return EventPage(
        items=[_event_read(e, lab) for e, lab in rows],
        total=total,
        limit=limit,
        offset=offset,
        n_labeled=_count(),
        n_tp=_count(Label.verdict == VERDICT_TP),
        n_fp=_count(Label.verdict == VERDICT_FP),
    )


@router.get("/jobs/{job_id}/classes", response_model=list[str])
def list_classes(job_id: int, session: Session = Depends(get_session)) -> list[str]:
    """Distinct detected classes in this job — populates the filter dropdown."""
    rows = session.exec(
        select(Event.detected_class)
        .where(Event.job_id == job_id)
        .where(Event.detected_class.is_not(None))
        .distinct()
    ).all()
    return sorted(r for r in rows if r)


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(event_id: int, session: Session = Depends(get_session)) -> EventRead:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return _event_read(event, event.label)


@router.put("/events/{event_id}/label", response_model=EventRead)
def upsert_label(
    event_id: int,
    payload: LabelWrite,
    session: Session = Depends(get_session),
) -> EventRead:
    """Record (or revise) the verdict on an event.

    An upsert rather than a create: reviewers change their minds, and the
    current opinion is the thing that matters.
    """
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    label = session.exec(select(Label).where(Label.event_id == event_id)).first()
    if label is None:
        label = Label(event_id=event_id, verdict=payload.verdict)
    label.verdict = payload.verdict
    label.species = payload.species
    label.notes = payload.notes
    label.tight_bbox = payload.tight_bbox
    label.updated_at = _dt.datetime.now(_dt.timezone.utc)
    session.add(label)
    session.commit()
    session.refresh(event)
    return _event_read(event, label)


@router.delete("/events/{event_id}/label", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(event_id: int, session: Session = Depends(get_session)) -> None:
    """Un-review an event, putting it back in the queue."""
    label = session.exec(select(Label).where(Label.event_id == event_id)).first()
    if label is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event is not labeled")
    session.delete(label)
    session.commit()


@router.get("/jobs/{job_id}/species", response_model=list[str])
def list_species(job_id: int, session: Session = Depends(get_session)) -> list[str]:
    """Species already used in this job — feeds the combo box's suggestions.

    Reusing what's been typed before is what keeps a free-text field from
    turning into 'Carcharhinus', 'carcharhinus' and 'Carcharinus'.
    """
    rows = session.exec(
        select(Label.species)
        .join(Event, Event.id == Label.event_id)
        .where(Event.job_id == job_id)
        .where(Label.species.is_not(None))
        .distinct()
    ).all()
    return sorted({r.strip() for r in rows if r and r.strip()})
