#!/usr/bin/env python3
"""Generate synthetic BRUV-style footage, for trying ReefScanner without dives.

Writes a few 90-second clips of noisy "water" with a large slow object crossing
frame — plus flickery specks standing in for baitfish, which the motion gate's
size and persistence filters are supposed to reject. Good enough to exercise
the whole loop: scan, review, label, export.

    python scripts/make_demo_footage.py ~/ReefScanner-demo

Not a substitute for real footage when tuning thresholds — real water has
caustics, surge and rig sway, which is where false positives actually come from.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def make_clip(
    path: Path,
    *,
    fps: int = 10,
    seconds: int = 90,
    width: int = 640,
    height: int = 480,
    passes: tuple[tuple[float, float], ...] = ((40.0, 55.0),),
    seed: int = 0,
) -> Path:
    """Write one clip. ``passes`` is a tuple of (start, end) seconds."""
    rng = np.random.default_rng(seed)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not open a writer for {path}")

    try:
        for i in range(fps * seconds):
            t = i / fps
            # Dim, slightly noisy background — the "empty water" the gate learns.
            frame = rng.integers(38, 58, (height, width, 3)).astype(np.uint8)

            # Baitfish: small, bright, and different every frame, so they fail
            # both the size filter and the persistence filter.
            for _ in range(25):
                x = int(rng.integers(0, width - 4))
                y = int(rng.integers(0, height - 4))
                frame[y : y + 4, x : x + 4] = 210

            for start, end in passes:
                if start <= t <= end:
                    frac = (t - start) / max(1e-6, end - start)
                    cx = int(30 + frac * (width - 160))
                    cy = int(height / 2 + 40 * np.sin(frac * 3.5))
                    cv2.ellipse(
                        frame, (cx, cy), (55, 22), 0, 0, 360, (225, 228, 230), -1
                    )
                    # A tail, so the shape isn't a perfect blob.
                    cv2.ellipse(
                        frame, (cx - 60, cy), (18, 26), 0, 0, 360, (215, 219, 222), -1
                    )

            writer.write(frame)
    finally:
        writer.release()

    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Wrote nothing to {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Folder to write the clips into.")
    parser.add_argument("--clips", type=int, default=3, help="How many (default 3).")
    parser.add_argument("--seconds", type=int, default=90, help="Length each.")
    args = parser.parse_args(argv)

    folder = args.output.expanduser()
    folder.mkdir(parents=True, exist_ok=True)

    # Varying the passes gives the review screen something to distinguish:
    # one empty clip is the useful case where the gate should stay quiet.
    schedules: list[tuple[tuple[float, float], ...]] = [
        ((40.0, 55.0),),
        ((15.0, 26.0), (60.0, 72.0)),
        (),  # nothing swims past — this one should produce no events
    ]

    for i in range(args.clips):
        path = folder / f"dive{i + 1:02d}.mp4"
        passes = schedules[i % len(schedules)]
        print(f"  {path.name} … ", end="", flush=True)
        make_clip(path, seconds=args.seconds, passes=passes, seed=i)
        print(f"{len(passes)} animal pass(es)")

    print(f"\nDone. Point a ReefScanner project at:\n  {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
