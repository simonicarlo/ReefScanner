"""Auto-download of default detector weights.

Lets ``detector='marine'`` work with no explicit ``detector_weights`` by
fetching SharkTrack's YOLOv8 weights (a single ~6 MB file committed in the
SharkTrack repo) into a local cache — the same convenience Ultralytics provides
for ``yolov8n.pt``. Set ``detector_weights`` explicitly to use your own
fine-tuned checkpoint instead.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

logger = logging.getLogger("reefscanner")

#: SharkTrack weights (YOLOv8, single `elasmobranch` class, BRUVS-trained, MIT).
SHARKTRACK_WEIGHTS_URL = (
    "https://raw.githubusercontent.com/filippovarini/sharktrack/master/models/sharktrack.pt"
)
SHARKTRACK_FILENAME = "sharktrack.pt"


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
