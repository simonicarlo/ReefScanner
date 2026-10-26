"""Write and read Camtrap DP packages: ``datapackage.json`` plus CSV tables.

A package is one folder. The writer puts the metadata and tables in it; the
media files themselves (clips, frames) are placed by whoever produced them, at
the relative ``filePath`` their media rows name.

The column order, field types and constraints come from the vendored Camtrap DP
table schemas (``schemas/<version>/``), so the format has one source of truth.
Before writing, every row is checked against them and against the references
between tables, and all problems are reported together: a package that fails
validation later, in someone else's tool, is much harder to fix than one that
was never written.

Files are written atomically and ``datapackage.json`` last, so a folder with a
``datapackage.json`` in it always holds a complete package.
"""

from __future__ import annotations

import csv
import datetime as _dt
import gzip
import io
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError
from sqlmodel import SQLModel

from .models import Deployment, Detection, Media, Observation, ObservationExtra
from .vocab import CAMTRAP_DP_VERSION

SCHEMA_DIR = Path(__file__).parent / "schemas" / CAMTRAP_DP_VERSION
_BASE_URL = f"https://raw.githubusercontent.com/tdwg/camtrap-dp/{CAMTRAP_DP_VERSION}"
PROFILE_URL = f"{_BASE_URL}/camtrap-dp-profile.json"

#: The standard's three tables, in the order they reference each other.
CAMTRAP_TABLES: dict[str, type[SQLModel]] = {
    "deployments": Deployment,
    "media": Media,
    "observations": Observation,
}

#: ReefScanner's sidecar tables. Their names sit outside Camtrap's reserved
#: three, which keeps the package valid; their schemas are inline.
SIDECAR_SCHEMAS: dict[str, dict[str, Any]] = {
    "reefscanner-observations": {
        "fields": [
            {"name": "observationID", "type": "string",
             "constraints": {"required": True, "unique": True}},
            {"name": "scanID", "type": "string"},
            {"name": "trackID", "type": "string"},
            {"name": "sourceVideo", "type": "string"},
            {"name": "videoStartSeconds", "type": "number", "constraints": {"minimum": 0}},
            {"name": "videoEndSeconds", "type": "number", "constraints": {"minimum": 0}},
            {"name": "peakSeconds", "type": "number", "constraints": {"minimum": 0}},
            {"name": "detectorClass", "type": "string"},
            {"name": "modelName", "type": "string"},
            {"name": "modelVersion", "type": "string"},
            {"name": "detectorBackend", "type": "string"},
            {"name": "detectorConfig", "type": "object"},
        ],
        "primaryKey": ["observationID"],
        "foreignKeys": [{
            "fields": ["observationID"],
            "reference": {"resource": "observations", "fields": ["observationID"]},
        }],
    },
    "reefscanner-detections": {
        "fields": [
            {"name": "observationID", "type": "string", "constraints": {"required": True}},
            {"name": "frameTimestamp", "type": "datetime", "constraints": {"required": True}},
            {"name": "bboxX", "type": "number",
             "constraints": {"required": True, "minimum": 0, "maximum": 1}},
            {"name": "bboxY", "type": "number",
             "constraints": {"required": True, "minimum": 0, "maximum": 1}},
            {"name": "bboxWidth", "type": "number",
             "constraints": {"required": True, "minimum": 1e-15, "maximum": 1}},
            {"name": "bboxHeight", "type": "number",
             "constraints": {"required": True, "minimum": 1e-15, "maximum": 1}},
            {"name": "confidence", "type": "number",
             "constraints": {"required": True, "minimum": 0, "maximum": 1}},
        ],
        "foreignKeys": [{
            "fields": ["observationID"],
            "reference": {"resource": "observations", "fields": ["observationID"]},
        }],
    },
}
SIDECAR_TABLES: dict[str, type[SQLModel]] = {
    "reefscanner-observations": ObservationExtra,
    "reefscanner-detections": Detection,
}

#: Defaults for the package's required ``project`` block (design note).
DEFAULT_PROJECT = {
    "samplingDesign": "targeted",
    "captureMethod": ["activityDetection"],
    "individualAnimals": False,
    "observationLevel": ["media"],
}


class PackageError(ValueError):
    """A package that isn't valid Camtrap DP. ``problems`` lists every issue."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        shown = "\n".join(f"  - {p}" for p in problems[:20])
        more = f"\n  … and {len(problems) - 20} more" if len(problems) > 20 else ""
        super().__init__(f"{len(problems)} problem(s) in the package:\n{shown}{more}")


@dataclass
class Package:
    """Everything in one Camtrap DP package, as table rows plus metadata.

    ``metadata`` is ``datapackage.json`` without ``resources``. When writing it
    must hold ``project.title`` and ``contributors``; ``spatial``, ``temporal``,
    ``taxonomic``, ``created`` and ``profile`` are derived from the rows.
    """

    deployments: list[Deployment] = field(default_factory=list)
    media: list[Media] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    observation_extras: list[ObservationExtra] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def rows(self, table: str) -> list[SQLModel]:
        return {
            "deployments": self.deployments,
            "media": self.media,
            "observations": self.observations,
            "reefscanner-observations": self.observation_extras,
            "reefscanner-detections": self.detections,
        }[table]


# -- schemas ---------------------------------------------------------------------

@lru_cache(maxsize=None)
def table_schema(table: str) -> dict[str, Any]:
    """The Table Schema for a Camtrap or sidecar table."""
    if table in SIDECAR_SCHEMAS:
        return SIDECAR_SCHEMAS[table]
    return json.loads((SCHEMA_DIR / f"{table}-table-schema.json").read_text())


def table_schema_url(table: str) -> str:
    return f"{_BASE_URL}/{table}-table-schema.json"


def field_names(table: str) -> list[str]:
    return [f["name"] for f in table_schema(table)["fields"]]


# -- writing ---------------------------------------------------------------------

def write_package(folder: str | Path, package: Package) -> Path:
    """Validate ``package`` and write it into ``folder``. Returns the descriptor path."""
    folder = Path(folder)
    problems = validate(package)
    if problems:
        raise PackageError(problems)

    folder.mkdir(parents=True, exist_ok=True)
    resources = []
    for table in [*CAMTRAP_TABLES, *SIDECAR_SCHEMAS]:
        rows = package.rows(table)
        if table in SIDECAR_SCHEMAS and not rows:
            continue  # optional, and an empty sidecar says nothing
        path = f"{table}.csv"
        _atomic_write(folder / path, _render_csv(table, rows))
        resource = {
            "name": table,
            "path": path,
            "profile": "tabular-data-resource",
            "format": "csv",
            "mediatype": "text/csv",
            "encoding": "utf-8",
            "schema": (
                table_schema(table) if table in SIDECAR_SCHEMAS
                else table_schema_url(table)
            ),
        }
        resources.append(resource)

    descriptor = {"resources": resources, **_metadata(package)}
    out = folder / "datapackage.json"
    _atomic_write(out, json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n")
    return out


def _metadata(package: Package) -> dict[str, Any]:
    meta = dict(package.metadata)
    meta["profile"] = PROFILE_URL
    meta.setdefault("name", _package_name(package))
    meta.setdefault(
        "created",
        _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    )
    meta["project"] = {**DEFAULT_PROJECT, **meta.get("project", {})}
    meta["spatial"] = _spatial(package.deployments)
    meta["temporal"] = _temporal(package.deployments)
    meta["taxonomic"] = _taxonomic(package.observations, meta.get("taxonomic", []))
    return meta


def _package_name(package: Package) -> str:
    ids = sorted(d.deploymentID for d in package.deployments)
    base = ids[0] if len(ids) == 1 else f"{ids[0]}-and-{len(ids) - 1}-more"
    # Frictionless names: lower-case letters, digits, '-', '_', '.'.
    return re.sub(r"[^a-z0-9._-]+", "-", f"reefscanner-{base}".lower()).strip("-")


def _spatial(deployments: list[Deployment]) -> dict[str, Any]:
    lons = [d.longitude for d in deployments]
    lats = [d.latitude for d in deployments]
    w, e, s, n = min(lons), max(lons), min(lats), max(lats)
    if w == e and s == n:
        return {"type": "Point", "coordinates": [w, s]}
    return {
        "type": "Polygon",
        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
    }


def _temporal(deployments: list[Deployment]) -> dict[str, str]:
    start = min(d.deploymentStart for d in deployments)
    end = max(d.deploymentEnd for d in deployments)
    return {"start": start.date().isoformat(), "end": end.date().isoformat()}


def _taxonomic(
    observations: list[Observation], known: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every scientific name observed, keeping any detail the caller supplied."""
    by_name = {t["scientificName"]: t for t in known}
    names = sorted({o.scientificName for o in observations if o.scientificName})
    return [by_name.get(n, {"scientificName": n}) for n in names]


def _render_csv(table: str, rows: Iterable[SQLModel]) -> str:
    names = field_names(table)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(names)
    for row in rows:
        writer.writerow([_format(getattr(row, n, None)) for n in names])
    return buf.getvalue()


def _format(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, _dt.datetime):
        # The standard's format has whole seconds and a required offset.
        return value.isoformat(timespec="seconds")
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# -- validation ------------------------------------------------------------------

def validate(package: Package) -> list[str]:
    """Every way ``package`` falls short of Camtrap DP. Empty means valid."""
    problems: list[str] = []
    if not package.deployments:
        problems.append("a package needs at least one deployment")

    meta = package.metadata
    if not (meta.get("project") or {}).get("title"):
        problems.append("metadata: project.title is required")
    if not meta.get("contributors"):
        problems.append("metadata: at least one contributor is required")

    for table in [*CAMTRAP_TABLES, *SIDECAR_SCHEMAS]:
        model = {**CAMTRAP_TABLES, **SIDECAR_TABLES}[table]
        for i, row in enumerate(package.rows(table), start=1):
            where = f"{table} row {i}"
            problems += _check_row(table, row, where)
            try:
                model.model_validate(row.model_dump())
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(p) for p in err["loc"])
                    problems.append(f"{where}: {loc}: {err['msg']}")

    for d in package.deployments:
        if d.deploymentStart and d.deploymentEnd and d.deploymentStart > d.deploymentEnd:
            problems.append(f"deployment {d.deploymentID!r}: starts after it ends")
    for o in package.observations:
        if o.observationLevel == "media" and not o.mediaID:
            problems.append(f"observation {o.observationID!r}: media-level needs a mediaID")
        box = [o.bboxX, o.bboxY, o.bboxWidth, o.bboxHeight]
        if any(v is not None for v in box) and any(v is None for v in box):
            problems.append(f"observation {o.observationID!r}: bounding box is partial")

    problems += _check_keys(package)
    return problems


def _check_row(table: str, row: SQLModel, where: str) -> list[str]:
    """Required fields, enums, ranges and timezones, straight from the schema."""
    problems = []
    for spec in table_schema(table)["fields"]:
        name, c = spec["name"], spec.get("constraints", {})
        value = getattr(row, name, None)
        if value is None or value == "":
            if c.get("required"):
                problems.append(f"{where}: {name} is required")
            continue
        if "enum" in c and value not in c["enum"]:
            problems.append(f"{where}: {name}={value!r} is not one of {c['enum']}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in c and value < c["minimum"]:
                problems.append(f"{where}: {name}={value} is below {c['minimum']}")
            if "maximum" in c and value > c["maximum"]:
                problems.append(f"{where}: {name}={value} is above {c['maximum']}")
        if isinstance(value, _dt.datetime) and value.utcoffset() is None:
            problems.append(f"{where}: {name} has no timezone")
    return problems


def _check_keys(package: Package) -> list[str]:
    """Unique primary keys, and every reference pointing at a row that exists."""
    problems = []

    def ids(rows: Iterable[SQLModel], attr: str, table: str) -> set[Any]:
        seen, dupes = set(), set()
        for r in rows:
            key = getattr(r, attr)
            (dupes if key in seen else seen).add(key)
        problems.extend(f"{table}: duplicate {attr} {k!r}" for k in sorted(dupes))
        return seen

    deployments = ids(package.deployments, "deploymentID", "deployments")
    media = ids(package.media, "mediaID", "media")
    observations = ids(package.observations, "observationID", "observations")
    ids(package.observation_extras, "observationID", "reefscanner-observations")

    def refs(
        rows: Iterable[SQLModel], attr: str, known: set[Any], table: str, target: str
    ) -> None:
        for r in rows:
            key = getattr(r, attr)
            if key is not None and key not in known:
                problems.append(f"{table}: {attr} {key!r} is not in {target}")

    refs(package.media, "deploymentID", deployments, "media", "deployments")
    refs(package.observations, "deploymentID", deployments, "observations", "deployments")
    refs(package.observations, "mediaID", media, "observations", "media")
    refs(package.observation_extras, "observationID", observations,
         "reefscanner-observations", "observations")
    refs(package.detections, "observationID", observations,
         "reefscanner-detections", "observations")
    return problems


# -- reading ---------------------------------------------------------------------

def read_package(folder: str | Path) -> Package:
    """Read a package written by ``write_package`` (or any Camtrap DP 1.0.2 one)."""
    folder = Path(folder)
    descriptor_path = folder / "datapackage.json"
    if not descriptor_path.is_file():
        raise PackageError([f"no datapackage.json in {folder}"])
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if descriptor.get("profile") != PROFILE_URL:
        raise PackageError([
            f"unsupported profile {descriptor.get('profile')!r}; "
            f"this reads Camtrap DP {CAMTRAP_DP_VERSION} only"
        ])

    resources = {r["name"]: r for r in descriptor.get("resources", [])}
    package = Package(metadata={k: v for k, v in descriptor.items() if k != "resources"})
    problems: list[str] = []
    for table, model in {**CAMTRAP_TABLES, **SIDECAR_TABLES}.items():
        resource = resources.get(table)
        if resource is None:
            if table in CAMTRAP_TABLES:
                problems.append(f"missing resource {table!r}")
            continue
        package.rows(table).extend(
            _read_table(folder / resource["path"], table, model, problems)
        )
    if problems:
        raise PackageError(problems)
    return package


def _read_table(path: Path, table: str, model, problems: list[str]) -> list[SQLModel]:
    if not path.is_file():
        problems.append(f"{table}: missing file {path.name}")
        return []
    types = {f["name"]: f["type"] for f in table_schema(table)["fields"]}
    opener = gzip.open if path.suffix == ".gz" else open
    rows = []
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        unknown = set(reader.fieldnames or []) - set(types)
        if unknown:
            problems.append(f"{table}: unknown columns {sorted(unknown)}")
            return []
        for i, raw in enumerate(reader, start=1):
            try:
                data = {k: _parse(v, types[k]) for k, v in raw.items()}
                rows.append(model.model_validate(data))
            except (ValueError, ValidationError) as exc:
                problems.append(f"{table} row {i}: {exc}")
    return rows


def _parse(value: str | None, kind: str) -> Any:
    if value is None or value == "":
        return None
    if kind == "number":
        return float(value)
    if kind == "integer":
        return int(value)
    if kind == "boolean":
        if value not in ("true", "false"):
            raise ValueError(f"not a boolean: {value!r}")
        return value == "true"
    if kind == "datetime":
        parsed = _dt.datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError(f"timestamp without a timezone: {value!r}")
        return parsed
    if kind in ("object", "array", "any"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value  # `any` may legitimately be plain text
    return value
