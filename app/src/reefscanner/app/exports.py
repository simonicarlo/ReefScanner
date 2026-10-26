"""Getting data out of the database.

* ``export_csv`` — the engine's results CSV (``core.results.CSV_COLUMNS``),
  with the human label columns filled in.
* ``export_coco`` / ``export_yolo`` — turn confirmed events into a detection
  training set, which is the whole reason for collecting labels. They reference
  the clean peak frames, never the thumbnails with the box drawn on them.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
from pathlib import Path
from typing import Iterable, Optional, Sequence

from reefscanner.core.results import CSV_COLUMNS
from .models import VERDICT_TP, Event, Label

#: Events with these verdicts become training annotations. Explicitly not
#: ``unsure`` — a box a human couldn't call is not a box to train on.
EXPORTABLE_VERDICTS = (VERDICT_TP,)


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
    """Render events + labels as a results CSV."""
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


def annotation_image(event: Event) -> Optional[str]:
    """The image an annotation points at: the clean peak frame."""
    return event.frame_path


def _frame_size(event: Event) -> Optional[tuple[int, int]]:
    """Resolution of the coordinate space ``peak_bbox`` lives in, recorded at ingest."""
    if event.frame_width and event.frame_height:
        return event.frame_width, event.frame_height
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
                "file_name": Path(annotation_image(event) or "").name,
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
