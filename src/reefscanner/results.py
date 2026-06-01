"""CSV results writer (SPEC §3 Step 6, §6).

One row per event. Append-only, whole rows per event (no partial flushes) so a
mid-write disconnect can't leave a torn row. The manifest (§7) is the source of
truth for "completed"; the CSV is append-only and reconciled on restart.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from .events import Event, derive_timestamp
from .videoio import VideoInfo

# Column order is part of the contract for the downstream labeling workflow.
CSV_COLUMNS = [
    "event_id",
    "source_video",
    "start_seconds",
    "end_seconds",
    "duration_s",
    "start_timestamp",
    "motion_score",
    "ml_confidence",
    "clip_path",
    "thumbnail_path",
    # Reserved for the future labeling workflow (SPEC §9, §10) — left blank.
    "label",
    "species",
    "notes",
]


def event_to_row(
    event: Event,
    info: VideoInfo,
    clip_path: Optional[str],
    thumbnail_path: Optional[str],
) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "source_video": event.source_video,
        "start_seconds": round(event.start_seconds, 3),
        "end_seconds": round(event.end_seconds, 3),
        "duration_s": round(event.duration_seconds, 3),
        "start_timestamp": derive_timestamp(
            info.creation_time, event.start_seconds
        ),
        "motion_score": round(event.peak_motion_score, 1),
        "ml_confidence": (
            "" if event.peak_ml_confidence is None
            else round(event.peak_ml_confidence, 4)
        ),
        "clip_path": clip_path or "",
        "thumbnail_path": thumbnail_path or "",
        "label": "",
        "species": "",
        "notes": "",
    }


class CsvWriter:
    """Append-only writer that guarantees whole-row writes per event."""

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._ensure_header()

    def _ensure_header(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            with open(self.csv_path, "w", newline="") as fh:
                csv.DictWriter(fh, fieldnames=CSV_COLUMNS).writeheader()

    def append_rows(self, rows: list[dict[str, object]]) -> None:
        """Append fully-formed rows and flush+fsync so finished work survives."""
        if not rows:
            return
        with open(self.csv_path, "a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            for row in rows:
                writer.writerow(row)
            fh.flush()
            import os

            os.fsync(fh.fileno())

    def existing_event_ids(self) -> set[str]:
        """event_ids already present (for restart reconciliation, SPEC §7)."""
        if not self.csv_path.exists():
            return set()
        with open(self.csv_path, "r", newline="") as fh:
            return {
                r["event_id"]
                for r in csv.DictReader(fh)
                if r.get("event_id")
            }
