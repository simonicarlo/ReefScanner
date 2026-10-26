"""Serving clips and clean frames.

Files are addressed by *event id*, never by a path from the client. The path
comes from the event's Camtrap media row (relative to its run folder), and the
resolved path is then checked to be inside the owning project's output folder.
That check is the point of this module: a naive ``/media?path=…`` endpoint on a
local server is an arbitrary-file-read for anything else on the machine.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from reefscanner.core.camtrap import Media, ObservationExtra
from ..deps import get_session
from ..models import Job, Project, run_folder

router = APIRouter(prefix="/api/media", tags=["media"])

MEDIA_KINDS = ("clip", "frame")


def resolve_media(session: Session, event_id: str, kind: str) -> Path:
    """The file behind an event's clip or frame, checked to be in its project."""
    media = session.get(Media, f"{event_id}:{kind}")
    extra = session.get(ObservationExtra, f"{event_id}:machine")
    if media is None or extra is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    job = session.get(Job, int((extra.scanID or "scan-0").removeprefix("scan-")))
    project = session.get(Project, job.project_id) if job else None
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    path = (run_folder(project, job.id) / media.filePath).resolve()
    root = Path(project.output_folder).expanduser().resolve()
    if not path.is_relative_to(root):
        # Only reachable through a tampered database or a hostile package, but
        # a media endpoint that will read any path is not one to ship.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Media outside project")
    if not path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"{kind.capitalize()} file is missing on disk"
        )
    return path


@router.get("/{kind}/{event_id}")
def get_media(
    kind: str, event_id: str, session: Session = Depends(get_session)
) -> FileResponse:
    if kind not in MEDIA_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown media kind")
    path = resolve_media(session, event_id, kind)
    # FileResponse handles Range requests, which is what lets the review
    # player seek within a clip instead of re-downloading it.
    return FileResponse(path, filename=path.name)
