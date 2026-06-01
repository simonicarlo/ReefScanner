"""Auto-download of default detector weights.

Lets ``detector='marine'`` work with no explicit ``detector_weights`` by
fetching SharkTrack's YOLOv8 weights (a single ~6 MB file committed in the
SharkTrack repo) into a local cache — the same convenience Ultralytics provides
for ``yolov8n.pt``. In Colab you'd usually point ``detector_weights`` at a Drive
path instead, so the file persists across sessions.
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


def ensure_sharktrack_weights() -> str:
    """Return a local path to SharkTrack weights, downloading once if needed."""
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
