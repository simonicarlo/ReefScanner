"""Export endpoints: CSV back out, and annotations for fine-tuning."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlmodel import Session, select

from ..deps import get_session
from ..exports import export_coco, export_csv, export_yolo, import_csv_events
from ..models import Event, Job, Label, Project

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
    """YOLO annotations as a zip.

    A zip rather than loose files because YOLO's format is a *directory* — the
    per-image label files are meaningless without the ``classes.txt`` that
    fixes the class-index order.
    """
    files = export_yolo(_pairs(session, job_id))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="yolo_job{job_id}.zip"'
        },
    )


@router.post("/jobs/{job_id}/import/csv", response_model=dict)
def import_job_csv(job_id: int, session: Session = Depends(get_session)) -> dict:
    """Adopt the results CSV sitting in the project's output folder.

    This is the bridge for runs made before the database existed: point a
    project at an old output folder, create a job, and import.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    project = session.get(Project, job.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    csv_name = (project.config or {}).get("csv_name", "reefscanner_results.csv")
    csv_path = Path(project.output_folder).expanduser() / csv_name
    if not csv_path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No results CSV at {csv_path}"
        )

    added = import_csv_events(session, job_id, csv_path)
    return {"imported": added, "source": str(csv_path)}
