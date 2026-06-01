"""Command-line interface (SPEC §5).

    reefscanner process <input_folder> --out <output_folder> [--fps 1.0]
                        [--detector none] [...]
    reefscanner report  <output_folder>   # false-positive rate (SPEC §8.6)

Every config field is overridable; CLI flags take precedence over an optional
``--config file.yaml``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .config import VALID_DETECTORS, ReefScannerConfig
from .pipeline import process_folder
from .report import fp_report


def _add_process_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("input_folder", help="Folder of input videos (searched recursively).")
    p.add_argument("--out", "--output", dest="output_folder", required=True,
                   help="Output folder (clips, thumbnails, CSV, manifest).")
    p.add_argument("--config", help="Optional YAML config file (flags override it).")

    # Sampling / detection
    p.add_argument("--fps", dest="frame_sample_fps", type=float,
                   help="Sampled decode frame rate (default 1.0).")
    p.add_argument("--detect-downscale", type=float,
                   help="Downscale factor for detection (default 0.5).")

    # Motion gating
    p.add_argument("--warmup-frames", type=int)
    p.add_argument("--min-blob-area", type=int)
    p.add_argument("--persistence-frames", type=int)
    p.add_argument("--bg-subtractor", choices=["MOG2", "KNN"])
    p.add_argument("--no-shadows", dest="detect_shadows", action="store_false",
                   default=None, help="Disable shadow detection.")

    # Event aggregation
    p.add_argument("--merge-gap-seconds", type=float)
    p.add_argument("--min-event-seconds", type=float)

    # Output / clips
    p.add_argument("--pad-seconds", type=float)
    p.add_argument("--reencode", dest="reencode_clips", action="store_true",
                   default=None, help="Re-encode clips (accurate boundaries).")
    p.add_argument("--ffmpeg-path")
    p.add_argument("--ext", dest="extensions", nargs="+",
                   help="Video extensions to discover (e.g. --ext .mp4 .mov).")

    # Detector (stage 2)
    p.add_argument("--detector", choices=list(VALID_DETECTORS))
    p.add_argument("--ml-confidence-threshold", type=float)

    p.add_argument("--quiet", action="store_true", help="Reduce logging.")
    p.add_argument("--no-progress", dest="progress", action="store_false",
                   default=True, help="Disable the tqdm progress bar.")


def _config_from_args(args: argparse.Namespace) -> ReefScannerConfig:
    base = (
        ReefScannerConfig.from_yaml(args.config)
        if getattr(args, "config", None)
        else ReefScannerConfig()
    )
    data = base.to_dict()
    data["input_folder"] = args.input_folder
    data["output_folder"] = args.output_folder

    # Only override fields the user actually passed (non-None).
    overridable = [
        "frame_sample_fps", "detect_downscale", "warmup_frames", "min_blob_area",
        "persistence_frames", "bg_subtractor", "detect_shadows",
        "merge_gap_seconds", "min_event_seconds", "pad_seconds",
        "reencode_clips", "ffmpeg_path", "extensions", "detector",
        "ml_confidence_threshold",
    ]
    for key in overridable:
        val = getattr(args, key, None)
        if val is not None:
            data[key] = val
    return ReefScannerConfig.from_dict(data)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reefscanner",
        description="Motion triage for static-camera underwater video (v1).",
    )
    parser.add_argument("--version", action="version",
                        version=f"reefscanner {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser("process", help="Scan a folder of videos.")
    _add_process_args(p_process)

    p_report = sub.add_parser(
        "report", help="Report false-positive rate from a labeled results CSV.")
    p_report.add_argument("output_folder", help="Output folder containing the CSV.")
    p_report.add_argument("--csv", help="Explicit CSV path (overrides default).")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if getattr(args, "quiet", False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.command == "process":
        cfg = _config_from_args(args)
        batch = process_folder(cfg, progress=args.progress)
        print(
            f"\nProcessed {batch.n_videos_processed} video(s); "
            f"{batch.n_events} event(s) emitted."
        )
        print(f"CSV:      {batch.csv_path}")
        print(f"Manifest: {batch.manifest_path}")
        errors = [r for r in batch.results if r.error]
        if errors:
            print(f"\n{len(errors)} video(s) errored:", file=sys.stderr)
            for r in errors:
                print(f"  - {r.video}: {r.error}", file=sys.stderr)
            return 1
        return 0

    if args.command == "report":
        csv_path = (
            Path(args.csv) if args.csv
            else Path(args.output_folder) / ReefScannerConfig().csv_name
        )
        report = fp_report(csv_path)
        print(report.summary())
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
