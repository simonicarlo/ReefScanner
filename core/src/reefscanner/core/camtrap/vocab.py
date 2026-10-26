"""Camtrap DP vocabularies, and how ReefScanner's own terms map onto them.

The enums are copied from the Camtrap DP 1.0.2 table schemas. The mappings
(verdicts, detector classes) are ReefScanner's decisions, recorded in
docs/specs/v3/features/2026-10-26-camtrap-dp-data-model-design.md.
"""

from __future__ import annotations


#: The Camtrap DP version every table and package targets.
CAMTRAP_DP_VERSION = "1.0.2"

CAPTURE_METHODS = ("activityDetection", "timeLapse")
OBSERVATION_LEVELS = ("media", "event")
OBSERVATION_TYPES = ("animal", "human", "vehicle", "blank", "unknown", "unclassified")
CLASSIFICATION_METHODS = ("human", "machine")

# -- human verdicts -------------------------------------------------------------

VERDICT_TP = "TP"
#: A false positive with nothing there at all.
VERDICT_FP = "FP"
#: A false positive where something else was there, optionally named.
VERDICT_FP_OTHER = "FP-other"
VERDICT_UNSURE = "unsure"
VERDICTS = (VERDICT_TP, VERDICT_FP, VERDICT_FP_OTHER, VERDICT_UNSURE)

#: The Camtrap observation type each verdict is recorded as. An unreviewed
#: event has no human observation at all, which is different from ``unsure``.
VERDICT_OBSERVATION_TYPE = {
    VERDICT_TP: "animal",
    VERDICT_FP: "blank",
    VERDICT_FP_OTHER: "animal",
    VERDICT_UNSURE: "unknown",
}

VERDICT_TAG_KEY = "verdict"


def verdict_tag(verdict: str) -> str:
    """The ``observationTags`` entry that keeps a verdict explicit.

    Needed because ``animal`` alone can't tell a TP from an FP-other.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    return f"{VERDICT_TAG_KEY}:{verdict}"


def verdict_from_tags(tags: str | None) -> str | None:
    """Read the verdict back out of pipe-separated ``observationTags``."""
    for tag in (tags or "").split("|"):
        key, _, value = tag.strip().partition(":")
        if key == VERDICT_TAG_KEY and value in VERDICTS:
            return value
    return None


# -- detector classes -------------------------------------------------------------

#: Scientific names for the classes our detectors output. Camtrap DP wants
#: scientific names; SharkTrack's one class is the elasmobranchs (sharks, rays).
DETECTOR_CLASS_TAXA = {
    "elasmobranch": "Elasmobranchii",
}


def taxon_for_class(class_name: str) -> str | None:
    """Scientific name for a detector class, or None if we have no mapping."""
    return DETECTOR_CLASS_TAXA.get(class_name.lower())
