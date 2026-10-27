"""``reefscanner-edge``: run the agent, or replay footage through it.

    reefscanner-edge run    --config rig.yaml --out PKG [--camera 0]
    reefscanner-edge replay --config rig.yaml --out PKG [--speed 0] VIDEO...

``run`` records from a camera until interrupted (Ctrl-C, or SIGTERM from
systemd), then closes the open event and finishes the package. ``replay``
plays recorded files as the camera and checks the result against a laptop
scan; it exits 1 if the agent missed an event the scan found.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from .config import AgentConfig, ConfigError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reefscanner-edge", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="record from a camera")
    run.add_argument("--camera", default="0", help="OpenCV device index or URL (default 0)")
    run.add_argument("--fps", type=float, default=None, help="override the camera's frame rate")

    rep = sub.add_parser("replay", help="play recorded footage through the agent")
    rep.add_argument("videos", nargs="+", type=Path, help="one deployment's files, in order")
    rep.add_argument("--speed", type=float, default=0.0,
                     help="1 = real time, 0 = as fast as detection allows (default)")
    rep.add_argument("--no-compare", action="store_true", help="skip the laptop-scan diff")

    for p in (run, rep):
        p.add_argument("--config", required=True, type=Path, help="agent config (YAML)")
        p.add_argument("--out", required=True, type=Path, help="package folder to write")
        p.add_argument("--detect-width", type=int, default=None,
                       help="override agent.detect_width (0 = full frame)")
        p.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        config = AgentConfig.from_yaml(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.detect_width is not None:
        if args.detect_width < 0:
            print("--detect-width must be 0 or more", file=sys.stderr)
            return 2
        config.agent.detect_width = args.detect_width

    if args.command == "replay":
        return _replay(args, config)
    return _run(args, config)


def _replay(args: argparse.Namespace, config: AgentConfig) -> int:
    from .replay import format_report, replay

    missing = [str(v) for v in args.videos if not v.is_file()]
    if missing:
        print(f"not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    if args.speed < 0:
        print("--speed must be 0 or more", file=sys.stderr)
        return 2
    report = replay(args.videos, config, args.out, speed=args.speed, compare=not args.no_compare)
    print(format_report(report))
    return 0 if report.passed or not report.compared else 1


def _run(args: argparse.Namespace, config: AgentConfig) -> int:
    from .agent import Agent
    from .camera import Webcam

    device: int | str = int(args.camera) if args.camera.isdigit() else args.camera
    source = Webcam(device, config.deployment.camera_timezone, fps=args.fps)
    agent = Agent(config, source, args.out)

    def stop(signum: int, _frame: object) -> None:
        logging.getLogger("reefscanner.edge").info("stopping (signal %s)", signum)
        agent.stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    result = agent.run()
    print(f"{len(result.events)} event(s) in {result.seconds:.0f}s; "
          f"dropped {result.dropped} frame(s); package: {result.package_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
