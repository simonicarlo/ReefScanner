"""Pluggable frame-scanning detector interface (v2, SPEC §3 Step 4).

In v2 the detector is the source of recall: it scans each sampled frame and
returns the animals it finds (``detect(frame) -> list[Detection]``), localising
*and* classifying. Motion is no longer the gate.

Implementations must be import-safe even when their heavy ML dependencies are
missing; defer such imports to ``__init__`` so that ``detector=none`` never
imports torch/ultralytics (SPEC §8.5).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from ..detection import Detection


@runtime_checkable
class Detector(Protocol):
    name: str
    #: Class labels this detector can output (for documentation / filtering).
    class_names: list[str]

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Return all detections in a single ORIGINAL-resolution frame."""
        ...
