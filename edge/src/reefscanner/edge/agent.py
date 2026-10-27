"""The edge agent: films, detects, and keeps the clips worth reviewing.

    source ──frames──▶ ring buffer (encoded, last N s)
       │
       └─ scheduler wants it? ──▶ detector (low-res copy) ──▶ tracker
                                                              │ closed events
                                                              ▼
                                               event writer ──▶ package folder

In real time (a camera, or a replay at speed > 0) detection runs on its own
thread fed by a one-frame slot. A frame the scheduler wants while the detector
is still busy is dropped and counted, which is what the rig would do. In
lockstep (a replay at speed 0) detection runs inline, so every wanted frame is
detected and a run is deterministic.

Phase 0 runs in one process with OpenCV frames. In phase 1 capture and
encoding move into a native pipeline and a separate process, behind the same
seams.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from reefscanner.core.clips import resolve_ffmpeg
from reefscanner.core.detectors import Detector, get_detector
from reefscanner.core.detection import Detection
from reefscanner.core.events import Event

from .camera import Frame, Place, Source, low_res
from .config import AgentConfig
from .ringbuffer import RingBuffer
from .scheduler import Scheduler
from .tracker import ClosedEvent, EventTracker
from .writer import EventWriter

logger = logging.getLogger("reefscanner.edge")


@dataclass
class AgentResult:
    package_dir: Path
    events: list[Event] = field(default_factory=list)
    frames: int = 0
    #: Frames the detector ran on.
    detected: int = 0
    #: Frames the scheduler wanted but the detector was too busy for.
    dropped: int = 0
    seconds: float = 0.0
    #: Wall-clock seconds the run took.
    elapsed: float = 0.0


class Agent:
    def __init__(
        self,
        config: AgentConfig,
        source: Source,
        package_dir: str | Path,
        detector: Detector | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.package_dir = Path(package_dir)
        self.detector = detector or get_detector(config.detector)
        a = config.agent
        self.scheduler = Scheduler(
            source.fps,
            idle_fps=a.idle_fps,
            burst_fps=a.burst_fps,
            burst_seconds=a.burst_seconds,
        )
        self.tracker = EventTracker(config.detector)
        buffer_dir = Path(a.buffer_dir) if a.buffer_dir else self.package_dir / ".buffer"
        self.buffer = RingBuffer(
            buffer_dir,
            fps=source.fps,
            width=source.width,
            height=source.height,
            ffmpeg=resolve_ffmpeg(config.detector),
            keep_seconds=a.pre_roll_seconds,
            segment_seconds=a.segment_seconds,
        )
        self.writer = EventWriter(self.package_dir, config, source, self.buffer)
        self._stop = threading.Event()
        self._slot: Frame | None = None
        self._slot_ready = threading.Condition()
        self._capture_done = False
        self._detect_error: BaseException | None = None
        self.result = AgentResult(package_dir=self.package_dir)

    @property
    def on_event(self) -> Callable[[Event, Place], None] | None:
        return self.writer.on_event

    @on_event.setter
    def on_event(self, callback: Callable[[Event, Place], None] | None) -> None:
        self.writer.on_event = callback

    def stop(self) -> None:
        """Ask a running agent to finish: it closes the open event and writes it."""
        self._stop.set()
        self.source.stop()

    # -- running ------------------------------------------------------------------

    def run(self) -> AgentResult:
        began = time.monotonic()
        self.package_dir.mkdir(parents=True, exist_ok=True)
        self.buffer.start()
        self.writer.start()
        detect_thread = None
        if self.source.realtime:
            detect_thread = threading.Thread(target=self._detect_loop, name="detector", daemon=True)
            detect_thread.start()
        try:
            for frame in self.source.frames():
                self.buffer.write(frame.image)
                self.result.frames += 1
                if self.scheduler.wants(frame.index, frame.seconds):
                    if detect_thread is None:
                        self.scheduler.taken(frame.index)
                        self._detect(frame)
                    else:
                        self._offer(frame)
                if self._detect_error is not None:
                    raise RuntimeError("detection failed") from self._detect_error
                if self._stop.is_set():
                    break
        finally:
            with self._slot_ready:
                self._capture_done = True
                self._slot_ready.notify_all()
            if detect_thread is not None:
                detect_thread.join()
            for closed in self.tracker.flush():
                self.writer.submit(closed)
            self.buffer.finish()
            self.writer.finish()
            self.buffer.close()

        self.result.events = list(self.writer.events)
        self.result.seconds = self.buffer.now()
        self.result.elapsed = time.monotonic() - began
        if self.writer.error is not None:
            raise RuntimeError("an event could not be written") from self.writer.error
        return self.result

    def _offer(self, frame: Frame) -> None:
        with self._slot_ready:
            if self._slot is not None:
                # The detector hasn't got to the last one: the newer replaces it.
                self.result.dropped += 1
            self.scheduler.taken(frame.index)
            self._slot = frame
            self._slot_ready.notify()

    def _detect_loop(self) -> None:
        while True:
            with self._slot_ready:
                self._slot_ready.wait_for(lambda: self._slot is not None or self._capture_done)
                frame, self._slot = self._slot, None
            if frame is None:
                return
            try:
                self._detect(frame)
            except Exception as exc:  # surfaced on the capture thread
                logger.exception("detection failed")
                self._detect_error = exc
                return

    def _detect(self, frame: Frame) -> None:
        small, scale = low_res(frame.image, self.config.agent.detect_width)
        detections = [_scale(d, scale) for d in self.detector.detect(small)]
        self.result.detected += 1
        if detections:
            self.scheduler.detected(frame.seconds)
        for closed in self.tracker.observe(frame.index, frame.seconds, frame.image, detections):
            self.writer.submit(closed)
        if self.tracker.open_since is not None and self.tracker.hold is None:
            # Keep the new event's pre-roll until its clip is cut.
            self.tracker.hold = self.buffer.hold(
                self.tracker.open_since - self.config.agent.pre_roll_seconds
            )


def _scale(det: Detection, scale: float) -> Detection:
    if scale == 1.0:
        return det
    x, y, w, h = det.bbox
    return Detection(
        bbox=(round(x * scale), round(y * scale), round(w * scale), round(h * scale)),
        class_name=det.class_name,
        confidence=det.confidence,
    )
