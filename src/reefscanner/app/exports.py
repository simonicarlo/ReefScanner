"""Getting data in and out of the database.

Three jobs:

* ``import_csv_events`` — adopt a ``reefscanner_results.csv`` from a v1 run so
  those results aren't orphaned by the move to SQLite.
* ``export_csv`` — write the same format back out, now with the human label
  columns actually filled in. This keeps the v1 CSV contract
  (``engine.results.CSV_COLUMNS``) intact as an interchange format.
* ``export_coco`` / ``export_yolo`` — turn confirmed events into a detection
  training set, which is the whole reason for collecting labels.

**Known limitation of the annotation exports:** the images they reference are
the engine's thumbnails, which have the detection box *drawn onto them* in red
(``engine.clips.save_thumbnail``). That burned-in box is fine for human triage
but is a visible artifact for a model to learn from. Re-extract clean peak
frames before actually fine-tuning on this data.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
from pathlib import Path
from typing import Iterable, Optional, Sequence

from sqlmodel import Session, select

from ..engine.results import CSV_COLUMNS
from .models import VERDICT_TP, Event, Label

#: Events with these verdicts become training annotations. Explicitly not
#: ``unsure`` — a box a human couldn't call is not a box to train on.
EXPORTABLE_VERDICTS = (VERDICT_TP,)


def _f(value: str) -> Optional[float]:
    """Parse a CSV cell that may legitimately be blank."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def import_csv_events(session: Session, job_id: int, csv_path: str | Path) -> int:
    """Load a v1 results CSV into ``job_id``. Returns the number of new events.

    Idempotent: events already present for this job (matched on the engine's
    ``event_id``) are skipped rather than duplicated, so re-importing after a
    partial run is safe. A filled-in ``label`` column is carried across too —
    that's hand-done work and losing it would defeat the point of the bridge.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return 0

    stmt = select(Event.event_id).where(Event.job_id == job_id)
    existing = set(session.exec(stmt).all())

    added = 0
    with open(csv_path, "r", newline="") as fh:
        for row in csv.DictReader(fh):
            eid = (row.get("event_id") or "").strip()
            if not eid or eid in existing:
                continue

            event = Event(
                job_id=job_id,
                event_id=eid,
                source_video=row.get("source_video", ""),
                start_seconds=_f(row.get("start_seconds", "")) or 0.0,
                end_seconds=_f(row.get("end_seconds", "")) or 0.0,
                duration_seconds=_f(row.get("duration_s", "")) or 0.0,
                start_timestamp=row.get("start_timestamp", "") or "",
                motion_score=_f(row.get("motion_score", "")),
                ml_confidence=_f(row.get("ml_confidence", "")),
                detected_class=(row.get("detected_class") or "") or None,
                clip_path=(row.get("clip_path") or "") or None,
                thumbnail_path=(row.get("thumbnail_path") or "") or None,
            )
            # The v1 CSV has no peak columns; the clip itself is the record.
            event.peak_timestamp = event.start_seconds
            event.peak_score = event.ml_confidence or event.motion_score or 0.0
            session.add(event)
            session.flush()  # need event.id to hang a label off

            verdict = (row.get("label") or "").strip()
            if verdict:
                session.add(
                    Label(
                        event_id=event.id,
                        verdict=_normalise_verdict(verdict),
                        species=(row.get("species") or "") or None,
                        notes=(row.get("notes") or "") or None,
                    )
                )
            existing.add(eid)
            added += 1

    session.commit()
    return added


def _normalise_verdict(raw: str) -> str:
    """Map the free-text labels a human typed into a v1 CSV onto our verdicts."""
    v = raw.strip().lower()
    if v in ("tp", "true", "yes", "y", "1", "shark", "animal"):
        return "TP"
    if v in ("fp", "false", "no", "n", "0"):
        return "FP"
    return "unsure"


def _rows_for(pairs: Sequence[tuple[Event, Optional[Label]]]) -> list[dict]:
    rows = []
    for event, label in pairs:
        rows.append(
            {
                "event_id": event.event_id,
                "source_video": event.source_video,
                "start_seconds": round(event.start_seconds, 3),
                "end_seconds": round(event.end_seconds, 3),
                "duration_s": round(event.duration_seconds, 3),
                "start_timestamp": event.start_timestamp,
                "motion_score": (
                    "" if event.motion_score is None else round(event.motion_score, 1)
                ),
                "ml_confidence": (
                    "" if event.ml_confidence is None else round(event.ml_confidence, 4)
                ),
                "detected_class": event.detected_class or "",
                "clip_path": event.clip_path or "",
                "thumbnail_path": event.thumbnail_path or "",
                "label": label.verdict if label else "",
                "species": (label.species if label else "") or "",
                "notes": (label.notes if label else "") or "",
            }
        )
    return rows


def export_csv(pairs: Sequence[tuple[Event, Optional[Label]]]) -> str:
    """Render events + labels as a v1-compatible results CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(_rows_for(pairs))
    return buf.getvalue()


def _annotation_box(event: Event, label: Optional[Label]) -> Optional[list[int]]:
    """The best box available: a human's correction beats the engine's guess."""
    if label is not None and label.tight_bbox:
        return list(label.tight_bbox)
    if event.peak_bbox:
        return list(event.peak_bbox)
    return None


def _category_of(label: Optional[Label], event: Event) -> str:
    """What to call this annotation's class.

    A human-tagged species is the most specific thing we know, so it wins; the
    model's own class is the fallback, and a generic bucket the last resort.
    """
    if label is not None and label.species:
        return label.species.strip()
    if event.detected_class:
        return event.detected_class
    return "animal"


def _frame_size(event: Event) -> Optional[tuple[int, int]]:
    """Resolution of the coordinate space ``peak_bbox`` lives in.

    Prefer what we recorded at ingest; fall back to measuring the thumbnail,
    which is a full-resolution peak frame, for events imported from a v1 CSV.
    """
    if event.frame_width and event.frame_height:
        return event.frame_width, event.frame_height
    if event.thumbnail_path and Path(event.thumbnail_path).exists():
        import cv2  # local import: keep the exporter importable without OpenCV

        img = cv2.imread(event.thumbnail_path)
        if img is not None:
            h, w = img.shape[:2]
            return int(w), int(h)
    return None


def _exportable(
    pairs: Iterable[tuple[Event, Optional[Label]]],
) -> list[tuple[Event, Label]]:
    return [
        (e, lab)
        for e, lab in pairs
        if lab is not None and lab.verdict in EXPORTABLE_VERDICTS
    ]


def export_coco(pairs: Sequence[tuple[Event, Optional[Label]]]) -> str:
    """COCO detection JSON for confirmed events. One image per event."""
    kept = _exportable(pairs)

    categories: dict[str, int] = {}
    images: list[dict] = []
    annotations: list[dict] = []

    for i, (event, label) in enumerate(kept, start=1):
        box = _annotation_box(event, label)
        size = _frame_size(event)
        if box is None or size is None:
            continue  # nothing to place a box in; skip rather than guess
        width, height = size

        name = _category_of(label, event)
        cat_id = categories.setdefault(name, len(categories) + 1)

        images.append(
            {
                "id": i,
                "file_name": Path(event.thumbnail_path or "").name,
                "width": width,
                "height": height,
            }
        )
        x, y, w, h = box
        annotations.append(
            {
                "id": i,
                "image_id": i,
                "category_id": cat_id,
                "bbox": [x, y, w, h],  # COCO is [x, y, w, h] — same as ours
                "area": w * h,
                "iscrowd": 0,
            }
        )

    doc = {
        "info": {
            "description": "ReefScanner confirmed events",
            "date_created": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        },
        "images": images,
        "annotations": annotations,
        "categories": [
            {"id": cid, "name": name}
            for name, cid in sorted(categories.items(), key=lambda kv: kv[1])
        ],
    }
    return json.dumps(doc, indent=2)


def export_yolo(pairs: Sequence[tuple[Event, Optional[Label]]]) -> dict[str, str]:
    """YOLO-format dataset as a path -> file-content mapping.

    Returns ``labels/<event>.txt`` files (one normalised box each) plus a
    ``classes.txt`` giving the class-index order, which is the part that's easy
    to lose and impossible to reconstruct afterwards.
    """
    kept = _exportable(pairs)

    class_names: list[str] = []
    files: dict[str, str] = {}

    for event, label in kept:
        box = _annotation_box(event, label)
        size = _frame_size(event)
        if box is None or size is None:
            continue
        width, height = size
        if width <= 0 or height <= 0:
            continue

        name = _category_of(label, event)
        if name not in class_names:
            class_names.append(name)
        cls = class_names.index(name)

        x, y, w, h = box
        # YOLO wants the box centre and size as fractions of the image.
        cx = (x + w / 2) / width
        cy = (y + h / 2) / height
        nw = w / width
        nh = h / height
        files[f"labels/{event.event_id}.txt"] = (
            f"{cls} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}\n"
        )

    files["classes.txt"] = "".join(f"{n}\n" for n in class_names)
    return files
