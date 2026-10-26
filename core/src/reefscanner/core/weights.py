"""Auto-download of default detector weights.

Lets ``detector='marine'`` work with no explicit ``detector_weights`` by
fetching SharkTrack's YOLOv8 weights (a single ~6 MB file committed in the
SharkTrack repo) into a local cache — the same convenience Ultralytics provides
for ``yolov8n.pt``. Set ``detector_weights`` explicitly to use your own
fine-tuned checkpoint instead.

The default ONNX backend needs the same model as ``sharktrack.onnx``. Nobody
publishes that file, so it is exported from the ``.pt`` once (which needs the
``ultralytics`` extra) and cached next to it; the packaged app and the rig get
it bundled instead.
"""

from __future__ import annotations

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
    """Return a local path to SharkTrack as ONNX, exporting it once if needed.

    Preference order: the bundled copy, then the cache, then an export from the
    ``.pt`` weights (downloading those first if needed).
    """
    shipped = bundled_weights(SHARKTRACK_ONNX_FILENAME)
    if shipped is not None:
        return str(shipped)

    dest = cache_dir() / SHARKTRACK_ONNX_FILENAME
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    try:
        import ultralytics  # type: ignore  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            f"No SharkTrack ONNX model found in {dest.parent}. Create it once "
            "on a machine with the ultralytics extra installed "
            "(pip install 'reefscanner-core[ultralytics]') by running "
            "`reefscanner export-onnx`, then copy sharktrack.onnx here or set "
            "detector_weights to its path."
        ) from exc
    logger.info("Exporting SharkTrack to ONNX at %s (one-off)", dest)
    return export_onnx(ensure_sharktrack_weights(), dest, imgsz=SHARKTRACK_IMGSZ)


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
