"""Fan-out of job progress to WebSocket clients.

The job runner is a plain thread with no access to the event loop, so it can't
await a send. It calls ``publish`` synchronously; that hands the payload to the
loop with ``call_soon_threadsafe`` and the loop does the actual sending. This is
the one place the threaded and async halves of the app meet, so the threading
rules are worth stating: ``publish`` may be called from any thread, everything
else is loop-only.

The last payload per job is retained so a client connecting mid-run gets the
current state immediately instead of an empty panel until the next tick.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("reefscanner.app.progress")


class ProgressHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[WebSocket] = set()
        self._latest: dict[int, dict[str, Any]] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called at startup, from the loop's own thread."""
        self._loop = loop

    def latest(self, job_id: int) -> dict[str, Any] | None:
        return self._latest.get(job_id)

    def snapshot(self) -> list[dict[str, Any]]:
        """Last known state of every job, for replay to a new client."""
        return list(self._latest.values())

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    def publish(self, job_id: int, payload: dict[str, Any]) -> None:
        """Thread-safe entry point used by the job runner."""
        self._latest[job_id] = payload
        loop = self._loop
        if loop is None or not self._clients:
            return
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._send(payload)))
        except RuntimeError:
            # Loop already closed — the app is shutting down mid-job.
            logger.debug("dropped progress for job %s: loop closed", job_id)

    async def _send(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for client in list(self._clients):
            try:
                await client.send_json(payload)
            except Exception:
                # A client that vanished mid-send: drop it rather than let one
                # dead socket stall progress for everyone.
                dead.append(client)
        for client in dead:
            self._clients.discard(client)
