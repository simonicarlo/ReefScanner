"""Command-line interface.

    reefscanner process <input_folder> --out <output_folder> [--fps 1.0]
                        [--detector marine] [...]
    reefscanner report  <output_folder>   # false-positive rate
    reefscanner export-onnx [--weights x.pt] [--out x.onnx]
    reefscanner serve   [--port 8000]     # the local service + review UI
    reefscanner desktop                   # the same thing in a native window

``process`` and ``report`` are the headless engine and need no web
dependencies. ``serve`` needs ``pip install reefscanner-app`` and is what the
desktop shell wraps.

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
from .config import VALID_BACKENDS, VALID_DETECTORS, ReefScannerConfig
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

    # Detector (stage 2 / v2 recall source)
    p.add_argument("--detector", choices=list(VALID_DETECTORS),
                   help="marine=YOLO (SharkTrack/fine-tuned, the default), "
                        "generic=stock COCO (experimental).")
    p.add_argument("--backend", dest="detector_backend", choices=list(VALID_BACKENDS),
                   help="onnx = ONNX Runtime (default, no torch); "
                        "ultralytics = PyTorch (needs the ultralytics extra).")
    p.add_argument("--weights", dest="detector_weights",
                   help="Detector model: .onnx for --backend onnx, .pt for "
                        "ultralytics. Default: SharkTrack.")
    p.add_argument("--conf", "--ml-confidence-threshold",
                   dest="ml_confidence_threshold", type=float,
                   help="Detector confidence threshold (recall-first = low, e.g. 0.2).")
    p.add_argument("--target-classes", dest="target_classes", nargs="+",
                   help="Keep only these model classes (e.g. elasmobranch shark ray).")
    p.add_argument("--sahi", dest="use_sahi", action="store_true", default=None,
                   help="SAHI tiled inference (better recall on distant/small animals).")
    p.add_argument("--motion-prefilter", dest="motion_prefilter",
                   action="store_true", default=None,
                   help="In detector mode, skip dead-static frames (cheap pre-skip).")

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
        "detector_backend", "detector_weights", "ml_confidence_threshold", "target_classes",
        "use_sahi", "motion_prefilter",
    ]
    for key in overridable:
        val = getattr(args, key, None)
        if val is not None:
            data[key] = val
    return ReefScannerConfig.from_dict(data)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reefscanner",
        description="Triage static-camera underwater video for marine megafauna.",
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

    p_export = sub.add_parser(
        "export-onnx",
        help="Convert a YOLO .pt checkpoint to ONNX (needs the ultralytics extra).")
    p_export.add_argument("--weights",
                          help="Checkpoint to convert (default: SharkTrack).")
    p_export.add_argument("--out",
                          help="Where to write the .onnx (default: the weights "
                               "cache, where the onnx backend looks for SharkTrack).")
    p_export.add_argument("--imgsz", type=int, default=640,
                          help="Input size in pixels, the long side (default 640).")
    p_export.add_argument("--static", action="store_true",
                          help="Fixed square input, for board runtimes that "
                               "need one. Default: dynamic, matching .pt results.")

    p_serve = sub.add_parser(
        "serve", help="Run the local web service and review UI.")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="Bind address. Defaults to localhost — the app "
                              "has no authentication, so do not expose it.")
    p_serve.add_argument("--port", type=int, default=8000, help="Port (default 8000).")
    p_serve.add_argument("--db", help="SQLite file to use (default: per-user app data).")
    p_serve.add_argument("--reload", action="store_true",
                         help="Auto-reload on code changes (development).")

    p_desktop = sub.add_parser(
        "desktop", help="Open ReefScanner in a native window.")
    p_desktop.add_argument("--db", help="SQLite file to use (default: per-user app data).")
    p_desktop.add_argument("--debug", action="store_true",
                           help="Open with web inspector and verbose logs.")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if getattr(args, "quiet", False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.command == "process":
        try:
            cfg = _config_from_args(args)
            batch = process_folder(cfg, progress=args.progress)
        except (ValueError, ImportError, FileNotFoundError, NotADirectoryError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
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

    if args.command == "serve":
        return _serve(args)

    if args.command == "export-onnx":
        return _export_onnx(args)

    if args.command == "desktop":
        try:
            from reefscanner.desktop.main import run
        except ImportError as exc:
            print(
                f"error: the desktop app is not installed ({exc}).\n"
                "Install it with:  pip install 'reefscanner-app[desktop]'",
                file=sys.stderr,
            )
            return 2

        return run(db_path=args.db, debug=args.debug)

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


def _export_onnx(args: argparse.Namespace) -> int:
    from . import weights

    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print(
            "error: export needs the ultralytics extra.\n"
            "Install it with:  pip install 'reefscanner-core[ultralytics]'",
            file=sys.stderr,
        )
        return 2
    src = args.weights or weights.ensure_sharktrack_weights()
    dest = (
        Path(args.out) if args.out
        else weights.cache_dir() / Path(src).with_suffix(".onnx").name
    )
    print(f"Exported {weights.export_onnx(src, dest, imgsz=args.imgsz, static=args.static)}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    """Run the FastAPI service under uvicorn."""
    try:
        import uvicorn

        from reefscanner.app.main import create_app
    except ImportError as exc:
        print(
            f"error: the service needs extra dependencies ({exc}).\n"
            "Install them with:  pip install reefscanner-app",
            file=sys.stderr,
        )
        return 2

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        # Worth saying out loud: there is no login, and the media endpoints
        # serve files from disk to anyone who can reach the port.
        print(
            f"warning: binding to {args.host} exposes ReefScanner to your "
            "network, and it has no authentication.",
            file=sys.stderr,
        )

    url = f"http://{args.host}:{args.port}"
    print(f"ReefScanner service on {url}  (API docs at {url}/docs)")

    if args.reload:
        # --reload needs an import string, so the DB override travels by env.
        import os

        if args.db:
            os.environ["REEFSCANNER_DB"] = args.db
        uvicorn.run(
            "reefscanner.app.main:create_app",
            factory=True, host=args.host, port=args.port, reload=True,
        )
    else:
        uvicorn.run(create_app(db_path=args.db), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
