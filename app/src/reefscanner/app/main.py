"""FastAPI application factory.

Everything the app needs — database, job runner, progress hub — is created here
and attached to ``app.state``, so a test can build an isolated app on a
temporary database by passing ``db_path``.

Route order matters at the bottom: the SPA catch-all is mounted last so it
can't shadow ``/api`` or ``/ws``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from reefscanner.core import __version__
from .db import Database
from .jobs import JobRunner
from .progress import ProgressHub
from .routers import analysis, events, exports, jobs, media, projects, ws

logger = logging.getLogger("reefscanner.app")

#: Where the built React app lands. Empty during backend-only development.
STATIC_DIR = Path(__file__).parent / "static"

#: Vite's dev server. Allowed so the frontend can be developed with hot reload
#: against this backend; in the packaged app the UI is same-origin and this is
#: simply unused.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app(
    db_path: Optional[str | Path] = None,
    allow_dev_origins: bool = True,
) -> FastAPI:
    database = Database(db_path)
    database.create_all()
    hub = ProgressHub()
    runner = JobRunner(database, on_update=hub.publish)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.bind_loop(asyncio.get_running_loop())
        _reconcile_orphaned_jobs(database)
        yield
        # Jobs are daemon threads, so without this an exit mid-run would leave
        # a half-written video behind with nothing marked in the manifest.
        runner.shutdown()
        database.dispose()

    app = FastAPI(
        title="ReefScanner",
        version=__version__,
        summary="Local triage of static-camera underwater video.",
        lifespan=lifespan,
    )
    app.state.db = database
    app.state.runner = runner
    app.state.hub = hub

    if allow_dev_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=DEV_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(analysis.router)
    app.include_router(projects.router)
    app.include_router(jobs.router)
    app.include_router(events.router)
    app.include_router(exports.router)
    app.include_router(media.router)
    app.include_router(ws.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__, "db": str(database.path)}

    _mount_frontend(app)
    return app


def _reconcile_orphaned_jobs(database: Database) -> None:
    """Fail jobs left 'running' by a previous process.

    Job threads don't survive a crash or a force-quit, so any job still marked
    running at startup is a lie. Marking it failed keeps the project startable
    again instead of permanently blocked by the already-running check.
    """
    from sqlmodel import select

    from .models import JOB_FAILED, JOB_PENDING, JOB_RUNNING, Job

    with database.session() as session:
        stale = session.exec(
            select(Job).where(Job.status.in_((JOB_RUNNING, JOB_PENDING)))
        ).all()
        for job in stale:
            job.status = JOB_FAILED
            job.message = "Interrupted"
            job.error = "The application exited while this job was running."
            session.add(job)
        if stale:
            logger.info("Marked %d interrupted job(s) as failed", len(stale))
            session.commit()


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React app, if it has been built into the package."""
    index = STATIC_DIR / "index.html"
    if not index.exists():
        @app.get("/", tags=["meta"])
        def no_frontend() -> dict:
            return {
                "detail": (
                    "No frontend build found. Run `npm run build` in app/frontend/ "
                    "or use the Vite dev server at http://localhost:5173."
                ),
                "api_docs": "/docs",
            }
        return

    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def spa_root() -> FileResponse:
        return FileResponse(index)

    @app.get("/{path:path}", include_in_schema=False)
    def spa_catch_all(path: str) -> FileResponse:
        """Client-side routing: unknown paths return index.html.

        Registered last, so real API routes still win. An unmatched /api path
        must 404 rather than silently return HTML, or a typo'd fetch looks like
        a JSON parse error instead of a missing route.
        """
        if path.startswith(("api/", "ws/", "docs", "openapi.json")):
            raise HTTPException(404, "Not found")
        # The path arrives percent-decoded, so `..%2f` reaches here as `../`.
        # Without the containment check this route reads any file on disk.
        root = STATIC_DIR.resolve()
        candidate = (root / path).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


# Uvicorn's `--factory` target, and what `reefscanner serve` uses.
__all__ = ["create_app"]
