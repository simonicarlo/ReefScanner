"""Step 1 — Discover: recursively find video files (SPEC §3 Step 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


def discover_videos(
    input_folder: str | Path,
    extensions: Sequence[str] | Iterable[str],
) -> list[Path]:
    """Recursively find video files under ``input_folder``.

    Matching is case-insensitive on the extension. Results are returned sorted
    by path so processing order is deterministic across runs (important for
    resumability and reproducible event IDs).
    """
    root = Path(input_folder)
    if not root.exists():
        raise FileNotFoundError(f"Input folder does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a folder: {root}")

    wanted = {(e if e.startswith(".") else "." + e).lower() for e in extensions}
    found: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in wanted:
            found.append(path)
    return sorted(found)
