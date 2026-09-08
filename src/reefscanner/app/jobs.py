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
from typing import Any, Callable, Optional

from sqlmodel import select

from ..engine.config import ReefScannerConfig
from ..engine.pipeline import process_folder
from .db import Database
from .models import (
    JOB_CANCELLED,
    JOB_DONE,
    JOB_FAILED,
    JOB_RUNNING,
    Event,
    Job,
    Project,
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


class JobRunner:
    """Owns the worker threads. One instance per app, held on ``app.state``."""

    def __init__(
        self,
        db: Database,
        on_update: Optional[Callable[[int, dict[str, Any]], None]] = None,
    ):
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
            cfg = config_for(project)

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
            state["events"] += len(result.events)
            if result.skipped:
                state["skipped"] += 1
            self._record_events(job_id, result)
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
            # Nothing was actually analysed. Say so plainly — a run that ends
            # in a second with no events otherwise looks like a failure.
            status = JOB_DONE
            message = (
                f"Nothing to do — all {skipped} video(s) already scanned with "
                "these settings. Change a setting to rescan."
            )
        elif skipped:
            status = JOB_DONE
            message = f"Finished ({skipped} already scanned, skipped)"
        else:
            status, message = JOB_DONE, "Finished"

        # A cancelled run keeps whatever progress it reached; only a completed
        # one is honestly at 100%.
        self._patch(
            job_id,
            status=status,
            **({"progress": 1.0} if status == JOB_DONE else {}),
            message=message,
            events_found=state["events"],
            videos_done=state["videos_done"],
            error="\n".join(errors) if errors else None,
            finished_at=_dt.datetime.now(_dt.timezone.utc),
        )

    def _record_events(self, job_id: int, result) -> None:
        """Persist one finished video's events.

        Called after the engine has already committed that video's clips, CSV
        rows and manifest entry, so a crash here loses database rows but never
        the analysis — re-running the job re-imports them from the CSV.
        """
        if not result.events:
            return
        info = result.info
        out_dir = None
        with self.db.session() as session:
            job = session.get(Job, job_id)
            project = session.get(Project, job.project_id) if job else None
            if project is not None:
                out_dir = Path(project.output_folder)
                cfg = config_for(project)

            existing = set(
                session.exec(
                    select(Event.event_id).where(Event.job_id == job_id)
                ).all()
            )

            for ev in result.events:
                if ev.event_id in existing:
                    continue
                clip = thumb = None
                if out_dir is not None:
                    suffix = Path(result.video).suffix or ".mp4"
                    clip = str(out_dir / cfg.clips_dirname / f"{ev.event_id}{suffix}")
                    thumb = str(
                        out_dir / cfg.thumbnails_dirname
                        / f"{ev.event_id}{cfg.thumbnail_ext}"
                    )
                session.add(
                    Event(
                        job_id=job_id,
                        event_id=ev.event_id,
                        source_video=ev.source_video,
                        start_seconds=ev.start_seconds,
                        end_seconds=ev.end_seconds,
                        duration_seconds=ev.duration_seconds,
                        peak_timestamp=ev.peak_timestamp,
                        peak_score=ev.peak_score,
                        peak_bbox=list(ev.peak_bbox) if ev.peak_bbox else None,
                        motion_score=ev.peak_motion_score,
                        ml_confidence=ev.peak_ml_confidence,
                        detected_class=ev.peak_class,
                        start_timestamp=_start_timestamp(info, ev.start_seconds),
                        frame_width=info.width if info else None,
                        frame_height=info.height if info else None,
                        clip_path=clip,
                        thumbnail_path=thumb,
                    )
                )
            session.commit()


def _start_timestamp(info, start_seconds: float) -> str:
    from ..engine.events import derive_timestamp

    if info is None:
        return ""
    return derive_timestamp(info.creation_time, start_seconds)
