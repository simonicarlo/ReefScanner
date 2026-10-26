"""Online event aggregation.

The laptop scan sees a whole video before grouping its detections into events;
the agent has to decide while the footage is still coming. It collects
candidates into an open event and closes it once ``merge_gap_seconds`` of
detected frames have passed without a hit, the point after which no later
detection could still join it. The closed group then goes through core's
``aggregate_events``, so the event (its peak, classes, minimum length) is
built exactly as the laptop scan builds it.

It also keeps the full-quality image of the best-scoring frame so far, which
becomes the event's clean peak frame and thumbnail. The footage itself is
only in the encoded buffer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.detection import Detection
from reefscanner.core.events import Candidate, Event, aggregate_events


@dataclass
class ClosedEvent:
    #: Built by core's aggregation; times are stream seconds. None when the
    #: hits were too short to count as an event: nothing to write, but its
    #: buffer hold still has to be released.
    event: Event | None
    #: Full-quality image of the peak frame.
    peak_image: np.ndarray
    #: The ring buffer hold keeping this event's footage.
    hold: int | None = None


class EventTracker:
    def __init__(self, cfg: ReefScannerConfig) -> None:
        self.cfg = cfg
        self._members: list[Candidate] = []
        self._peak_score = -1.0
        self._peak_image: np.ndarray | None = None
        self.hold: int | None = None

    @property
    def open_since(self) -> float | None:
        """Stream time of the open event's first hit, if one is open."""
        return self._members[0].timestamp if self._members else None

    def observe(
        self, index: int, seconds: float, image: np.ndarray, detections: list[Detection]
    ) -> list[ClosedEvent]:
        """Feed one detected frame, hits or not. Returns events it closed."""
        closed = self._close_if_quiet(seconds)
        if not detections:
            return closed
        for det in detections:
            self._members.append(Candidate(
                sampled_index=index,
                source_frame=index,
                timestamp=seconds,
                bbox=det.bbox,
                score=det.confidence,
                class_name=det.class_name,
                ml_confidence=det.confidence,
            ))
        best = max(d.confidence for d in detections)
        # Strictly greater: aggregation also picks the earliest of equal peaks.
        if best > self._peak_score:
            self._peak_score, self._peak_image = best, image
        return closed

    def _close_if_quiet(self, seconds: float) -> list[ClosedEvent]:
        if self._members and seconds - self._members[-1].timestamp >= self.cfg.merge_gap_seconds:
            return self.flush()
        return []

    def flush(self) -> list[ClosedEvent]:
        """Close the open event now (the stream ended, or went quiet)."""
        if not self._members:
            return []
        members, image, hold = self._members, self._peak_image, self.hold
        self._members, self._peak_score, self._peak_image, self.hold = [], -1.0, None, None
        events = aggregate_events(members, self.cfg, video_stem="event", source_video="")
        # One group by construction, or none if it was shorter than the minimum.
        return [ClosedEvent(event=events[0] if events else None, peak_image=image, hold=hold)]
