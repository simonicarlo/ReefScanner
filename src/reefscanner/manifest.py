"""Resumability manifest (SPEC §7).

The manifest is the *source of truth* for what is "done". A video is marked
complete only after its clips, thumbnails and CSV rows are all flushed. An
interrupted video is not marked complete and is reprocessed from frame 0 on
restart (no mid-video resume — SPEC §3, §7).

A relative key (path relative to the input folder) identifies each video so the
manifest stays valid if the Drive mount point changes between Colab sessions.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Optional


class Manifest:
    def __init__(self, manifest_path: str | Path, input_root: str | Path):
        self.manifest_path = Path(manifest_path)
        self.input_root = Path(input_root)
        self._data: dict = {"version": 1, "videos": {}}
        self._load()

    def _load(self) -> None:
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict) and "videos" in loaded:
                    self._data = loaded
            except (json.JSONDecodeError, OSError):
                # Corrupt/partial manifest: start fresh rather than crash. The
                # CSV reconciliation (existing_event_ids) still guards dupes.
                self._data = {"version": 1, "videos": {}}

    def _key(self, video_path: str | Path) -> str:
        p = Path(video_path)
        try:
            return p.relative_to(self.input_root).as_posix()
        except ValueError:
            return p.as_posix()

    def is_complete(self, video_path: str | Path) -> bool:
        entry = self._data["videos"].get(self._key(video_path))
        return bool(entry and entry.get("status") == "complete")

    def mark_complete(
        self,
        video_path: str | Path,
        n_events: int,
        event_ids: Optional[list[str]] = None,
    ) -> None:
        self._data["videos"][self._key(video_path)] = {
            "status": "complete",
            "n_events": n_events,
            "event_ids": event_ids or [],
            "completed_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def completed_videos(self) -> list[str]:
        return [
            k for k, v in self._data["videos"].items()
            if v.get("status") == "complete"
        ]

    def event_ids_for(self, video_path: str | Path) -> list[str]:
        entry = self._data["videos"].get(self._key(video_path), {})
        return list(entry.get("event_ids", []))

    def _save(self) -> None:
        """Atomic write: temp file + fsync + os.replace (SPEC §7 durability)."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(self.manifest_path.suffix + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(self._data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.manifest_path)
