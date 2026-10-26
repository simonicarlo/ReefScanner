"""The scheduler and the online tracker: which frames get detected, and when
an event is over."""

from __future__ import annotations

import numpy as np

from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.detection import Detection
from reefscanner.edge.scheduler import Scheduler
from reefscanner.edge.tracker import EventTracker


def _run(s: Scheduler, fps: float, frames: int, hits: set[int] = frozenset()) -> list[int]:
    taken = []
    for i in range(frames):
        if s.wants(i, i / fps):
            s.taken(i)
            taken.append(i)
            if i in hits:
                s.detected(i / fps)
    return taken


def test_idle_frames_include_every_frame_the_laptop_scan_samples() -> None:
    # The laptop scan samples 1 fps on the grid index % 30 == 0; an idle rate
    # that is a multiple of it must keep every one of those frames, bursts or not.
    taken = _run(Scheduler(30, idle_fps=2, burst_seconds=1), 30, 300, hits={45})
    assert set(range(0, 300, 30)) <= set(taken)


def test_a_detection_starts_a_burst_that_ends_after_quiet() -> None:
    s = Scheduler(10, idle_fps=2, burst_seconds=1.0)
    taken = _run(s, 10, 60, hits={20})
    assert taken[:5] == [0, 5, 10, 15, 20]
    # Every frame for one second after the hit, then back to the idle grid.
    assert list(range(20, 31)) == [t for t in taken if 20 <= t <= 30]
    assert [t for t in taken if t > 30] == [35, 40, 45, 50, 55]


def test_burst_rate_can_be_limited() -> None:
    s = Scheduler(30, idle_fps=1, burst_fps=10, burst_seconds=2.0)
    taken = _run(s, 30, 60, hits={0})
    assert taken[:4] == [0, 3, 6, 9]


def _hit(conf: float = 0.9) -> list[Detection]:
    return [Detection(bbox=(10, 10, 50, 50), class_name="shark", confidence=conf)]


def test_tracker_closes_an_event_once_no_hit_could_join_it() -> None:
    t = EventTracker(ReefScannerConfig(merge_gap_seconds=3.0, min_event_seconds=1.0))
    blank = np.zeros((4, 4, 3), np.uint8)
    for s in (10.0, 11.0, 12.0):
        assert t.observe(int(s), s, blank, _hit()) == []
    assert t.observe(14, 14.0, blank, []) == []  # 2 s quiet: a hit could still join
    closed = t.observe(15, 15.0, blank, [])
    assert len(closed) == 1 and closed[0].event is not None
    assert (closed[0].event.start_seconds, closed[0].event.end_seconds) == (10.0, 12.0)
    assert t.open_since is None


def test_tracker_keeps_the_peak_frame_image() -> None:
    t = EventTracker(ReefScannerConfig())
    frames = {s: np.full((2, 2, 3), s, np.uint8) for s in (1, 2, 3)}
    for s, conf in ((1, 0.5), (2, 0.8), (3, 0.6)):
        t.observe(s, float(s), frames[s], _hit(conf))
    (closed,) = t.flush()
    assert closed.event.peak_timestamp == 2.0
    assert closed.peak_image is frames[2]


def test_hits_too_short_for_an_event_still_hand_back_their_hold() -> None:
    t = EventTracker(ReefScannerConfig(min_event_seconds=1.0))
    t.observe(1, 1.0, np.zeros((2, 2, 3), np.uint8), _hit())
    t.hold = 7
    (closed,) = t.flush()
    assert closed.event is None and closed.hold == 7
