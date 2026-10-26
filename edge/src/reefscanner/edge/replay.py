"""Replay simulator: the whole agent against recorded footage, then a diff.

The agent plays the files as one camera stream and writes its package. Then the
laptop scan (core's ``find_events``, same detector, same settings) runs over
the same files, and the two sets of events are matched per file by time
overlap. This is the phase 0 gate: no event the laptop scan finds may be
missing from the agent's.

Matching is by overlap rather than one-to-one: the agent detects on more
frames, so it can see an animal through a gap the scan's sparser samples
split into two events.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from reefscanner.core.detectors import Detector, get_detector
from reefscanner.core.events import Event
from reefscanner.core.pipeline import find_events

from .agent import Agent, AgentResult
from .camera import FileReplay
from .config import AgentConfig


@dataclass
class ReplayReport:
    agent: AgentResult
    #: (file, reference event, agent events overlapping it)
    found: list[tuple[str, Event, list[Event]]] = field(default_factory=list)
    #: (file, reference event): the gate requires none.
    missed: list[tuple[str, Event]] = field(default_factory=list)
    #: (file, agent event) with no reference event overlapping it.
    extra: list[tuple[str, Event]] = field(default_factory=list)
    compared: bool = False

    @property
    def passed(self) -> bool:
        return self.compared and not self.missed


def replay(
    files: list[str | Path],
    config: AgentConfig,
    package_dir: str | Path,
    *,
    speed: float = 0.0,
    compare: bool = True,
    detector: Detector | None = None,
) -> ReplayReport:
    detector = detector or get_detector(config.detector)
    d = config.deployment
    source = FileReplay(files, d.camera_timezone, d.camera_clock, speed=speed)
    result = Agent(config, source, package_dir, detector=detector).run()
    report = ReplayReport(agent=result)
    if not compare:
        return report

    reference = {
        info.path.name: find_events(info.path, config.detector, info, detector)
        for info in source.infos
    }
    report.found, report.missed, report.extra = compare_events(reference, by_file(result.events))
    report.compared = True
    return report


def by_file(events: list[Event]) -> dict[str, list[Event]]:
    out: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        out[e.source_video].append(e)
    return out


def compare_events(
    reference: dict[str, list[Event]], agent: dict[str, list[Event]]
) -> tuple[list, list, list]:
    """Match events per file by overlapping time spans."""
    found, missed, extra = [], [], []
    for name in sorted(set(reference) | set(agent)):
        ours = agent.get(name, [])
        hit: set[int] = set()
        for ref in reference.get(name, []):
            matches = [i for i, e in enumerate(ours) if _overlap(ref, e)]
            hit.update(matches)
            if matches:
                found.append((name, ref, [ours[i] for i in matches]))
            else:
                missed.append((name, ref))
        extra += [(name, e) for i, e in enumerate(ours) if i not in hit]
    return found, missed, extra


def _overlap(a: Event, b: Event) -> bool:
    return a.start_seconds <= b.end_seconds and b.start_seconds <= a.end_seconds


def format_report(report: ReplayReport) -> str:
    r = report.agent
    rate = r.seconds / r.elapsed if r.elapsed else 0.0
    lines = [
        f"Agent: {len(r.events)} event(s) from {r.seconds:.0f}s of footage "
        f"in {r.elapsed:.0f}s ({rate:.1f}x real time)",
        f"  frames {r.frames}, detected {r.detected}, dropped {r.dropped}",
        f"  package: {r.package_dir}",
    ]
    if not report.compared:
        return "\n".join(lines)
    n_ref = len(report.found) + len(report.missed)
    lines.append(
        f"Laptop scan: {n_ref} event(s); the agent found {len(report.found)}, "
        f"missed {len(report.missed)}, and has {len(report.extra)} extra"
    )

    def span(e: Event) -> str:
        return f"{e.start_seconds:7.1f}s–{e.end_seconds:7.1f}s  peak {e.peak_ml_confidence or 0:.2f}"

    for name, ref, ours in report.found:
        lines.append(f"  found   {name}  {span(ref)}  ← {', '.join(e.event_id for e in ours)}")
    for name, ref in report.missed:
        lines.append(f"  MISSED  {name}  {span(ref)}")
    for name, e in report.extra:
        lines.append(f"  extra   {name}  {span(e)}  {e.event_id}")
    lines.append("PASS: every laptop-scan event was found" if report.passed
                 else "FAIL: the agent missed laptop-scan events")
    return "\n".join(lines)
