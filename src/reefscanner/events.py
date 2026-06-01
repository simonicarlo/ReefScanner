"""Candidate model + Step 5 event aggregation (SPEC §3 Step 5).

A ``Candidate`` is a single per-frame hit, produced by EITHER the motion gate
(v1) or the frame-scanning detector (v2). Aggregation merges candidates into
events by time gap (merge if gap < merge_gap_seconds), drops events shorter than
min_event_seconds, and computes per-event summaries.

v1/v2 both aggregate by time gap only, not spatial separation (SPEC §3 note):
two animals at once — or one leaving as another enters — merge into one event.
Accepted for triage.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional, Sequence


@dataclass
class Candidate:
    """One per-frame hit, in ORIGINAL-resolution coordinates.

    Motion produces candidates with ``motion_score`` set (class/confidence None);
    the detector produces one candidate per detection with ``class_name`` +
    ``ml_confidence`` set (motion_score None). ``score`` is the unified ranking
    value used to pick an event's peak frame (blob area or detection confidence).
    """

    sampled_index: int
    source_frame: int
    timestamp: float
    bbox: tuple[int, int, int, int]
    score: float
    class_name: Optional[str] = None
    ml_confidence: Optional[float] = None
    motion_score: Optional[float] = None


# Back-compat alias: v1 callers/tests refer to MotionCandidate.
MotionCandidate = Candidate


@dataclass
class Event:
    """A merged run of candidates — one clip is emitted per event."""

    event_id: str
    source_video: str
    start_seconds: float
    end_seconds: float
    #: Candidate timestamp with the peak score (used for the thumbnail).
    peak_timestamp: float
    #: Peak ranking score (motion area in motion-mode, confidence in detector-mode).
    peak_score: float
    #: bbox at the peak frame, original-resolution (x, y, w, h).
    peak_bbox: tuple[int, int, int, int]
    peak_motion_score: Optional[float]
    peak_ml_confidence: Optional[float]
    #: Model class of the peak candidate (None in motion-only mode).
    peak_class: Optional[str]
    #: All distinct model classes seen in the event (empty in motion-only mode).
    classes: tuple[str, ...]
    n_candidates: int

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def aggregate_events(
    candidates: Sequence[Candidate],
    cfg,
    video_stem: str,
    source_video: str,
) -> list[Event]:
    """Merge candidates (ordered by time) into events.

    Candidates already carry their own ``class_name``/``ml_confidence`` (set by
    the detector) or ``motion_score`` (set by the motion gate), so aggregation
    is mode-agnostic.
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
        members = [candidates[i] for i in group]
        start = members[0].timestamp
        end = members[-1].timestamp
        if (end - start) < cfg.min_event_seconds:
            continue

        # Peak by unified score; ties resolved by earliest candidate.
        peak = max(members, key=lambda c: c.score)

        motion_scores = [c.motion_score for c in members if c.motion_score is not None]
        confidences = [c.ml_confidence for c in members if c.ml_confidence is not None]
        classes = tuple(sorted({c.class_name for c in members if c.class_name}))

        seq += 1
        events.append(
            Event(
                # event_id is unique across the whole batch (SPEC §3 Step 6).
                event_id=f"{video_stem}_{seq:03d}",
                source_video=source_video,
                start_seconds=start,
                end_seconds=end,
                peak_timestamp=peak.timestamp,
                peak_score=peak.score,
                peak_bbox=peak.bbox,
                peak_motion_score=max(motion_scores) if motion_scores else None,
                peak_ml_confidence=max(confidences) if confidences else None,
                peak_class=peak.class_name,
                classes=classes,
                n_candidates=len(members),
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
