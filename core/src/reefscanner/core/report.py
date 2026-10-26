"""False-positive-rate reporting (SPEC §8.6, §10).

Acceptance criterion 6: report a false-positive rate on real footage — events
emitted vs. events a human confirms. This number is the go/no-go input for
whether ML (v2) earns its place. A human fills the reserved ``label`` column
(e.g. TP / FP) during triage; this reads it back.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# Label tokens (case-insensitive) counted as a confirmed true positive.
TRUE_POSITIVE_TOKENS = {"tp", "true", "true_positive", "yes", "y", "confirm", "confirmed", "1"}
FALSE_POSITIVE_TOKENS = {"fp", "false", "false_positive", "no", "n", "reject", "rejected", "0"}


@dataclass
class FpReport:
    total_events: int
    labeled: int
    true_positives: int
    false_positives: int

    @property
    def unlabeled(self) -> int:
        return self.total_events - self.labeled

    @property
    def false_positive_rate(self) -> float:
        """FP / labeled. NaN-safe: returns 0.0 when nothing is labeled yet."""
        return self.false_positives / self.labeled if self.labeled else 0.0

    def summary(self) -> str:
        if self.labeled == 0:
            return (
                f"{self.total_events} events emitted, none labeled yet. "
                "Fill the 'label' column (TP/FP) during triage, then re-run "
                "the report to get the false-positive rate (SPEC §8.6, §10)."
            )
        return (
            f"False-positive rate: {self.false_positive_rate:.1%} "
            f"({self.false_positives} FP / {self.labeled} labeled; "
            f"{self.true_positives} TP, {self.unlabeled} unlabeled, "
            f"{self.total_events} total events)."
        )


def fp_report(csv_path: str | Path) -> FpReport:
    """Compute the FP report from a (partially) human-labeled results CSV."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Results CSV not found: {path}")

    total = labeled = tp = fp = 0
    with open(path, "r", newline="") as fh:
        for row in csv.DictReader(fh):
            total += 1
            token = (row.get("label") or "").strip().lower()
            if not token:
                continue
            if token in TRUE_POSITIVE_TOKENS:
                labeled += 1
                tp += 1
            elif token in FALSE_POSITIVE_TOKENS:
                labeled += 1
                fp += 1
            # Unknown tokens are ignored (treated as not-yet-decided).
    return FpReport(total_events=total, labeled=labeled,
                    true_positives=tp, false_positives=fp)
