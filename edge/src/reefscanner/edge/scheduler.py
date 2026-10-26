"""Which frames the detector sees.

While nothing is in view the detector runs at the idle rate (2 fps by
default), which keeps power and heat down. A detection starts a burst at the
burst rate (every frame by default) that lasts until ``burst_seconds`` have
passed without one, so an animal in view is followed closely and the clip's
event times are tight. Then it drops back to idle.

Rates are frame strides, as in the laptop scan's sampling, so they hold
exactly at any source frame rate. Idle frames stay on a fixed grid
(``index % stride == 0``) through bursts, as the laptop scan's samples do:
with an idle rate that is a multiple of the scan's, the agent detects on every
frame the scan would, and more. The scheduler counts in stream time, and
it is the hook for the later light control (brighten on a burst).
"""

from __future__ import annotations

import threading


class Scheduler:
    def __init__(
        self,
        fps: float,
        *,
        idle_fps: float = 2.0,
        burst_fps: float | None = None,
        burst_seconds: float = 5.0,
    ) -> None:
        self.idle_stride = max(1, round(fps / idle_fps))
        self.burst_stride = 1 if burst_fps is None else max(1, round(fps / burst_fps))
        self.burst_seconds = burst_seconds
        self._last_taken: int | None = None
        self._last_hit: float | None = None
        # wants() runs on the capture thread, detected() on the detector's.
        self._lock = threading.Lock()

    def bursting(self, seconds: float) -> bool:
        with self._lock:
            return self._bursting(seconds)

    def _bursting(self, seconds: float) -> bool:
        return self._last_hit is not None and seconds - self._last_hit <= self.burst_seconds

    def wants(self, index: int, seconds: float) -> bool:
        """Whether frame ``index`` should go to the detector. Call ``taken``
        when it does."""
        with self._lock:
            if index % self.idle_stride == 0:
                return True
            if not self._bursting(seconds):
                return False
            return self._last_taken is None or index - self._last_taken >= self.burst_stride

    def taken(self, index: int) -> None:
        with self._lock:
            self._last_taken = index

    def detected(self, seconds: float) -> None:
        """A frame at ``seconds`` had a detection: burst from there."""
        with self._lock:
            if self._last_hit is None or seconds > self._last_hit:
                self._last_hit = seconds
