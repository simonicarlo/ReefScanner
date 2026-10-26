"""Getting a run's data out: its Camtrap DP package, and training sets.

* ``build_package`` — the run as a Camtrap DP package: the deployment, the
  run's media, machine and human observations, and the sidecar. Written into
  the run folder, where the clips and frames already sit at the paths the
  media rows name, so the folder is the package.
* ``export_coco`` / ``export_yolo`` — confirmed events (TP reviews) as a
  detection training set, which is the whole reason for collecting reviews.
  They reference the clean peak frames, never anything with a box drawn on.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import aliased
from sqlmodel import Session, and_, select

from reefscanner.core.camtrap import (
    VERDICT_TP,
    Deployment,
    Detection,
    Media,
    Observation,
    ObservationExtra,
    Package,
    verdict_tag,
)
from .models import Job, Project, run_folder, scan_id


@dataclass
class Confirmed:
    """One TP review, ready to become a training annotation."""

    event_id: str
    image: Path
    category: str
    #: Relative to the frame, (x, y, w, h) in 0..1.
    bbox: tuple[float, float, float, float]


def build_package(session: Session, project: Project, job: Job) -> Package:
    """Everything one run contributes, as a Camtrap DP package."""
    scan = scan_id(job.id)
    extras = session.exec(
        select(ObservationExtra).where(ObservationExtra.scanID == scan)
    ).all()
    machine_ids = [e.observationID for e in extras]
    event_ids = [i.removesuffix(":machine") for i in machine_ids]
    observations = session.exec(
        select(Observation).where(Observation.eventID.in_(event_ids))
    ).all()
    media_ids = {f"{e}:{kind}" for e in event_ids for kind in ("clip", "frame")}
    media = session.exec(select(Media).where(Media.mediaID.in_(media_ids))).all()
    detections = session.exec(
        select(Detection).where(Detection.observationID.in_(machine_ids))
    ).all()
    return Package(
        deployments=[session.get(Deployment, project.deployment_id)],
        media=sorted(media, key=lambda m: m.mediaID),
        observations=sorted(observations, key=lambda o: o.observationID),
        observation_extras=sorted(extras, key=lambda e: e.observationID),
        detections=sorted(detections, key=lambda d: (d.observationID, d.frameTimestamp)),
        metadata={
            "title": f"{project.name} — scan {job.id}",
            "project": {"title": project.name},
            # The person running the app on this machine. Camtrap DP needs at
            # least one contributor; naming the team is for a later settings page.
            "contributors": [{"title": getpass.getuser(), "role": "contributor"}],
        },
    )


def confirmed_events(session: Session, project: Project, job: Job) -> list[Confirmed]:
    """TP reviews of this run with a box and a frame on disk."""
    human = aliased(Observation)
    rows = session.exec(
        select(Observation, human, Media)
        .join(ObservationExtra, ObservationExtra.observationID == Observation.observationID)
        .join(human, and_(
            human.eventID == Observation.eventID,
            human.classificationMethod == "human",
        ))
        .join(Media, Media.mediaID == Observation.mediaID)
        .where(ObservationExtra.scanID == scan_id(job.id))
        .where(Observation.classificationMethod == "machine")
        .where(human.observationTags == verdict_tag(VERDICT_TP))
    ).all()

    folder = run_folder(project, job.id)
    out = []
    for machine, review, frame in sorted(rows, key=lambda r: r[0].eventID):
        box = review if review.bboxX is not None else machine
        if box.bboxX is None:
            continue  # nothing to place a box with; skip rather than guess
        out.append(Confirmed(
            event_id=machine.eventID,
            image=folder / frame.filePath,
            # The reviewer's species is the most specific thing we know.
            category=review.scientificName or machine.scientificName or "animal",
            bbox=(box.bboxX, box.bboxY, box.bboxWidth, box.bboxHeight),
        ))
    return out


def export_coco(confirmed: list[Confirmed]) -> str:
    """COCO detection JSON for confirmed events. One image per event.

    COCO boxes are in pixels, so each frame's size is read from the image.
    """
    import cv2

    categories: dict[str, int] = {}
    images: list[dict] = []
    annotations: list[dict] = []
    for i, item in enumerate(confirmed, start=1):
        img = cv2.imread(str(item.image)) if item.image.is_file() else None
        if img is None:
            continue
        height, width = img.shape[:2]
        cat_id = categories.setdefault(item.category, len(categories) + 1)
        images.append({
            "id": i, "file_name": item.image.name, "width": width, "height": height,
        })
        x, y, w, h = item.bbox
        box = [round(x * width), round(y * height), round(w * width), round(h * height)]
        annotations.append({
            "id": i, "image_id": i, "category_id": cat_id,
            "bbox": box, "area": box[2] * box[3], "iscrowd": 0,
        })

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


def export_yolo(confirmed: list[Confirmed]) -> dict[str, str]:
    """YOLO-format labels as a path -> file-content mapping.

    ``labels/<n>.txt`` holds one normalised box each, named to match
    ``images/<n>.<ext>``, plus a ``classes.txt`` giving the class-index order —
    the part that's easy to lose and impossible to reconstruct afterwards.
    """
    class_names: list[str] = []
    files: dict[str, str] = {}
    for item in confirmed:
        if item.category not in class_names:
            class_names.append(item.category)
        x, y, w, h = item.bbox
        # YOLO wants the box centre and size as fractions of the image.
        files[f"labels/{yolo_stem(item)}.txt"] = (
            f"{class_names.index(item.category)} "
            f"{x + w / 2:.6f} {y + h / 2:.6f} {w:.6f} {h:.6f}\n"
        )
    files["classes.txt"] = "".join(f"{n}\n" for n in class_names)
    return files


def yolo_stem(item: Confirmed) -> str:
    """A file-name-safe stem shared by an image and its label file."""
    return item.image.stem
