"""Export endpoints: CSV back out, and annotations for fine-tuning."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlmodel import Session, select

from ..deps import get_session
from ..exports import (
    annotation_image,
    export_coco,
    export_csv,
    export_yolo,
)
from ..models import Event, Job, Label

router = APIRouter(prefix="/api", tags=["exports"])


def _pairs(session: Session, job_id: int) -> list[tuple[Event, Label | None]]:
    if session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return list(
        session.exec(
            select(Event, Label)
            .join(Label, Label.event_id == Event.id, isouter=True)
            .where(Event.job_id == job_id)
            .order_by(Event.source_video, Event.start_seconds)
        ).all()
    )


@router.get("/jobs/{job_id}/export/csv")
def export_job_csv(job_id: int, session: Session = Depends(get_session)) -> Response:
    """The v1 results CSV, with the label columns now filled in."""
    body = export_csv(_pairs(session, job_id))
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="reefscanner_job{job_id}.csv"'
        },
    )


@router.get("/jobs/{job_id}/export/coco")
def export_job_coco(job_id: int, session: Session = Depends(get_session)) -> Response:
    body = export_coco(_pairs(session, job_id))
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="coco_job{job_id}.json"'
        },
    )


@router.get("/jobs/{job_id}/export/yolo")
def export_job_yolo(job_id: int, session: Session = Depends(get_session)) -> Response:
    """A YOLO dataset as a zip: labels, images, and the class order.

    A zip rather than loose files because YOLO's format is a *directory* — the
    per-image label files are meaningless without their images, or without the
    ``classes.txt`` that fixes the class-index order.

    Images are the clean frames, so the model never sees the drawn box. An
    image missing from disk is skipped rather than failing the whole export.
    """
    pairs = _pairs(session, job_id)
    files = export_yolo(pairs)
    images = {event.event_id: annotation_image(event) for event, _ in pairs}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
            if not name.startswith("labels/"):
                continue
            # YOLO pairs a label with its image by filename stem.
            stem = Path(name).stem
            image = images.get(stem)
            if image and Path(image).is_file():
                zf.write(image, f"images/{stem}{Path(image).suffix}")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="yolo_job{job_id}.zip"'
        },
    )
