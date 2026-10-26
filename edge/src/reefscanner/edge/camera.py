"""Camera adapter: one interface over every frame source.

A source yields full-quality frames numbered from 0, at a constant frame rate,
so a frame's stream time is ``index / fps``. The ring buffer, the scheduler
and the event times all count in that one clock. A source also says where in
the real world a stream time falls (``locate``), which is how a replayed
folder of camera files gets the same file names, offsets and timestamps as a
laptop scan of the same files.

Phase 0 has two sources: ``FileReplay`` (recorded footage, as the simulator)
and ``Webcam`` (any OpenCV device). Real cameras come once one is chosen; in
phase 1 a native pipeline will supply the frames and the low-res copy.
"""

from __future__ import annotations

import datetime as _dt
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

import cv2
import numpy as np

from reefscanner.core.camtrap.build import file_start
from reefscanner.core.videoio import VideoInfo, probe_video

logger = logging.getLogger("reefscanner.edge")


@dataclass
class Frame:
    #: Frame number in the stream, from 0.
    index: int
    #: Stream time: ``index / fps``.
    seconds: float
    #: Full-quality BGR image.
    image: np.ndarray


@dataclass
class Place:
    """Where a stream time is in the footage it came from."""

    #: The file (or stream) name observations refer to.
    name: str
    #: Stream time of that file's first frame.
    offset_seconds: float
    #: When that file's first frame happened.
    start: _dt.datetime
    #: True when ``start`` was guessed rather than recorded.
    guessed: bool = False


class Source(Protocol):
    fps: float
    width: int
    height: int
    #: True when the source runs at its own pace and drops what isn't taken in
    #: time (a camera, or a replay at real-time speed).
    realtime: bool

    def frames(self) -> Iterator[Frame]: ...

    def locate(self, seconds: float) -> Place: ...

    def stop(self) -> None: ...


class FileReplay:
    """Recorded files as one continuous stream.

    The files are a deployment's chapters, played back to back in the order
    given. They must share a frame rate and size, as one camera's do.
    ``speed`` 1 plays at real time, 2 at twice that; 0 hands frames over as
    fast as the agent takes them (lockstep, deterministic).
    """

    def __init__(
        self,
        paths: list[str | Path],
        camera_timezone: str,
        camera_clock: str = "local",
        speed: float = 1.0,
    ) -> None:
        if not paths:
            raise ValueError("a replay needs at least one video file")
        if speed < 0:
            raise ValueError("speed must be 0 (lockstep) or more")
        self.infos: list[VideoInfo] = [probe_video(p) for p in paths]
        first = self.infos[0]
        for info in self.infos[1:]:
            if abs(info.fps - first.fps) > 1e-3 or (info.width, info.height) != (first.width, first.height):
                raise ValueError(
                    f"{info.path.name} is {info.width}x{info.height} at {info.fps:g} fps, "
                    f"but {first.path.name} is {first.width}x{first.height} at {first.fps:g}: "
                    "a replay plays one camera's files"
                )
        if first.fps <= 0:
            raise ValueError(f"{first.path.name}: frame rate unknown")
        self.fps, self.width, self.height = first.fps, first.width, first.height
        self.speed = speed
        self.realtime = speed > 0
        self._zone, self._clock = camera_timezone, camera_clock
        self._stop = threading.Event()
        # Stream offsets come from the frames actually decoded, not the
        # container's frame count, which can be off by a few.
        self._offsets: list[float] = []

    def frames(self) -> Iterator[Frame]:
        index = 0
        began = time.monotonic()
        for info in self.infos:
            self._offsets.append(index / self.fps)
            cap = cv2.VideoCapture(str(info.path))
            if not cap.isOpened():
                raise RuntimeError(f"could not open {info.path}")
            try:
                while not self._stop.is_set():
                    ok, image = cap.read()
                    if not ok or image is None:
                        break
                    seconds = index / self.fps
                    if self.realtime:
                        delay = began + seconds / self.speed - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
                    yield Frame(index=index, seconds=seconds, image=image)
                    index += 1
            finally:
                cap.release()
            if self._stop.is_set():
                return

    def locate(self, seconds: float) -> Place:
        """The file a stream time falls in. Times before a file starts belong
        to the previous one, so an event is filed under the file it began in."""
        i = max(0, sum(1 for off in self._offsets if off <= seconds) - 1)
        info = self.infos[i]
        offset = self._offsets[i] if i < len(self._offsets) else 0.0
        start, guessed = file_start(info, self._zone, self._clock)
        return Place(name=info.path.name, offset_seconds=offset, start=start, guessed=guessed)

    def stop(self) -> None:
        self._stop.set()


class Webcam:
    """An OpenCV capture device (USB webcam, or a GoPro in webcam mode).

    Frame times assume the device's nominal frame rate. Fine for phase 0;
    the native pipeline in phase 1 takes real timestamps from the camera.
    """

    realtime = True

    def __init__(
        self,
        device: int | str = 0,
        camera_timezone: str = "UTC",
        fps: float | None = None,
        name: str | None = None,
    ) -> None:
        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            self._cap.release()
            raise RuntimeError(f"could not open camera {device!r}")
        reported = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.fps = fps or (reported if reported > 0 else 30.0)
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        from zoneinfo import ZoneInfo

        # The rig's system clock is UTC, synced before the drop; times are
        # given in the deployment's zone.
        self._start = _dt.datetime.now(_dt.timezone.utc).astimezone(ZoneInfo(camera_timezone))
        self._name = name or f"live-{self._start:%Y%m%dT%H%M%S}"
        self._stop = threading.Event()

    def frames(self) -> Iterator[Frame]:
        index = 0
        try:
            while not self._stop.is_set():
                ok, image = self._cap.read()
                if not ok or image is None:
                    logger.warning("camera stopped delivering frames")
                    return
                yield Frame(index=index, seconds=index / self.fps, image=image)
                index += 1
        finally:
            self._cap.release()

    def locate(self, seconds: float) -> Place:
        return Place(name=self._name, offset_seconds=0.0, start=self._start)

    def stop(self) -> None:
        self._stop.set()


def low_res(image: np.ndarray, width: int) -> tuple[np.ndarray, float]:
    """The detection copy of a frame and the factor back to full size.

    Width 0, or a frame already that narrow, passes the frame through.
    """
    h, w = image.shape[:2]
    if width <= 0 or w <= width:
        return image, 1.0
    scale = w / width
    small = cv2.resize(image, (width, round(h / scale)), interpolation=cv2.INTER_AREA)
    return small, scale
