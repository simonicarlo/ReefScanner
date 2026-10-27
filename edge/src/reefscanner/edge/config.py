"""The agent's configuration: one YAML file per deployment.

Four blocks. ``deployment`` and ``project`` say where and for whom the rig is
recording, and fill the package's deployment row and metadata. ``agent`` holds
the buffer and scheduler settings. ``detector`` is a plain
``ReefScannerConfig``, so the agent and the laptop scan read the same detector,
threshold and event settings and their results can be compared.

Every problem is reported at once: the file is filled in by hand before
sealing the housing, which is a bad time to fix one typo per attempt.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from reefscanner.core.config import ReefScannerConfig


class ConfigError(ValueError):
    """An invalid agent config. ``problems`` lists every issue."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid agent config:\n" + "\n".join(f"  - {p}" for p in problems))


@dataclass
class DeploymentConfig:
    """What the deployment row needs, known before the rig goes in."""

    id: str
    latitude: float
    longitude: float
    #: Where the rig is: local time of day matters for the research, so a zone
    #: is required even though the rig's clock runs on UTC.
    camera_timezone: str
    #: What the source's clock holds. A live rig syncs its clock to UTC; a
    #: replayed file follows the camera that recorded it (GoPros: "local").
    camera_clock: str = "utc"
    location_name: str | None = None
    camera_id: str | None = None
    camera_model: str | None = None
    #: Metres; for a BRUV, the rig's water depth.
    camera_depth: float | None = None
    bait_use: bool | None = None
    setup_by: str | None = None
    comments: str | None = None


@dataclass
class AgentSettings:
    """Buffer and scheduler settings."""

    #: Seconds of footage before the first detection kept in every clip.
    pre_roll_seconds: float = 30.0
    #: Seconds after the last detection kept in every clip.
    post_roll_seconds: float = 10.0
    #: Detection rate while nothing is in view.
    idle_fps: float = 2.0
    #: Detection rate during a burst; None means every frame.
    burst_fps: float | None = None
    #: How long a burst lasts after the last detection.
    burst_seconds: float = 5.0
    #: Length of each encoded buffer segment; clip edges snap to these.
    segment_seconds: float = 2.0
    #: Width of the frame handed to the detector (the low-res stream);
    #: 0 hands it the full frame.
    detect_width: int = 640
    #: Where the encoded ring buffer lives (tmpfs on a board). Default: a
    #: hidden folder next to the package.
    buffer_dir: str | None = None


@dataclass
class AgentConfig:
    deployment: DeploymentConfig
    project_title: str
    contributors: list[dict[str, Any]]
    agent: AgentSettings = field(default_factory=AgentSettings)
    detector: ReefScannerConfig = field(default_factory=ReefScannerConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> AgentConfig:
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ConfigError([f"{path}: expected a mapping at the top level"])
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentConfig:
        problems: list[str] = []
        unknown = set(data) - {"deployment", "project", "agent", "detector"}
        if unknown:
            problems.append(f"unknown blocks: {sorted(unknown)}")

        deployment = _build(DeploymentConfig, data.get("deployment"), "deployment", problems)
        agent = _build(AgentSettings, data.get("agent") or {}, "agent", problems)

        project = data.get("project") or {}
        title = project.get("title") if isinstance(project, dict) else None
        if not title:
            problems.append("project.title is required")
        contributors = _contributors(
            project.get("contributors") if isinstance(project, dict) else None, problems
        )

        detector = ReefScannerConfig()
        try:
            detector = ReefScannerConfig.from_dict(data.get("detector") or {})
        except (TypeError, ValueError) as exc:
            problems.append(f"detector: {exc}")

        if deployment is not None:
            problems += _check_deployment(deployment)
        if agent is not None:
            problems += _check_agent(agent)
        if problems:
            raise ConfigError(problems)
        return cls(
            deployment=deployment,
            project_title=title,
            contributors=contributors,
            agent=agent,
            detector=detector,
        )


def _build(kind: type, raw: Any, block: str, problems: list[str]) -> Any:
    if not isinstance(raw, dict):
        problems.append(f"{block}: a mapping is required")
        return None
    names = {f.name for f in dataclasses.fields(kind)}
    required = {
        f.name for f in dataclasses.fields(kind)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    }
    if unknown := set(raw) - names:
        problems.append(f"{block}: unknown keys {sorted(unknown)}")
    if missing := required - set(raw):
        problems.append(f"{block}: missing {sorted(missing)}")
    if unknown or missing:
        return None
    return kind(**raw)


def _contributors(raw: Any, problems: list[str]) -> list[dict[str, Any]]:
    """Names or Camtrap contributor objects; at least one is required."""
    if not raw:
        problems.append("project.contributors needs at least one name")
        return []
    out = []
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, str) and item.strip():
            out.append({"title": item.strip(), "role": "contributor"})
        elif isinstance(item, dict) and item.get("title"):
            out.append(dict(item))
        else:
            problems.append(f"project.contributors: {item!r} has no name (title)")
    return out


def _check_deployment(d: DeploymentConfig) -> list[str]:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    problems = []
    # IDs end up in file names and URL paths (see camtrap.build).
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(d.id)):
        problems.append(
            "deployment.id may only hold letters, digits, '.', '_' and '-'"
        )
    if not isinstance(d.latitude, (int, float)) or not -90 <= d.latitude <= 90:
        problems.append("deployment.latitude must be a number from -90 to 90")
    if not isinstance(d.longitude, (int, float)) or not -180 <= d.longitude <= 180:
        problems.append("deployment.longitude must be a number from -180 to 180")
    try:
        ZoneInfo(str(d.camera_timezone))
    except (ZoneInfoNotFoundError, ValueError):
        problems.append(
            f"deployment.camera_timezone {d.camera_timezone!r} is not an IANA "
            "timezone (e.g. 'Africa/Maputo')"
        )
    if d.camera_clock not in ("local", "utc"):
        problems.append("deployment.camera_clock must be 'local' or 'utc'")
    if d.camera_depth is not None and d.camera_depth < 0:
        problems.append("deployment.camera_depth must be 0 or more")
    return problems


def _check_agent(a: AgentSettings) -> list[str]:
    problems = []
    if a.pre_roll_seconds < 0 or a.post_roll_seconds < 0:
        problems.append("agent: pre- and post-roll must be 0 or more seconds")
    if a.idle_fps <= 0:
        problems.append("agent.idle_fps must be above 0")
    if a.burst_fps is not None and a.burst_fps <= 0:
        problems.append("agent.burst_fps must be above 0, or empty for every frame")
    if a.burst_seconds < 0:
        problems.append("agent.burst_seconds must be 0 or more")
    if a.segment_seconds <= 0:
        problems.append("agent.segment_seconds must be above 0")
    if a.detect_width < 0:
        problems.append("agent.detect_width must be 0 (full frame) or a width")
    return problems
