#!/usr/bin/env python3
"""Check that the ONNX backend finds what the Ultralytics backend finds.

Runs both backends over the same sampled frames of real footage and compares
their detections box by box. Needs the ultralytics extra (the dev install has
it). Synthetic footage is no use here: SharkTrack finds nothing in it.

    uv run python scripts/check_onnx_parity.py inputs/*.mp4 [--fps 1] [--conf 0.2]

A detection counts as matched when the other backend has a box of the same
class overlapping it by IoU >= 0.5. What matters for recall is the last
column: frames where one backend saw something and the other saw nothing.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.detectors import get_detector
from reefscanner.core.videoio import iter_sampled_frames, probe_video


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def match(ref, other, threshold=0.5):
    """Greedy one-to-one matching by IoU; returns matched pairs."""
    pairs, used = [], set()
    for r in sorted(ref, key=lambda d: -d.confidence):
        best, best_j = 0.0, None
        for j, o in enumerate(other):
            if j in used or o.class_name != r.class_name:
                continue
            v = iou(r.bbox, o.bbox)
            if v > best:
                best, best_j = v, j
        if best_j is not None and best >= threshold:
            used.add(best_j)
            pairs.append((r, other[best_j], best))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--conf", type=float, default=0.2)
    ap.add_argument("--providers", nargs="+",
                    help="ONNX Runtime providers (default: best available)")
    args = ap.parse_args()

    opts = {"providers": args.providers} if args.providers else {}
    onnx = get_detector(ReefScannerConfig(
        ml_confidence_threshold=args.conf, detector_options=opts))
    ref = get_detector(ReefScannerConfig(
        ml_confidence_threshold=args.conf, detector_backend="ultralytics"))
    print(f"onnx providers: {onnx._session.get_providers()}")

    totals = dict(frames=0, ref=0, onnx=0, matched=0, ref_only_frames=0,
                  onnx_only_frames=0)
    t_ref = t_onnx = 0.0
    dconf, ious = [], []
    print(f"{'video':45} {'frames':>6} {'ref':>5} {'onnx':>5} {'match':>5} "
          f"{'only-ref frames':>15} {'only-onnx frames':>16}")
    for video in args.videos:
        info = probe_video(Path(video))
        row = dict(frames=0, ref=0, onnx=0, matched=0, ref_only_frames=0,
                   onnx_only_frames=0)
        for sample in iter_sampled_frames(info, args.fps):
            t0 = time.perf_counter()
            r = ref.detect(sample.frame)
            t1 = time.perf_counter()
            o = onnx.detect(sample.frame)
            t2 = time.perf_counter()
            t_ref += t1 - t0
            t_onnx += t2 - t1
            pairs = match(r, o)
            dconf += [abs(a.confidence - b.confidence) for a, b, _ in pairs]
            ious += [v for _, _, v in pairs]
            row["frames"] += 1
            row["ref"] += len(r)
            row["onnx"] += len(o)
            row["matched"] += len(pairs)
            row["ref_only_frames"] += bool(r) and not o
            row["onnx_only_frames"] += bool(o) and not r
        for k in totals:
            totals[k] += row[k]
        print(f"{Path(video).name[:45]:45} {row['frames']:>6} {row['ref']:>5} "
              f"{row['onnx']:>5} {row['matched']:>5} {row['ref_only_frames']:>15} "
              f"{row['onnx_only_frames']:>16}")

    n = max(totals["frames"], 1)
    print(f"\n{totals['matched']}/{totals['ref']} reference detections matched "
          f"({totals['onnx']} from onnx)")
    if dconf:
        print(f"confidence |Δ|: mean {np.mean(dconf):.4f}, max {np.max(dconf):.4f}; "
              f"IoU of matches: mean {np.mean(ious):.3f}, min {np.min(ious):.3f}")
    print(f"frames where only one backend saw anything: "
          f"ref {totals['ref_only_frames']}, onnx {totals['onnx_only_frames']}")
    print(f"per frame: ultralytics {1000 * t_ref / n:.1f} ms, "
          f"onnx {1000 * t_onnx / n:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
