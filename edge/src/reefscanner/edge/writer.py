"""Event writer: from a closed event to files and Camtrap DP rows.

Per event: the clip (pre-roll + event + post-roll, joined from the ring
buffer), the clean peak frame, the annotated thumbnail, and the rows, built by
core's ``rows_for_event``, the same mapping the field app's scans use. Events
are filed under the source file they started in (a replayed chapter, or the
live stream), with that file's own times, so a replay's rows line up with a
laptop scan of the same files.

It runs on its own thread because a clip can only be cut once the post-roll
has been recorded, and detection must not wait for that.

After every event the whole package is rewritten through the atomic
``write_package``, with the deployment ending now. A power cut therefore
leaves a valid package of every event written so far. The tables are small.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import logging
import queue
import threading
from collections import defaultdict
from pathlib import Path
from typing import Callable

from reefscanner.core.camtrap import Deployment, Package, write_package
from reefscanner.core.camtrap.build import ScanContext, VideoRows, rows_for_event
from reefscanner.core.clips import save_clean_frame, save_thumbnail
from reefscanner.core.detectors import describe_model
from reefscanner.core.events import Candidate, Event

from .camera import Place, Source
from .config import AgentConfig
from .ringbuffer import RingBuffer
from .tracker import ClosedEvent

logger = logging.getLogger("reefscanner.edge")

#: Provenance for the agent's observations (the sidecar's scanID).
SCAN_ID = "agent"

_STOP = object()


class EventWriter:
    def __init__(
        self,
        package_dir: str | Path,
        config: AgentConfig,
        source: Source,
        buffer: RingBuffer,
    ) -> None:
        self.dir = Path(package_dir)
        self.config = config
        self.source = source
        self.buffer = buffer
        cfg = config.detector
        model_name, model_version = describe_model(cfg)
        self.ctx = ScanContext(
            deployment_id=config.deployment.id,
            scan_id=SCAN_ID,
            camera_timezone=config.deployment.camera_timezone,
            camera_clock=config.deployment.camera_clock,
            clips_dir=cfg.clips_dirname,
            frames_dir=cfg.frames_dirname,
            frame_ext=cfg.thumbnail_ext,
            pad_seconds=config.agent.pre_roll_seconds,
            model_name=model_name,
            model_version=model_version,
            detector_backend=cfg.detector_backend,
            detector_config={
                k: v for k, v in cfg.to_dict().items()
                if k not in ("input_folder", "output_folder")
            },
        )
        self.rows = VideoRows()
        self.events: list[Event] = []
        self._seq: dict[str, int] = defaultdict(int)
        self._guessed = False
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self.error: BaseException | None = None
        #: Called with each written event, for progress reports.
        self.on_event: Callable[[Event, Place], None] | None = None

    # -- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        self.write()  # an empty but valid package from the first second
        self._thread = threading.Thread(target=self._run, name="event-writer", daemon=True)
        self._thread.start()

    def submit(self, closed: ClosedEvent) -> None:
        self._queue.put(closed)

    def finish(self) -> None:
        """Write every queued event, then the final package."""
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join()
        self.write()

    def _run(self) -> None:
        while (item := self._queue.get()) is not _STOP:
            try:
                self._write_event(item)
            except Exception as exc:  # keep the rig recording; report at the end
                logger.exception("could not write an event")
                self.error = exc
            finally:
                if item.hold is not None:
                    self.buffer.release(item.hold)

    # -- one event ----------------------------------------------------------------

    def _write_event(self, closed: ClosedEvent) -> None:
        if closed.event is None:
            return
        stream_event = closed.event
        a = self.config.agent
        end = stream_event.end_seconds + a.post_roll_seconds
        self.buffer.wait_until(end)

        place = self.source.locate(stream_event.start_seconds)
        self._seq[place.name] += 1
        event = _rebase(stream_event, place, self._seq[place.name])
        self._guessed |= place.guessed

        cfg = self.config.detector
        clip_start = self.buffer.cut(
            stream_event.start_seconds - a.pre_roll_seconds,
            end,
            self.dir / cfg.clips_dirname / f"{event.event_id}.mp4",
        )
        save_clean_frame(event, None, cfg, self.dir / cfg.frames_dirname, frame=closed.peak_image)
        save_thumbnail(event, None, cfg, self.dir / cfg.thumbnails_dirname, frame=closed.peak_image)

        self.rows.extend(rows_for_event(
            self.ctx, event,
            start=place.start,
            width=self.source.width,
            height=self.source.height,
            source_name=place.name,
            clip_suffix=".mp4",
            clip_start_seconds=clip_start - place.offset_seconds,
        ))
        self.events.append(event)
        self.write()
        logger.info(
            "event %s: %.1fs to %.1fs in %s", event.event_id,
            event.start_seconds, event.end_seconds, place.name,
        )
        if self.on_event is not None:
            self.on_event(event, place)

    # -- the package --------------------------------------------------------------

    def write(self) -> Path:
        return write_package(self.dir, self.package())

    def package(self) -> Package:
        d = self.config.deployment
        first = self.source.locate(0.0)
        now = self.buffer.now()
        last = self.source.locate(now)
        start = first.start.replace(microsecond=0)
        end = max(start, (last.start + _dt.timedelta(seconds=now - last.offset_seconds)).replace(microsecond=0))
        deployment = Deployment(
            deploymentID=d.id,
            locationName=d.location_name,
            latitude=d.latitude,
            longitude=d.longitude,
            deploymentStart=start,
            deploymentEnd=end,
            setupBy=d.setup_by,
            cameraID=d.camera_id,
            cameraModel=d.camera_model,
            cameraDepth=d.camera_depth,
            baitUse=d.bait_use,
            timestampIssues=self._guessed or first.guessed or None,
            deploymentComments=d.comments,
        )
        return Package(
            deployments=[deployment],
            media=list(self.rows.media),
            observations=list(self.rows.observations),
            observation_extras=list(self.rows.extras),
            detections=list(self.rows.detections),
            metadata={
                "title": f"{self.config.project_title} — {d.id}",
                "project": {"title": self.config.project_title},
                "contributors": self.config.contributors,
            },
        )


def _rebase(event: Event, place: Place, seq: int) -> Event:
    """The event in its source file's own times, numbered within that file."""
    off = place.offset_seconds

    def shift(c: Candidate) -> Candidate:
        return dataclasses.replace(c, timestamp=c.timestamp - off)

    return dataclasses.replace(
        event,
        event_id=f"{Path(place.name).stem}_{seq:03d}",
        source_video=place.name,
        start_seconds=event.start_seconds - off,
        end_seconds=event.end_seconds - off,
        peak_timestamp=event.peak_timestamp - off,
        members=tuple(shift(c) for c in event.members),
    )
