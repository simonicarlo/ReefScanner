"""Entry point for the packaged desktop app.

PyInstaller runs this file as ``__main__`` inside the ``.app``. Two things have
to happen before anything heavy is imported:

* ``multiprocessing.freeze_support()`` — in a frozen app a child process is
  started by re-running this executable. Without the call, anything torch
  spawns would boot a second copy of the whole app and open another window.
* File logging — a windowed app has no terminal, so without a log file a
  failure on someone else's Mac leaves nothing to diagnose.
"""

from __future__ import annotations

import logging
import multiprocessing
import sys
from pathlib import Path

LOG_DIR = Path.home() / "Library" / "Logs" / "ReefScanner"


def _configure_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "reefscanner.log"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return log_file


def main() -> int:
    log_file = _configure_logging()
    logging.getLogger("reefscanner").info("Starting ReefScanner (log: %s)", log_file)
    try:
        from reefscanner.desktop.main import run

        return run()
    except Exception:
        logging.getLogger("reefscanner").exception("ReefScanner crashed")
        raise


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
