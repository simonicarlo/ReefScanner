"""Validate a Camtrap DP package the way an outside tool would, offline.

The descriptor is checked against the Camtrap DP profile (JSON Schema) and the
tables against their Table Schemas by Frictionless, from the copies of the
schemas in the repo. Shared by the core package tests and the app's export test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import frictionless
import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT4

from reefscanner.core.camtrap.package import SCHEMA_DIR

FIXTURES = Path(__file__).parent / "fixtures"


def assert_valid_camtrap(folder: Path) -> None:
    """Validate a written package the way an outside tool would, offline."""
    descriptor = json.loads((folder / "datapackage.json").read_text())

    # 1. The descriptor against the Camtrap DP profile. It refers to the
    #    Frictionless data-package profile and to GeoJSON by URL; both are
    #    served here from copies (the schemastore GeoJSON URL just points on
    #    to geojson.org's schema, so one copy answers both).
    profile = json.loads((SCHEMA_DIR / "camtrap-dp-profile.json").read_text())
    base = json.loads((FIXTURES / "frictionless" / "data-package.json").read_text())
    geojson = Resource.from_contents(
        json.loads((FIXTURES / "frictionless" / "geojson.json").read_text())
    )
    registry = Registry().with_resources([
        ("https://specs.frictionlessdata.io/schemas/data-package.json",
         Resource.from_contents(base, default_specification=DRAFT4)),
        ("http://json.schemastore.org/geojson.json", geojson),
        ("https://geojson.org/schema/GeoJSON.json", geojson),
    ])
    jsonschema.Draft4Validator(profile, registry=registry).validate(descriptor)

    # 2. Every table against its Table Schema, with the remote schema URLs
    #    swapped for the local copies.
    local = copy.deepcopy(descriptor)
    local.pop("profile")  # checked above; Frictionless would fetch it
    for resource in local["resources"]:
        if isinstance(resource["schema"], str):
            name = resource["schema"].rsplit("/", 1)[1]
            resource["schema"] = json.loads((SCHEMA_DIR / name).read_text())
    report = frictionless.Package(local, basepath=str(folder)).validate()
    assert report.valid, report.flatten(["rowNumber", "fieldName", "type", "note"])

