"""Export endpoints: a run's Camtrap DP package, and training sets."""

from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlmodel import Session

from reefscanner.core.camtrap import PackageError, write_package
from ..deps import get_session
from ..exports import build_package, confirmed_events, export_coco, export_yolo, yolo_stem
from ..models import Job, Project, run_folder

router = APIRouter(prefix="/api", tags=["exports"])


def _job_and_project(session: Session, job_id: int) -> tuple[Job, Project]:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    project = session.get(Project, job.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return job, project


@router.post("/jobs/{job_id}/package", response_model=dict)
def write_job_package(job_id: int, session: Session = Depends(get_session)) -> dict:
    """Write the run as a Camtrap DP package into its run folder.

    The clips and frames are already there, so the folder becomes a complete,
    self-contained package: copying it is exporting it.
    """
    job, project = _job_and_project(session, job_id)
    package = build_package(session, project, job)
    try:
        path = write_package(run_folder(project, job.id), package)
    except PackageError as exc:
        # The problems describe the package's content, not internals.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "The run isn't a valid Camtrap DP package yet",
             "problems": exc.problems},
        ) from exc
    return {
        "path": str(path.parent),
        "observations": len(package.observations),
        "media": len(package.media),
    }


@router.get("/jobs/{job_id}/export/coco")
def export_job_coco(job_id: int, session: Session = Depends(get_session)) -> Response:
    job, project = _job_and_project(session, job_id)
    return Response(
        export_coco(confirmed_events(session, project, job)),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="coco_scan{job_id}.json"'},
    )


@router.get("/jobs/{job_id}/export/yolo")
def export_job_yolo(job_id: int, session: Session = Depends(get_session)) -> Response:
    """A YOLO dataset as a zip: labels, images, and the class order.

    A zip rather than loose files because YOLO's format is a *directory* — the
    per-image label files are meaningless without their images, or without the
    ``classes.txt`` that fixes the class-index order. An image missing from
    disk is skipped rather than failing the whole export.
    """
    job, project = _job_and_project(session, job_id)
    confirmed = [c for c in confirmed_events(session, project, job) if c.image.is_file()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in export_yolo(confirmed).items():
            zf.writestr(name, content)
        for item in confirmed:
            zf.write(item.image, f"images/{yolo_stem(item)}{item.image.suffix}")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="yolo_scan{job_id}.zip"'},
    )
