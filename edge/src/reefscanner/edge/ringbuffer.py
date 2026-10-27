"""Ring buffer of the encoded full-quality stream.

Raw frames go into one ffmpeg process, which writes the stream as short
MPEG-TS segments with a keyframe forced at every boundary. Segment ``i`` covers
stream time ``[i * S, (i + 1) * S)``. It is complete once ffmpeg has started
segment ``i + 1``, or has exited. A clip is a lossless join of whole segments,
so cutting one never re-encodes. Its edges snap outwards to segment
boundaries, which only adds footage.

Segments older than the pre-roll are deleted unless a hold keeps them: an open
event holds everything from its start minus the pre-roll until its clip has
been cut. On a board the folder goes on tmpfs. Keeping every segment instead of
deleting old ones is the backup recorder (phase 1).

Why encoded and not raw frames: 30 s of raw 1080p is about 5 GB.
"""

from __future__ import annotations

import itertools
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("reefscanner.edge")

_PATTERN = "seg_%08d.ts"


class RingBuffer:
    def __init__(
        self,
        folder: str | Path,
        *,
        fps: float,
        width: int,
        height: int,
        ffmpeg: str,
        keep_seconds: float,
        segment_seconds: float = 2.0,
    ) -> None:
        self.folder = Path(folder)
        self.fps, self.width, self.height = fps, width, height
        self.segment_seconds = segment_seconds
        # One extra segment of slack: the detector runs a little behind
        # capture, so an event's start may be found after its pre-roll would
        # otherwise have gone.
        self.keep_seconds = keep_seconds + segment_seconds
        self._ffmpeg = ffmpeg
        self._proc: subprocess.Popen | None = None
        self._finished = False
        self._frames = 0
        self._next_segment = 0  # lowest segment not yet known to be complete
        self._deleted_below = 0  # every segment below this one is gone
        self._holds: dict[int, float] = {}
        self._hold_ids = itertools.count()
        self._cond = threading.Condition()

    # -- writing ------------------------------------------------------------------

    def start(self) -> None:
        if self.folder.exists():
            # Left behind by a crash; a new stream starts from segment 0.
            shutil.rmtree(self.folder)
        self.folder.mkdir(parents=True)
        s = self.segment_seconds
        cmd = [
            self._ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{self.width}x{self.height}", "-r", f"{self.fps}", "-i", "-",
            # Software x264 for phase 0; the board encodes in hardware.
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-force_key_frames", f"expr:gte(t,n_forced*{s})",
            "-f", "segment", "-segment_time", f"{s}", "-segment_format", "mpegts",
            str(self.folder / _PATTERN),
        ]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def write(self, image) -> None:
        """Append one full-quality BGR frame."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("ring buffer not started")
        try:
            self._proc.stdin.write(image.tobytes())
        except BrokenPipeError as exc:
            raise RuntimeError(f"encoder stopped: {self._stderr()}") from exc
        self._frames += 1
        self._refresh()

    def finish(self) -> None:
        """Flush the encoder; every segment written so far becomes complete."""
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            code = self._proc.wait(timeout=60)
            if code != 0:
                logger.error("encoder exited with %s: %s", code, self._stderr())
        finally:
            with self._cond:
                self._finished = True
                self._cond.notify_all()

    def close(self) -> None:
        """Stop the encoder if it is still running and delete the buffer."""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()
        with self._cond:
            self._finished = True
            self._cond.notify_all()
        shutil.rmtree(self.folder, ignore_errors=True)

    def _stderr(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            return self._proc.stderr.read().decode(errors="replace")[-2000:]
        except (OSError, ValueError):
            return ""

    def _scan(self) -> bool:
        """Notice newly completed segments. Call with the lock held."""
        advanced = False
        while (self.folder / (_PATTERN % (self._next_segment + 1))).exists():
            self._next_segment += 1
            advanced = True
        if advanced:
            self._cond.notify_all()
        return advanced

    def _refresh(self) -> None:
        """Notice newly completed segments and delete what nobody needs."""
        with self._cond:
            self._scan()
            floor = self.now() - self.keep_seconds
            if self._holds:
                floor = min(floor, min(self._holds.values()))
        # Never the segment in progress: _next_segment is not yet complete.
        upto = min(int(floor // self.segment_seconds), self._next_segment)
        for i in range(self._deleted_below, upto):
            (self.folder / (_PATTERN % i)).unlink(missing_ok=True)
        self._deleted_below = max(self._deleted_below, upto)

    # -- reading ------------------------------------------------------------------

    def now(self) -> float:
        """Stream time of the next frame to be written."""
        return self._frames / self.fps

    def hold(self, from_seconds: float) -> int:
        """Keep segments from ``from_seconds`` on until ``release``."""
        with self._cond:
            key = next(self._hold_ids)
            self._holds[key] = max(0.0, from_seconds)
            return key

    def release(self, key: int) -> None:
        with self._cond:
            self._holds.pop(key, None)

    def complete_until(self) -> float:
        """Stream time up to which every segment is on disk."""
        if self._finished:
            return self.now()
        return self._next_segment * self.segment_seconds

    def wait_until(self, seconds: float, timeout: float | None = None) -> bool:
        """Block until the stream up to ``seconds`` is on disk, or it ended."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while not (self._finished or self.complete_until() >= seconds):
                # ffmpeg finishes segments on its own time, possibly after the
                # last frame was written, so look at the folder too.
                if self._scan():
                    continue
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._cond.wait(0.2 if left is None else min(0.2, left))
            return True

    def cut(self, start: float, end: float, out_path: str | Path) -> float:
        """Write the footage from ``start`` to ``end`` as an MP4.

        Returns the stream time the clip really starts at, which is ``start``
        snapped down to its segment (or the oldest segment still kept).
        """
        s = self.segment_seconds
        first = max(int(max(0.0, start) // s), self._deleted_below)
        last = int(max(start, end) // s)
        segments = [
            self.folder / (_PATTERN % i) for i in range(first, last + 1)
            if (self.folder / (_PATTERN % i)).exists()
        ]
        if not segments:
            raise RuntimeError(f"no buffered footage from {start:.1f}s to {end:.1f}s")
        if first * s > start + 1e-6:
            logger.warning(
                "clip from %.1fs: footage before %.1fs was already gone", start, first * s
            )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_name(out_path.name + ".part")
        # concat: joins MPEG-TS byte streams; paths come from our own pattern.
        cmd = [
            self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", "concat:" + "|".join(str(p) for p in segments),
            "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(tmp),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"clip join failed: {proc.stderr[-2000:]}")
        os.replace(tmp, out_path)
        return int(segments[0].stem.split("_")[1]) * s
