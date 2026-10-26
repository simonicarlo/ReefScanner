"""Camtrap DP: the one data format from the rig to the field app.

``models`` defines the tables (shared by the edge agent and the field app),
``vocab`` the standard's vocabularies and how ReefScanner's verdicts and
detector classes map onto them.
"""

from __future__ import annotations

from .models import Deployment, Detection, Media, Observation, ObservationExtra, TZDateTime
from .vocab import (
    CAMTRAP_DP_VERSION,
    VERDICT_FP,
    VERDICT_FP_OTHER,
    VERDICT_OBSERVATION_TYPE,
    VERDICT_TP,
    VERDICT_UNSURE,
    VERDICTS,
    taxon_for_class,
    verdict_from_tags,
    verdict_tag,
)

__all__ = [
    "CAMTRAP_DP_VERSION",
    "Deployment",
    "Detection",
    "Media",
    "Observation",
    "ObservationExtra",
    "TZDateTime",
    "VERDICTS",
    "VERDICT_FP",
    "VERDICT_FP_OTHER",
    "VERDICT_OBSERVATION_TYPE",
    "VERDICT_TP",
    "VERDICT_UNSURE",
    "taxon_for_class",
    "verdict_from_tags",
    "verdict_tag",
]
