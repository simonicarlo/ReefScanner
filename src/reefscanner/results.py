"""CSV results writer (SPEC §3 Step 6, §6).

One row per event. Append-only, whole rows per event (no partial flushes) so a
mid-write disconnect can't leave a torn row. The manifest (§7) is the source of
truth for "completed"; the CSV is append-only and reconciled on restart.
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from .events import Event, derive_timestamp
from .videoio import VideoInfo

logger = logging.getLogger("reefscanner")

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
    # Model's predicted class at the peak frame (detector mode); blank in
    # motion-only mode. Distinct from the human-filled `species` column.
    "detected_class",
    "clip_path",
    "thumbnail_path",
    # Reserved for the future labeling workflow (SPEC §9, §10) — left blank.
    "label",
    "species",
    "notes",
]

# Pre-`detected_class` (v1) column order. `detected_class` was inserted after
# `ml_confidence`, so a legacy row is the current schema minus that one column.
# Used to migrate CSVs written before detector mode existed (see _migrate).
LEGACY_CSV_COLUMNS = [c for c in CSV_COLUMNS if c != "detected_class"]
_KNOWN_SCHEMAS = {len(CSV_COLUMNS): CSV_COLUMNS, len(LEGACY_CSV_COLUMNS): LEGACY_CSV_COLUMNS}


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
        "motion_score": (
            "" if event.peak_motion_score is None
            else round(event.peak_motion_score, 1)
        ),
        "ml_confidence": (
            "" if event.peak_ml_confidence is None
            else round(event.peak_ml_confidence, 4)
        ),
        "detected_class": event.peak_class or "",
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
            return
        # File exists: make sure its header matches the current schema. A CSV
        # written by an older version (before `detected_class`) has a narrower
        # header; appending wider rows under it yields a file that strict
        # readers like pandas reject ("Expected N fields, saw N+1"). Migrate.
        with open(self.csv_path, "r", newline="") as fh:
            try:
                header = next(csv.reader(fh))
            except StopIteration:
                header = []
        if header != CSV_COLUMNS:
            self._migrate()

    def _migrate(self) -> None:
        """Rewrite the CSV to the current schema, row by row, losslessly.

        Handles a file with mixed row widths (legacy v1 rows alongside rows a
        newer version already appended). Each data row is interpreted by its
        field count against a known schema, then re-emitted in CSV_COLUMNS
        order with blanks for columns it didn't have. The original is kept as a
        ``.pre-migration.bak`` sibling so nothing is destroyed irrecoverably.
        """
        with open(self.csv_path, "r", newline="") as fh:
            raw = list(csv.reader(fh))
        if not raw:
            return
        data_rows = raw[1:]  # drop whatever header was there

        migrated: list[dict[str, object]] = []
        for cells in data_rows:
            if not cells:
                continue
            schema = _KNOWN_SCHEMAS.get(len(cells))
            if schema is None:
                # Unknown width: map positionally against the current schema,
                # truncating/padding so the row is at least well-formed.
                schema = CSV_COLUMNS
                cells = (cells + [""] * len(CSV_COLUMNS))[: len(CSV_COLUMNS)]
            row = dict(zip(schema, cells))
            migrated.append({c: row.get(c, "") for c in CSV_COLUMNS})

        backup = self.csv_path.with_suffix(self.csv_path.suffix + ".pre-migration.bak")
        if not backup.exists():
            backup.write_bytes(self.csv_path.read_bytes())
        logger.warning(
            "Migrated results CSV to current schema (%d columns); original kept at %s",
            len(CSV_COLUMNS), backup,
        )

        fd, tmp = tempfile.mkstemp(dir=str(self.csv_path.parent), suffix=".csv")
        with os.fdopen(fd, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(migrated)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.csv_path)

    def append_rows(self, rows: list[dict[str, object]]) -> None:
        """Append fully-formed rows and flush+fsync so finished work survives."""
        if not rows:
            return
        with open(self.csv_path, "a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            for row in rows:
                writer.writerow(row)
            fh.flush()
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
