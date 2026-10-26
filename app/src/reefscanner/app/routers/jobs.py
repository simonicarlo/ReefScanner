"""Jobs: starting, watching and stopping engine runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..deps import get_runner, get_session
from ..jobs import JobRunner
from ..models import (
    JOB_CANCELLED,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    TERMINAL_JOB_STATUSES,
    Job,
    Project,
)
from ..schemas import JobRead

router = APIRouter(prefix="/api", tags=["jobs"])


def _read(job: Job) -> JobRead:
    return JobRead(**job.model_dump())


@router.post(
    "/projects/{project_id}/jobs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def start_job(
    project_id: int,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
) -> JobRead:
    """Queue a run for this project.

    A new run always scans every video, so its package is complete on its
    own. Refuses if one is already in flight: on a laptop two runs just make
    each other slower.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    active = session.exec(
        select(Job)
        .where(Job.project_id == project_id)
        .where(Job.status.in_((JOB_PENDING, JOB_RUNNING)))
    ).first()
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Job {active.id} is already running for this project",
        )

    job = Job(project_id=project_id, status=JOB_PENDING, message="Queued")
    session.add(job)
    session.commit()
    session.refresh(job)

    runner.start(job.id)
    return _read(job)


@router.post("/jobs/{job_id}/resume", response_model=JobRead)
def resume_job(
    job_id: int,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
) -> JobRead:
    """Continue a cancelled or failed run where it stopped.

    The same run, in the same folder: videos it already finished are skipped,
    so its events and package stay whole. This is how a long scan survives an
    interruption without starting over.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.status not in (JOB_CANCELLED, JOB_FAILED):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Only a cancelled or failed run can resume; this one is {job.status}"
        )
    active = session.exec(
        select(Job)
        .where(Job.project_id == job.project_id)
        .where(Job.status.in_((JOB_PENDING, JOB_RUNNING)))
    ).first()
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Job {active.id} is already running for this project",
        )
    job.status = JOB_PENDING
    job.message = "Resuming…"
    job.error = None
    job.finished_at = None
    session.add(job)
    session.commit()
    session.refresh(job)
    runner.start(job.id)
    return _read(job)


@router.get("/projects/{project_id}/jobs", response_model=list[JobRead])
def list_jobs(
    project_id: int, session: Session = Depends(get_session)
) -> list[JobRead]:
    jobs = session.exec(
        select(Job).where(Job.project_id == project_id).order_by(Job.id.desc())
    ).all()
    return [_read(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: int, session: Session = Depends(get_session)) -> JobRead:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _read(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: int,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
) -> JobRead:
    """Ask a job to stop between frames.

    Returns immediately; the worker sets the final ``cancelled`` status once it
    unwinds, so the UI should keep watching rather than assume it's stopped.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.status in TERMINAL_JOB_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Job is already {job.status}"
        )
    runner.cancel(job_id)
    job.message = "Cancelling…"
    session.add(job)
    session.commit()
    session.refresh(job)
    return _read(job)
