"""Projects: a folder of footage from one place, its deployment, and its config."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, func, select

from reefscanner.core.camtrap import Deployment, PackageError
from reefscanner.core.config import ReefScannerConfig
from .. import imports, metadata
from ..deps import get_runner, get_session
from ..jobs import JobRunner
from ..models import JOB_PENDING, Job, Project
from .events import run_summary
from ..schemas import (
    DeploymentRead,
    ProjectCreate,
    ProjectImport,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _read(session: Session, project: Project) -> ProjectRead:
    count = session.exec(
        select(func.count()).select_from(Job).where(Job.project_id == project.id)
    ).one()
    latest = session.exec(
        select(Job)
        .where(Job.project_id == project.id, Job.events_found > 0)
        .order_by(Job.id.desc())
        .limit(1)
    ).first()
    return ProjectRead(
        id=project.id,
        name=project.name,
        input_folder=project.input_folder,
        output_folder=project.output_folder,
        config=project.config or {},
        created_at=project.created_at,
        job_count=count,
        latest_run=run_summary(session, latest) if latest else None,
        package_metadata=metadata.project_metadata(session, project),
        deployment=_deployment_read(session.get(Deployment, project.deployment_id)),
    )


def _deployment_read(d: Deployment) -> DeploymentRead:
    return DeploymentRead(
        deployment_id=d.deploymentID,
        latitude=d.latitude,
        longitude=d.longitude,
        location_name=d.locationName,
        camera_depth=d.cameraDepth,
        bait_use=d.baitUse,
        comments=d.deploymentComments,
        start=d.deploymentStart,
        end=d.deploymentEnd,
        timestamp_issues=bool(d.timestampIssues),
    )


def _deployment_id(name: str) -> str:
    """Readable and unique: the project name, plus a short random suffix."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "deployment"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


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
    d = payload.deployment
    deployment = Deployment(
        deploymentID=_deployment_id(payload.name),
        latitude=d.latitude,
        longitude=d.longitude,
        locationName=d.location_name or payload.name,
        cameraDepth=d.camera_depth,
        baitUse=d.bait_use,
        deploymentComments=d.comments,
    )
    session.add(deployment)
    session.flush()  # the project's foreign key needs the deployment first
    project = Project(
        name=payload.name,
        deployment_id=deployment.deploymentID,
        input_folder=input_folder,
        output_folder=str(Path(payload.output_folder).expanduser()),
        config=payload.config,
        package_metadata=metadata.stored(
            payload.package_metadata or metadata.default_metadata(session, payload.name)
        ),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read(session, project)


@router.post("/import", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def import_package(
    payload: ProjectImport,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
) -> ProjectRead:
    """Import a Camtrap DP package folder as a new project.

    Checked here so the person sees every problem at once; the copy and the
    rows then happen in an import run on the job runner, with progress.
    """
    try:
        checked = imports.check_package(payload.package_folder)
    except PackageError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "This package can't be imported", "problems": exc.problems[:100]},
        ) from None
    (incoming,) = checked.package.deployments
    if session.get(Deployment, incoming.deploymentID) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Deployment {incoming.deploymentID} is already in the app",
        )

    session.add(Deployment.model_validate(incoming.model_dump()))
    session.flush()  # the project's foreign key needs the deployment first
    project = Project(
        name=payload.name or incoming.locationName or incoming.deploymentID,
        deployment_id=incoming.deploymentID,
        # A rescan of an imported project reruns the laptop scan on its clips.
        input_folder=str(checked.folder),
        output_folder=str(Path(payload.output_folder).expanduser()),
        config=checked.config,
        package_metadata=checked.metadata,
    )
    session.add(project)
    session.flush()
    job = Job(
        project_id=project.id, status=JOB_PENDING, message="Queued",
        source=str(checked.folder),
    )
    session.add(job)
    session.commit()
    runner.start(job.id)
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
    if data.get("package_metadata") is not None:
        data["package_metadata"] = metadata.stored(payload.package_metadata)
    else:
        data.pop("package_metadata", None)  # it can be replaced, not removed
    for key, value in data.items():
        setattr(project, key, value)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read(session, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> None:
    """Delete a project, its runs, and its deployment with every observation.

    Only database rows: the clips, frames and packages on disk are left alone,
    because deleting a project shouldn't silently destroy files the user may
    have copied or referenced elsewhere.
    """
    project = _get_or_404(session, project_id)
    deployment = session.get(Deployment, project.deployment_id)
    session.delete(project)
    session.flush()
    # Media and observations go with it (ON DELETE CASCADE).
    session.delete(deployment)
    session.commit()
