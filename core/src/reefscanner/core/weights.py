"""Auto-download of default detector weights.

Lets ``detector='marine'`` work with no explicit ``detector_weights`` by
fetching SharkTrack's YOLOv8 weights (a single ~6 MB file committed in the
SharkTrack repo) into a local cache — the same convenience Ultralytics provides
for ``yolov8n.pt``. Set ``detector_weights`` explicitly to use your own
fine-tuned checkpoint instead.

The default ONNX backend needs the same model as ``sharktrack.onnx``. SharkTrack
doesn't publish one, so ReefScanner does, as a GitHub release asset (exported
with ``reefscanner export-onnx``). It is downloaded and checked against a
pinned hash; with the ``ultralytics`` extra installed it can also be exported
locally if the download fails. The packaged app gets it bundled.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

logger = logging.getLogger("reefscanner")

#: SharkTrack weights (YOLOv8, single `elasmobranch` class, BRUVS-trained, MIT).
SHARKTRACK_WEIGHTS_URL = (
    "https://raw.githubusercontent.com/filippovarini/sharktrack/master/models/sharktrack.pt"
)
SHARKTRACK_FILENAME = "sharktrack.pt"
SHARKTRACK_ONNX_FILENAME = "sharktrack.onnx"
#: Our ONNX export of the same weights (dynamic input, 640 px, opset 17).
SHARKTRACK_ONNX_URL = (
    "https://github.com/simonicarlo/ReefScanner/releases/download/"
    "models-v1/sharktrack.onnx"
)
#: Pinned so a replaced or corrupted release file is refused, not run.
SHARKTRACK_ONNX_SHA256 = (
    "ebbef2594720033066cc3eca0809c144b7092660a2018080a6042ae1ab565ff4"
)
#: SharkTrack was trained at 640 px, so it is exported at that input size.
SHARKTRACK_IMGSZ = 640


def cache_dir() -> Path:
    """Where auto-downloaded weights are cached (override via REEFSCANNER_CACHE)."""
    base = os.environ.get("REEFSCANNER_CACHE")
    d = Path(base) if base else Path.home() / ".cache" / "reefscanner"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_weights(filename: str) -> Path | None:
    """Weights shipped inside the packaged desktop app, if running from one.

    PyInstaller marks a frozen app with ``sys.frozen`` and unpacks its data
    under ``sys._MEIPASS``; the build puts the weights in a ``weights`` folder
    there. Outside a packaged app this is always None.
    """
    import sys

    if not getattr(sys, "frozen", False):
        return None
    candidate = Path(getattr(sys, "_MEIPASS", "")) / "weights" / filename
    return candidate if candidate.is_file() else None


def ensure_sharktrack_weights() -> str:
    """Return a local path to SharkTrack weights, downloading once if needed.

    Preference order: the copy bundled with the desktop app (so a first scan
    works offline), then the download cache, then a download.
    """
    shipped = bundled_weights(SHARKTRACK_FILENAME)
    if shipped is not None:
        return str(shipped)

    dest = cache_dir() / SHARKTRACK_FILENAME
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    logger.info("Downloading SharkTrack weights to %s", dest)
    try:
        urllib.request.urlretrieve(SHARKTRACK_WEIGHTS_URL, dest)
    except Exception as exc:  # network/SSL/etc.
        # Leave no partial file behind.
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to auto-download SharkTrack weights from "
            f"{SHARKTRACK_WEIGHTS_URL}: {exc}. Download it manually and set "
            "config.detector_weights to the local path."
        ) from exc
    return str(dest)


def ensure_sharktrack_onnx() -> str:
    """Return a local path to SharkTrack as ONNX, fetching it once if needed.

    Preference order: the bundled copy, then the cache, then a download of our
    published export, then a local export from the ``.pt`` (only possible with
    the ``ultralytics`` extra).
    """
    shipped = bundled_weights(SHARKTRACK_ONNX_FILENAME)
    if shipped is not None:
        return str(shipped)

    dest = cache_dir() / SHARKTRACK_ONNX_FILENAME
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)

    logger.info("Downloading SharkTrack (ONNX) to %s", dest)
    try:
        return _download(SHARKTRACK_ONNX_URL, dest, sha256=SHARKTRACK_ONNX_SHA256)
    except Exception as download_error:
        try:
            import ultralytics  # type: ignore  # noqa: F401
        except ImportError:
            raise RuntimeError(
                f"Failed to download SharkTrack (ONNX) from "
                f"{SHARKTRACK_ONNX_URL}: {download_error}. Download it manually "
                f"into {dest.parent}, or export it with `reefscanner export-onnx` "
                "on a machine with the ultralytics extra "
                "(pip install 'reefscanner-core[ultralytics]')."
            ) from download_error
        logger.warning(
            "Download failed (%s); exporting SharkTrack to ONNX locally instead",
            download_error,
        )
        return export_onnx(ensure_sharktrack_weights(), dest, imgsz=SHARKTRACK_IMGSZ)


def _download(url: str, dest: Path, sha256: str | None = None) -> str:
    """Fetch ``url`` to ``dest`` atomically, checking its hash if one is given."""
    partial = dest.with_name(dest.name + ".partial")
    try:
        urllib.request.urlretrieve(url, partial)
        if sha256 is not None:
            digest = hashlib.sha256(partial.read_bytes()).hexdigest()
            if digest != sha256:
                raise ValueError(f"checksum mismatch: got {digest}, expected {sha256}")
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    return str(dest)


def export_onnx(
    weights: str, dest: str | Path, imgsz: int = 640, static: bool = False
) -> str:
    """Export an Ultralytics YOLO checkpoint to ONNX at ``dest``.

    Needs the ``ultralytics`` extra. By default the input shape is dynamic, so
    frames are padded only to a multiple of the stride, exactly as Ultralytics
    runs the ``.pt`` — the two backends then give the same detections. Board
    runtimes (TensorRT, Hailo, RKNN) want a fixed shape instead: ``static``
    exports a square ``imgsz`` input, which pads every frame to that square
    and shifts confidences slightly.
    """
    from ultralytics import YOLO  # type: ignore

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Ultralytics writes the export next to the weights, so export a copy in a
    # scratch folder rather than litter the user's model directory.
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / Path(weights).name
        shutil.copyfile(weights, src)
        exported = YOLO(str(src)).export(
            format="onnx", imgsz=imgsz, dynamic=not static, simplify=True,
            opset=17,
        )
        tmp_dest = dest.with_suffix(".onnx.partial")
        shutil.copyfile(exported, tmp_dest)
        tmp_dest.replace(dest)  # never leave a half-written model in the cache
    return str(dest)
