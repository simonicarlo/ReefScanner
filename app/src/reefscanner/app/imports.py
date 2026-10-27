"""Importing a Camtrap DP package (from the rig, an SD card, another laptop).

A package becomes a project with one import run: its files are copied into the
run folder and its rows go into the database under the run's ``scanID``, so the
review flow, analysis and exports treat it exactly like a scan. Design:
docs/specs/v3/features/2026-10-26-package-import-design.md.

The package is untrusted input. Beyond the standard's own checks, every media
path must name a regular file inside the package folder through no symlink at
all, and the package must have ReefScanner's shape: a sidecar row plus clip and
frame media for every machine observation. Every problem is reported at once.

Files are opened one path component at a time with ``O_NOFOLLOW``, both when
checking and again when copying, and copied from the open descriptor. Swapping
a file or folder for a link between the check and the copy therefore fails
instead of pulling in a file from outside the package. The rig never writes
symlinks, so refusing them costs nothing.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from sqlmodel import Session

from reefscanner.core.camtrap import Deployment, Package, PackageError, read_package, validate
from reefscanner.core.config import ReefScannerConfig

#: Settings a package may carry into a project: detection and event tuning
#: only, every one a number, flag or validated choice. Anything that names a
#: program, a model file or an output file name (``ffmpeg_path``,
#: ``detector_weights``, ``detector_options``, ``thumbnail_ext``, the folder
#: and file names) stays at this laptop's defaults: a hostile package must not
#: pick what a later rescan runs or where it writes. An allowlist, so a new
#: setting stays out until someone decides it is safe.
_CONFIG_KEYS = frozenset({
    "camera_timezone", "camera_clock",
    "detector", "detector_backend", "ml_confidence_threshold", "target_classes",
    "frame_sample_fps", "detect_downscale", "motion_prefilter",
    "warmup_frames", "min_blob_area", "persistence_frames", "bg_subtractor",
    "detect_shadows", "bg_history", "mog2_var_threshold", "morph_kernel_size",
    "merge_gap_seconds", "min_event_seconds", "pad_seconds", "reencode_clips",
    "use_sahi", "sahi_slice_height", "sahi_slice_width", "sahi_overlap",
})


@dataclass
class CheckedPackage:
    folder: Path
    package: Package
    #: mediaID -> its file's path relative to the package root
    files: dict[str, str]
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
            files[m.mediaID] = rel

    config = _config(list(extras.values()), problems)
    if problems:
        raise PackageError(problems)
    return CheckedPackage(folder=root, package=package, files=files, config=config)


def _inside(root: Path, file_path: str) -> str | None:
    """``file_path`` normalised, if it names a regular file inside ``root``
    reached through no symlink; otherwise None."""
    try:
        parts = _parts(file_path)
        fd = open_inside(root, parts)
    except (OSError, ValueError):
        return None
    os.close(fd)
    return "/".join(parts)


def _parts(file_path: str) -> tuple[str, ...]:
    path = PurePosixPath(file_path.replace("\\", "/"))
    parts = path.parts
    if not parts or path.is_absolute() or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"not a relative path inside the package: {file_path!r}")
    return parts


def open_inside(root: Path, parts: tuple[str, ...]) -> int:
    """Open ``root/parts…`` for reading, following no symlink on the way.

    Each folder is opened relative to the one before with ``O_NOFOLLOW``, so a
    link anywhere in the path, swapped in at any time, makes the open fail.
    Returns a descriptor of a regular file; the caller closes it.
    """
    if os.open not in os.supports_dir_fd:  # pragma: no cover - not macOS/Linux
        raise OSError("this system can't open files without following links")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = nxt
        file_fd = os.open(parts[-1], flags, dir_fd=fd)
    finally:
        os.close(fd)
    if not stat.S_ISREG(os.fstat(file_fd).st_mode):
        os.close(file_fd)
        raise OSError(f"not a regular file: {'/'.join(parts)}")
    return file_fd


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

    Each source is reopened without following links (see ``open_inside``),
    since the package may have changed since it was checked. Each copy is
    written to a temporary name and renamed, so a file at its final path is
    always complete.
    """
    unique = sorted(set(checked.files.values()))
    for i, rel in enumerate(unique):
        if should_cancel is not None and should_cancel():
            return False
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        try:
            with os.fdopen(open_inside(checked.folder, _parts(rel)), "rb") as src, \
                    open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        if on_file is not None:
            on_file(i + 1, len(unique))
    return True


def insert_rows(
    session: Session, checked: CheckedPackage, scan: str, deployment_id: str
) -> int:
    """Add the package's media, observations and sidecars under run ``scan``.

    ``deployment_id`` is the project's deployment, which already exists; its
    details are taken from the package. The package is read again when the
    import runs, so it must still be that deployment: otherwise a swapped
    folder could write into another project's. (``validate`` has already
    checked that every row references the package's one deployment.)
    Returns the number of events. Does not commit.
    """
    p = checked.package
    (incoming,) = p.deployments
    if incoming.deploymentID != deployment_id:
        raise PackageError([
            f"the package is now deployment {incoming.deploymentID!r}, "
            f"not {deployment_id!r} as when it was checked"
        ])
    deployment = session.get(Deployment, deployment_id)
    for field in Deployment.model_fields:
        if field != "deploymentID":
            setattr(deployment, field, getattr(incoming, field))
    session.add(deployment)

    # Parents first: there are no ORM relationships to order the inserts.
    for level in (
        [_with(m, filePath=checked.files[m.mediaID]) for m in p.media],
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
