"""WebSocket endpoint for live job progress."""

from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])


@router.websocket("/ws/jobs")
async def job_progress(websocket: WebSocket) -> None:
    """Stream progress for every job in this app.

    One socket for all jobs rather than one per job: a desktop app runs a
    handful of jobs and the client filters by ``job_id``. On connect we replay
    the last known state of each job so a page refresh mid-run shows a filled
    progress bar immediately.
    """
    hub = websocket.app.state.hub
    await hub.connect(websocket)
    try:
        for payload in hub.snapshot():
            await websocket.send_json(payload)
        while True:
            # We never expect client messages; this receive is how we notice
            # the socket closing.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
