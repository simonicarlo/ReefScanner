"""Where the desktop app writes its log, by each OS's convention.

One place for it, because three things must agree: the packaged app's
launcher writes there, the "couldn't start" page tells people where to look,
and Settings → About opens it. Kept free of heavy imports: the launcher reads
it before anything else is loaded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "ReefScanner"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ReefScanner" / "Logs"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "reefscanner"


def log_file() -> Path:
    return log_dir() / "reefscanner.log"


def shown(path: Path) -> str:
    """A path as people read it: the home folder as ``~``."""
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)
