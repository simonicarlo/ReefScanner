"""Importing a Camtrap DP package (from the rig, an SD card, another laptop).

A package becomes a project with one import run: its files are copied into the
run folder and its rows go into the database under the run's ``scanID``, so the
review flow, analysis and exports treat it exactly like a scan. Design:
docs/specs/v3/features/2026-10-26-package-import-design.md.

The package is untrusted input. Beyond the standard's own checks, every media
path must resolve (symlinks included) to a file inside the package folder, and
the package must have ReefScanner's shape: a sidecar row plus clip and frame
media for every machine observation. Every problem is reported at once.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlmodel import Session

from reefscanner.core.camtrap import Deployment, Package, PackageError, read_package, validate
from reefscanner.core.config import ReefScannerConfig

_CONFIG_KEYS = {f.name for f in dataclasses.fields(ReefScannerConfig)} - {
    "input_folder", "output_folder",
}


@dataclass
class CheckedPackage:
    folder: Path
    package: Package
    #: mediaID -> (file inside the package, its path relative to the root)
    files: dict[str, tuple[Path, str]]
    #: The engine config its observations were made with.
    config: dict[str, Any]


def check_package(folder: str | Path) -> CheckedPackage:
    """Read and check a package folder; raises ``PackageError`` with every problem."""
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise PackageError([f"not a folder: {folder}"])
    root = folder.resolve()
    package = read_package(root)
    problems = validate(package)

    if len(package.deployments) != 1:
        problems.append(
            f"a project holds one deployment; this package has {len(package.deployments)}"
        )

    media = {m.mediaID: m for m in package.media}
    extras = {e.observationID: e for e in package.observation_extras}
    machine = [o for o in package.observations if o.classificationMethod == "machine"]
    if not machine:
        problems.append("no machine observations: nothing to review")
    for o in machine:
        if o.observationID not in extras:
            problems.append(f"observation {o.observationID!r}: no reefscanner-observations row")
        for kind in ("clip", "frame"):
            if f"{o.eventID}:{kind}" not in media:
                problems.append(f"event {o.eventID!r}: no {kind} in media")

    files = {}
    for m in package.media:
        rel = _inside(root, m.filePath)
        if rel is None:
            problems.append(f"media {m.mediaID!r}: {m.filePath!r} is not a file in the package")
        else:
            files[m.mediaID] = (root / rel, rel)

    config = _config(list(extras.values()), problems)
    if problems:
        raise PackageError(problems)
    return CheckedPackage(folder=root, package=package, files=files, config=config)


def _inside(root: Path, file_path: str) -> str | None:
    """``file_path`` relative to ``root`` if it is a file inside it, else None."""
    if not file_path or Path(file_path).is_absolute():
        return None
    target = (root / file_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target.relative_to(root).as_posix()


def _config(extras: list, problems: list[str]) -> dict[str, Any]:
    """The scan settings recorded with the observations, as a project config.

    The camera timezone is required: without it a rescan of the project
    couldn't place its own events in time.
    """
    recorded = next((e.detectorConfig for e in extras if e.detectorConfig), None) or {}
    config = {k: v for k, v in recorded.items() if k in _CONFIG_KEYS}
    try:
        config = ReefScannerConfig.from_dict(config).to_dict()
    except (TypeError, ValueError) as exc:
        problems.append(f"recorded detector config is invalid: {exc}")
        return {}
    if not config.get("camera_timezone"):
        problems.append("the package doesn't record the camera timezone (detectorConfig)")
    for key in ("input_folder", "output_folder"):
        config.pop(key, None)
    return config


def copy_files(
    checked: CheckedPackage,
    dest: Path,
    on_file: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> bool:
    """Copy the package's media files into ``dest``. False if cancelled.

    Each file is written to a temporary name and renamed, so a file at its
    final path is always complete.
    """
    unique = sorted(set(checked.files.values()))
    for i, (src, rel) in enumerate(unique):
        if should_cancel is not None and should_cancel():
            return False
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        if on_file is not None:
            on_file(i + 1, len(unique))
    return True


def insert_rows(session: Session, checked: CheckedPackage, scan: str) -> int:
    """Add the package's media, observations and sidecars under run ``scan``.

    The deployment row already exists (the project points at it); its times
    are taken from the package. Returns the number of events. Does not commit.
    """
    p = checked.package
    (incoming,) = p.deployments
    deployment = session.get(Deployment, incoming.deploymentID)
    for field in Deployment.model_fields:
        if field != "deploymentID":
            setattr(deployment, field, getattr(incoming, field))
    session.add(deployment)

    # Parents first: there are no ORM relationships to order the inserts.
    for level in (
        [_with(m, filePath=checked.files[m.mediaID][1]) for m in p.media],
        p.observations,
        [_with(e, scanID=scan) for e in p.observation_extras],
        [_with(d, id=None) for d in p.detections],
    ):
        session.add_all(level)
        session.flush()
    return sum(1 for o in p.observations if o.classificationMethod == "machine")


def _with(row: Any, **changes: Any) -> Any:
    """A fresh copy of a table row with some fields changed."""
    return type(row).model_validate({**row.model_dump(), **changes})
