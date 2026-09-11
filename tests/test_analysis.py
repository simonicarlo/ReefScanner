"""Threshold sweep logic — pure, so no database or video is involved."""

from __future__ import annotations

from reefscanner.app.analysis import analyse_thresholds


def test_recommends_highest_threshold_that_keeps_every_confirmed():
    """The rule: never lose a real animal to save review time."""
    result = analyse_thresholds(
        [(0.9, "TP"), (0.5, "TP"), (0.32, "TP"), (0.25, "FP"), (0.21, "FP")],
        scan_threshold=0.2,
        min_labeled=1,
    )
    assert result.recommended == 0.32
    assert result.confirmed == 3
    assert result.rejected == 2


def test_sweep_points_are_the_observed_confidences():
    """Only the values where the answer changes — no arbitrary bins."""
    result = analyse_thresholds(
        [(0.9, "TP"), (0.4, "FP")], scan_threshold=0.2, min_labeled=1
    )
    assert [p.threshold for p in result.points] == [0.4, 0.9]


def test_point_counts_and_precision():
    result = analyse_thresholds(
        [(0.8, "TP"), (0.6, "FP"), (0.4, "TP")], scan_threshold=0.2, min_labeled=1
    )
    at_lowest = result.points[0]
    assert at_lowest.threshold == 0.4
    assert at_lowest.kept == 3
    assert at_lowest.confirmed_kept == 2
    assert at_lowest.rejected_kept == 1
    assert at_lowest.confirmed_lost == 0
    assert round(at_lowest.precision, 3) == 0.667

    at_highest = result.points[-1]
    assert at_highest.threshold == 0.8
    assert at_highest.kept == 1
    assert at_highest.confirmed_lost == 1
    assert at_highest.precision == 1.0


def test_unsure_is_neither_confirmed_nor_rejected():
    """A verdict a human couldn't reach is not evidence either way."""
    result = analyse_thresholds(
        [(0.9, "TP"), (0.5, "unsure"), (0.3, "FP")],
        scan_threshold=0.2,
        min_labeled=1,
    )
    assert result.undecided == 1
    assert result.confirmed == 1
    assert result.rejected == 1
    # 0.5 must not appear as a sweep point; it carries no evidence.
    assert [p.threshold for p in result.points] == [0.3, 0.9]


def test_no_confirmed_events_gives_no_recommendation():
    """Otherwise the rule is vacuous and 'recommends' discarding everything."""
    result = analyse_thresholds(
        [(0.9, "FP"), (0.4, "FP")], scan_threshold=0.2, min_labeled=1
    )
    assert result.recommended is None
    assert "No confirmed animals" in result.recommendation


def test_events_without_confidence_are_counted_not_swept():
    """Motion-era events have no confidence and can't be in a confidence sweep."""
    result = analyse_thresholds(
        [(None, "TP"), (None, "FP"), (0.7, "TP")],
        scan_threshold=0.2,
        min_labeled=1,
    )
    assert result.unscored == 2
    assert result.confirmed == 1
    assert [p.threshold for p in result.points] == [0.7]


def test_all_unscored_gives_no_recommendation():
    result = analyse_thresholds([(None, "TP"), (None, "FP")], min_labeled=1)
    assert result.recommended is None
    assert "no confidence" in result.recommendation.lower()


def test_no_labels_at_all():
    result = analyse_thresholds([])
    assert result.labeled == 0
    assert result.points == []
    assert result.recommended is None
    assert result.reliable is False


def test_reliability_threshold():
    """Few labels still compute, but must not masquerade as evidence."""
    sparse = analyse_thresholds([(0.9, "TP"), (0.3, "FP")], min_labeled=5)
    assert sparse.reliable is False

    plenty = analyse_thresholds(
        [(0.9, "TP"), (0.8, "TP"), (0.7, "TP"), (0.6, "FP"), (0.3, "FP")],
        min_labeled=5,
    )
    assert plenty.reliable is True
