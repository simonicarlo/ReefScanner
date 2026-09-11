"""Serving clips and thumbnails.

Files are addressed by *event id*, never by a path from the client. The paths
live in the database and are resolved server-side, and every resolved path is
then checked to be inside the owning project's output folder. That check is the
point of this module: a naive ``/media?path=…`` endpoint on a local server is
still an arbitrary-file-read for anything else running on the machine.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from ..deps import get_session
from ..models import Event, Job, Project

router = APIRouter(prefix="/api/media", tags=["media"])


def _resolve(session: Session, event_id: int, kind: str) -> Path:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    raw = {
        "clip": event.clip_path,
        "thumbnail": event.thumbnail_path,
        "frame": event.frame_path,
    }.get(kind)
    if not raw:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Event has no {kind}")

    path = Path(raw).resolve()

    job = session.get(Job, event.job_id)
    project = session.get(Project, job.project_id) if job else None
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    root = Path(project.output_folder).expanduser().resolve()
    if not path.is_relative_to(root):
        # Only reachable if the database was tampered with, but a media
        # endpoint that will read any absolute path is not one to ship.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Media outside project")

    if not path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"{kind.capitalize()} file is missing on disk"
        )
    return path


@router.get("/clip/{event_id}")
def get_clip(event_id: int, session: Session = Depends(get_session)) -> FileResponse:
    path = _resolve(session, event_id, "clip")
    # FileResponse handles Range requests, which is what lets the review
    # player seek within a clip instead of re-downloading it.
    return FileResponse(path, filename=path.name)


@router.get("/thumbnail/{event_id}")
def get_thumbnail(
    event_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    path = _resolve(session, event_id, "thumbnail")
    return FileResponse(path, filename=path.name)


@router.get("/frame/{event_id}")
def get_frame(event_id: int, session: Session = Depends(get_session)) -> FileResponse:
    """The clean peak frame, without the detection box drawn on it."""
    path = _resolve(session, event_id, "frame")
    return FileResponse(path, filename=path.name)
