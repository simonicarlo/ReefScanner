"""Projects: a footage folder plus the config used to analyse it."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, func, select

from ...engine.config import ReefScannerConfig
from ..deps import get_session
from ..models import Job, Project
from ..schemas import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _read(session: Session, project: Project) -> ProjectRead:
    count = session.exec(
        select(func.count()).select_from(Job).where(Job.project_id == project.id)
    ).one()
    return ProjectRead(
        id=project.id,
        name=project.name,
        input_folder=project.input_folder,
        output_folder=project.output_folder,
        config=project.config or {},
        created_at=project.created_at,
        job_count=count,
    )


def _get_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.get("/defaults", response_model=dict)
def config_defaults() -> dict:
    """The engine's default config — what the UI's config editor starts from.

    Served rather than hard-coded in the frontend so the two can't drift when
    a tunable is added or a default changes.
    """
    defaults = ReefScannerConfig().to_dict()
    defaults.pop("input_folder", None)
    defaults.pop("output_folder", None)
    return defaults


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectRead]:
    projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    return [_read(session, p) for p in projects]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, session: Session = Depends(get_session)
) -> ProjectRead:
    input_folder = str(Path(payload.input_folder).expanduser())
    if not Path(input_folder).is_dir():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Input folder does not exist: {input_folder}",
        )
    project = Project(
        name=payload.name,
        input_folder=input_folder,
        output_folder=str(Path(payload.output_folder).expanduser()),
        config=payload.config,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read(session, project)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int, session: Session = Depends(get_session)
) -> ProjectRead:
    return _read(session, _get_or_404(session, project_id))


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: Session = Depends(get_session),
) -> ProjectRead:
    project = _get_or_404(session, project_id)
    data = payload.model_dump(exclude_unset=True)
    if "input_folder" in data and data["input_folder"]:
        folder = str(Path(data["input_folder"]).expanduser())
        if not Path(folder).is_dir():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Input folder does not exist: {folder}"
            )
        data["input_folder"] = folder
    if "output_folder" in data and data["output_folder"]:
        data["output_folder"] = str(Path(data["output_folder"]).expanduser())
    for key, value in data.items():
        setattr(project, key, value)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read(session, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> None:
    """Delete a project and its jobs, events and labels.

    Only database rows: the clips and thumbnails on disk are left alone,
    because deleting a project shouldn't silently destroy footage-derived
    files the user may have referenced elsewhere.
    """
    project = _get_or_404(session, project_id)
    session.delete(project)
    session.commit()
