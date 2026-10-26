"""What confidence threshold should this project use?

A scan run at confidence C emits every detection above C, and the reviewer
labels them. Raising the threshold afterwards is therefore perfectly
simulatable: the surviving events are known and so are their verdicts. No
rescan, no model, no guessing.

The one thing this can never see is what the detector missed *below* C. So the
numbers here describe recall relative to what this scan found, never absolute
recall — and the wording that says so is a correctness requirement, not copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

#: Below this many scored, labeled events, a recommendation is a guess.
DEFAULT_MIN_LABELED = 5

_CONFIRMED = "TP"
_REJECTED = "FP"


@dataclass
class ThresholdPoint:
    """What would happen if the threshold were set here."""

    threshold: float
    kept: int
    confirmed_kept: int
    rejected_kept: int
    #: Confirmed animals that would fall below the line. The expensive error.
    confirmed_lost: int
    precision: float


@dataclass
class ThresholdAnalysis:
    labeled: int = 0
    confirmed: int = 0
    rejected: int = 0
    undecided: int = 0
    #: Labeled events with no confidence at all (scanned before detector mode).
    unscored: int = 0
    reliable: bool = False
    scan_threshold: float | None = None
    recommended: float | None = None
    recommendation: str = ""
    points: list[ThresholdPoint] = field(default_factory=list)


def analyse_thresholds(
    labeled: Sequence[tuple[float | None, str]],
    scan_threshold: float | None = None,
    min_labeled: int = DEFAULT_MIN_LABELED,
) -> ThresholdAnalysis:
    """Sweep every threshold worth considering over labeled events.

    ``labeled`` is ``(ml_confidence, verdict)`` per reviewed event. Sweep points
    are the distinct observed confidences of events carrying evidence, because
    those are the only thresholds at which any count can change.
    """
    result = ThresholdAnalysis(labeled=len(labeled), scan_threshold=scan_threshold)

    scored = [(c, v) for c, v in labeled if c is not None]
    result.unscored = len(labeled) - len(scored)
    result.undecided = sum(1 for _, v in scored if v not in (_CONFIRMED, _REJECTED))

    # Only TP/FP carry evidence. 'unsure' is a human declining to call it, which
    # is not the same as either answer and must not tilt precision.
    evidence = [(c, v) for c, v in scored if v in (_CONFIRMED, _REJECTED)]
    result.confirmed = sum(1 for _, v in evidence if v == _CONFIRMED)
    result.rejected = len(evidence) - result.confirmed
    result.reliable = len(evidence) >= min_labeled

    if not evidence:
        result.recommendation = (
            "These labeled detections have no confidence scores, so there is "
            "nothing to sweep. They predate detector mode."
            if result.unscored
            else "Nothing labeled yet — review some events first."
        )
        return result

    for threshold in sorted({c for c, _ in evidence}):
        kept = [(c, v) for c, v in evidence if c >= threshold]
        confirmed_kept = sum(1 for _, v in kept if v == _CONFIRMED)
        result.points.append(
            ThresholdPoint(
                threshold=threshold,
                kept=len(kept),
                confirmed_kept=confirmed_kept,
                rejected_kept=len(kept) - confirmed_kept,
                confirmed_lost=result.confirmed - confirmed_kept,
                precision=(confirmed_kept / len(kept)) if kept else 0.0,
            )
        )

    if result.confirmed == 0:
        # Every threshold trivially loses nothing, so the rule would "recommend"
        # discarding every detection. Refuse to answer instead.
        result.recommendation = (
            "No confirmed animals yet — nothing to protect. "
            "Confirm at least one detection for a recommendation."
        )
        return result

    safe = [p for p in result.points if p.confirmed_lost == 0]
    best = max(safe, key=lambda p: p.threshold)
    result.recommended = best.threshold
    result.recommendation = (
        f"Highest threshold that keeps every confirmed animal. "
        f"At {best.threshold:.2f} you would review {best.kept} detection(s) "
        f"instead of {result.points[0].kept}, losing none."
    )
    return result
