"""Step 5 — Event aggregation (SPEC §3 Step 5).

Group consecutive motion candidates into events (merge when the time gap
between candidates < merge_gap_seconds), drop events shorter than
min_event_seconds, and compute per-event summaries.

v1 aggregates by time gap only, not spatial separation (SPEC §3 note): two
animals at once — or one leaving as another enters — merge into one event.
Accepted for triage.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Optional, Sequence

from .config import ReefScannerConfig
from .motion import MotionCandidate


@dataclass
class Event:
    """A merged run of motion candidates — one clip is emitted per event."""

    event_id: str
    source_video: str
    start_seconds: float
    end_seconds: float
    #: Candidate timestamp with the peak motion score (used for the thumbnail).
    peak_timestamp: float
    peak_motion_score: float
    #: bbox at the peak frame, original-resolution (x, y, w, h).
    peak_bbox: tuple[int, int, int, int]
    peak_ml_confidence: Optional[float]
    n_candidates: int

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def aggregate_events(
    candidates: Sequence[MotionCandidate],
    cfg: ReefScannerConfig,
    video_stem: str,
    source_video: str,
    ml_confidences: Optional[Sequence[Optional[float]]] = None,
) -> list[Event]:
    """Merge candidates (ordered by time) into events.

    ``ml_confidences`` (if given) is parallel to ``candidates`` and supplies a
    stage-2 confidence per candidate; the event keeps the max.
    """
    if not candidates:
        return []

    ordered = sorted(range(len(candidates)), key=lambda i: candidates[i].timestamp)

    groups: list[list[int]] = []
    current: list[int] = [ordered[0]]
    for idx in ordered[1:]:
        gap = candidates[idx].timestamp - candidates[current[-1]].timestamp
        if gap < cfg.merge_gap_seconds:
            current.append(idx)
        else:
            groups.append(current)
            current = [idx]
    groups.append(current)

    events: list[Event] = []
    seq = 0
    for group in groups:
        start = candidates[group[0]].timestamp
        end = candidates[group[-1]].timestamp
        if (end - start) < cfg.min_event_seconds:
            continue

        # Peak by motion score; ties resolved by earliest candidate.
        peak_i = max(group, key=lambda i: candidates[i].motion_score)
        peak = candidates[peak_i]

        peak_conf: Optional[float] = None
        if ml_confidences is not None:
            confs = [
                ml_confidences[i]
                for i in group
                if ml_confidences[i] is not None
            ]
            peak_conf = max(confs) if confs else None

        seq += 1
        events.append(
            Event(
                # event_id is unique across the whole batch (SPEC §3 Step 6).
                event_id=f"{video_stem}_{seq:03d}",
                source_video=source_video,
                start_seconds=start,
                end_seconds=end,
                peak_timestamp=peak.timestamp,
                peak_motion_score=peak.motion_score,
                peak_bbox=peak.bbox,
                peak_ml_confidence=peak_conf,
                n_candidates=len(group),
            )
        )
    return events


def derive_timestamp(
    creation_time: Optional[_dt.datetime], start_seconds: float
) -> str:
    """Wall-clock ISO timestamp for an event start, or '' if unknown (SPEC §3)."""
    if creation_time is None:
        return ""
    return (creation_time + _dt.timedelta(seconds=start_seconds)).isoformat()
