"""In-process background job runner.

Deliberately not Celery/RQ/arq. This is a single-user desktop app: an external
broker would be another thing to install and another process to keep alive, for
a queue that is almost always one job deep. One worker thread per job, a
registry of the live ones, and a lock is the whole design.

The engine work is blocking and CPU-bound (OpenCV, and optionally torch), so it
runs on a real thread rather than in the event loop. It never touches the
request session; each callback opens its own short-lived one.

Progress is written on a time throttle, not on every frame: the per-frame hook
fires several times a second on a fast video, and a SQLite write plus a
WebSocket broadcast each time would cost more than the analysis.
"""

from __future__ import annotations

import datetime as _dt
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from sqlmodel import func, select

from reefscanner.core.camtrap import Deployment, Observation, ObservationExtra, PackageError
from reefscanner.core.camtrap.build import ScanContext, rows_for_video
from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.detectors import describe_model
from reefscanner.core.pipeline import process_folder
from . import imports
from .db import Database
from .models import (
    JOB_CANCELLED,
    JOB_DONE,
    JOB_FAILED,
    JOB_RUNNING,
    Job,
    Project,
    run_folder,
    scan_id,
)

logger = logging.getLogger("reefscanner.app.jobs")

#: Minimum seconds between progress writes. Fast enough to feel live, slow
#: enough that the DB isn't the bottleneck.
PROGRESS_INTERVAL_S = 0.5


def config_for(project: Project) -> ReefScannerConfig:
    """Build the engine config for a project run.

    The project's folders always win over anything stored in the config blob,
    so a project can't be edited into analysing someone else's directory.
    """
    data = dict(project.config or {})
    data["input_folder"] = project.input_folder
    data["output_folder"] = project.output_folder
    return ReefScannerConfig.from_dict(data)


def run_config(project: Project, job_id: int) -> ReefScannerConfig:
    """The project's config with everything this run writes in its own folder.

    Each run keeps its clips, frames and manifest in ``scan-<id>/``, so a
    rescan never overwrites an earlier run's files and the folder is a
    self-contained Camtrap DP package. The manifest is per run on purpose: a
    shared one would let a new run skip videos an earlier run finished, and
    its package would silently lack them. Resuming the *same* run is what
    skips finished videos.
    """
    folder = scan_id(job_id)
    data = config_for(project).to_dict()
    for key in (
        "clips_dirname", "thumbnails_dirname", "frames_dirname", "csv_name",
        "manifest_name",
    ):
        data[key] = f"{folder}/{data[key]}"
    return ReefScannerConfig.from_dict(data)


def scan_context(project: Project, cfg: ReefScannerConfig, job_id: int) -> ScanContext:
    """What the Camtrap mapping needs to know about this run."""
    model_name, model_version = describe_model(cfg)
    folder = scan_id(job_id)
    return ScanContext(
        deployment_id=project.deployment_id,
        scan_id=folder,
        camera_timezone=cfg.camera_timezone,
        camera_clock=cfg.camera_clock,
        # Relative to the run folder, which is the package root.
        clips_dir=cfg.clips_dirname.removeprefix(f"{folder}/"),
        frames_dir=cfg.frames_dirname.removeprefix(f"{folder}/"),
        frame_ext=cfg.thumbnail_ext,
        pad_seconds=cfg.pad_seconds,
        model_name=model_name,
        model_version=model_version,
        detector_backend=cfg.detector_backend,
        detector_config={
            k: v for k, v in cfg.to_dict().items()
            if k not in ("input_folder", "output_folder")
        },
    )


class JobRunner:
    """Owns the worker threads. One instance per app, held on ``app.state``."""

    def __init__(
        self,
        db: Database,
        on_update: Callable[[int, dict[str, Any]], None] | None = None,
    ) -> None:
        self.db = db
        #: Called with (job_id, payload) whenever a job's progress changes.
        #: The WebSocket router hangs off this; None means nobody is listening.
        self.on_update = on_update
        self._lock = threading.Lock()
        self._threads: dict[int, threading.Thread] = {}
        self._cancels: dict[int, threading.Event] = {}

    # -- lifecycle ---------------------------------------------------------
    def start(self, job_id: int) -> None:
        """Launch ``job_id`` on a worker thread. Idempotent per job id."""
        with self._lock:
            if job_id in self._threads and self._threads[job_id].is_alive():
                return
            cancel = threading.Event()
            self._cancels[job_id] = cancel
            thread = threading.Thread(
                target=self._run, args=(job_id, cancel),
                name=f"reefscanner-job-{job_id}", daemon=True,
            )
            self._threads[job_id] = thread
        thread.start()

    def cancel(self, job_id: int) -> bool:
        """Ask a running job to stop. Returns False if it isn't running."""
        with self._lock:
            cancel = self._cancels.get(job_id)
        if cancel is None:
            return False
        cancel.set()
        return True

    def is_running(self, job_id: int) -> bool:
        with self._lock:
            thread = self._threads.get(job_id)
        return thread is not None and thread.is_alive()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Signal every running job and wait briefly for the threads to exit."""
        with self._lock:
            cancels = list(self._cancels.values())
            threads = list(self._threads.values())
        for cancel in cancels:
            cancel.set()
        for thread in threads:
            thread.join(timeout=timeout)

    # -- the worker --------------------------------------------------------
    def _publish(self, job_id: int, payload: dict[str, Any]) -> None:
        if self.on_update is None:
            return
        try:
            self.on_update(job_id, payload)
        except Exception:  # a broken listener must never kill the job
            logger.exception("progress listener failed for job %s", job_id)

    def _patch(self, job_id: int, **fields: Any) -> dict[str, Any]:
        """Write fields onto the job row and broadcast the new state."""
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                return {}
            for key, value in fields.items():
                setattr(job, key, value)
            session.add(job)
            session.commit()
            session.refresh(job)
            payload = {
                "job_id": job.id,
                "status": job.status,
                "progress": job.progress,
                "message": job.message,
                "videos_total": job.videos_total,
                "videos_done": job.videos_done,
                "events_found": job.events_found,
                "error": job.error,
            }
        self._publish(job_id, payload)
        return payload

    def _run(self, job_id: int, cancel: threading.Event) -> None:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                logger.warning("job %s vanished before it started", job_id)
                return
            project = session.get(Project, job.project_id)
            if project is None:
                job.status = JOB_FAILED
                job.error = "project no longer exists"
                job.finished_at = _dt.datetime.now(_dt.timezone.utc)
                session.add(job)
                session.commit()
                return
            # An import run copies a package instead of scanning footage.
            source = job.source
            if source is not None:
                folder = run_folder(project, job_id)
                deployment_id = project.deployment_id
            else:
                cfg = run_config(project, job_id)

        if source is not None:
            self._import(job_id, source, folder, deployment_id, cancel)
            return

        self._patch(
            job_id,
            status=JOB_RUNNING,
            message="Starting…",
            started_at=_dt.datetime.now(_dt.timezone.utc),
            error=None,
        )

        last_write = 0.0
        state = {"videos_done": 0, "videos_total": 0, "events": 0, "skipped": 0}

        def on_frame(video: Path, index: int, total: int, fraction: float) -> None:
            nonlocal last_write
            now = time.monotonic()
            if now - last_write < PROGRESS_INTERVAL_S:
                return
            last_write = now
            state["videos_total"] = total
            # Videos are the unit; the current one contributes its own fraction
            # so a single long video still shows a moving bar.
            overall = (index + fraction) / total if total else 0.0
            self._patch(
                job_id,
                progress=round(min(1.0, overall), 4),
                videos_total=total,
                videos_done=state["videos_done"],
                message=f"Analysing {video.name} ({index + 1}/{total})",
            )

        def on_video(result) -> None:
            nonlocal last_write
            state["videos_done"] += 1
            if result.skipped:
                state["skipped"] += 1
            self._record_events(job_id, result)
            # Counted from the database, so a resumed run includes the events
            # it found before it was interrupted.
            state["events"] = self._count_events(job_id)
            last_write = time.monotonic()
            total = state["videos_total"] or state["videos_done"]
            self._patch(
                job_id,
                progress=round(state["videos_done"] / total, 4) if total else 0.0,
                videos_total=total,
                videos_done=state["videos_done"],
                events_found=state["events"],
                message=f"Finished {result.video.name}",
            )

        try:
            batch = process_folder(
                cfg,
                progress=False,  # no tqdm: nobody is watching a terminal
                on_video=on_video,
                on_frame=on_frame,
                should_cancel=cancel.is_set,
            )
        except Exception as exc:
            logger.exception("job %s failed", job_id)
            self._patch(
                job_id,
                status=JOB_FAILED,
                error=str(exc),
                message="Failed",
                finished_at=_dt.datetime.now(_dt.timezone.utc),
            )
            return
        finally:
            with self._lock:
                self._cancels.pop(job_id, None)

        errors = [r.error for r in batch.results if r.error]
        skipped = batch.n_skipped
        if batch.cancelled:
            status, message = JOB_CANCELLED, "Cancelled"
        elif errors:
            # Some videos failed but others succeeded: the run finished, and
            # the per-video errors are surfaced rather than swallowed.
            status, message = JOB_DONE, f"Finished with {len(errors)} error(s)"
        elif skipped and skipped == len(batch.results):
            # Only a resume can get here: every video was done before it.
            status = JOB_DONE
            message = f"Finished — all {skipped} video(s) were already scanned in this run"
        elif skipped:
            status = JOB_DONE
            message = f"Finished ({skipped} video(s) scanned before the resume)"
        else:
            status, message = JOB_DONE, "Finished"

        # A cancelled run keeps whatever progress it reached; only a completed
        # one is honestly at 100%.
        self._patch(
            job_id,
            status=status,
            **({"progress": 1.0} if status == JOB_DONE else {}),
            message=message,
            events_found=self._count_events(job_id),
            videos_done=state["videos_done"],
            error="\n".join(errors) if errors else None,
            finished_at=_dt.datetime.now(_dt.timezone.utc),
        )

    def _import(
        self,
        job_id: int,
        source: str,
        folder: Path,
        deployment_id: str,
        cancel: threading.Event,
    ) -> None:
        """Copy a package's files into the run folder, then add its rows.

        Rows go in one transaction after every file is in place, so a failed
        or cancelled import leaves no events behind and a retry starts clean.
        """
        self._patch(
            job_id, status=JOB_RUNNING, message="Checking the package…",
            started_at=_dt.datetime.now(_dt.timezone.utc), error=None,
        )
        last_write = 0.0

        def on_file(done: int, total: int) -> None:
            nonlocal last_write
            now = time.monotonic()
            if now - last_write < PROGRESS_INTERVAL_S and done < total:
                return
            last_write = now
            self._patch(
                job_id, progress=round(0.95 * done / total, 4),
                message=f"Copying files ({done}/{total})",
            )

        def finish(status: str, message: str, **fields: Any) -> None:
            self._patch(
                job_id, status=status, message=message,
                finished_at=_dt.datetime.now(_dt.timezone.utc), **fields,
            )

        try:
            # Checked again here: the folder may have changed since the request.
            checked = imports.check_package(source)
            sources = {Path(m.sourceVideo or "") for m in checked.package.observation_extras}
            self._patch(job_id, videos_total=len(sources))
            if not imports.copy_files(checked, folder, on_file, cancel.is_set):
                finish(JOB_CANCELLED, "Cancelled")
                return
            with self.db.session() as session:
                events = imports.insert_rows(
                    session, checked, scan_id(job_id), deployment_id
                )
                session.commit()
        except PackageError as exc:
            finish(JOB_FAILED, "The package is not valid", error="\n".join(exc.problems))
            return
        except Exception:
            logger.exception("import job %s failed", job_id)
            finish(JOB_FAILED, "Failed", error="The import failed; see the app log.")
            return
        finally:
            with self._lock:
                self._cancels.pop(job_id, None)
        finish(
            JOB_DONE, f"Imported from {Path(source).name}",
            progress=1.0, videos_done=len(sources), events_found=events,
        )

    def _count_events(self, job_id: int) -> int:
        with self.db.session() as session:
            return session.exec(
                select(func.count())
                .select_from(ObservationExtra)
                .where(ObservationExtra.scanID == scan_id(job_id))
            ).one()

    def _record_events(self, job_id: int, result) -> None:
        """Store one finished video as Camtrap DP rows.

        Called after the engine has written that video's clips and frames and
        its manifest entry. Every scanned video also stretches the
        deployment's start and end, even when nothing was found in it.
        """
        if result.info is None:
            return  # skipped or unreadable: nothing new to record
        with self.db.session() as session:
            job = session.get(Job, job_id)
            project = session.get(Project, job.project_id) if job else None
            if project is None:
                return
            cfg = run_config(project, job_id)
            rows = rows_for_video(
                scan_context(project, cfg, job_id), result.info, result.events
            )

            deployment = session.get(Deployment, project.deployment_id)
            if deployment.deploymentStart is None or rows.video_start < deployment.deploymentStart:
                deployment.deploymentStart = rows.video_start.replace(microsecond=0)
            if deployment.deploymentEnd is None or rows.video_end > deployment.deploymentEnd:
                deployment.deploymentEnd = rows.video_end.replace(microsecond=0)
            if rows.timestamp_issues:
                deployment.timestampIssues = True
            session.add(deployment)

            # A video re-recorded into the same run (a retried callback) must
            # not duplicate rows.
            new = [
                o for o in rows.observations
                if session.get(Observation, o.observationID) is None
            ]
            keep = {o.observationID for o in new}
            media = {o.mediaID for o in new} | {f"{o.eventID}:clip" for o in new}
            # Parents first: there are no ORM relationships to order the inserts.
            for level in (
                [m for m in rows.media if m.mediaID in media],
                new,
                [e for e in rows.extras if e.observationID in keep],
                [d for d in rows.detections if d.observationID in keep],
            ):
                session.add_all(level)
                session.flush()
            session.commit()
