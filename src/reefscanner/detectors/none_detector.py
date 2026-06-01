"""The ``none`` detector — no ML; the pipeline uses motion-only mode (SPEC §8.5).

This is the v1 product path. It imports nothing beyond numpy and finds nothing,
which signals the pipeline to run the motion gate as the recall source. Selecting
it guarantees no torch/ultralytics import.
"""

from __future__ import annotations

import numpy as np

from ..detection import Detection


class NoneDetector:
    name = "none"
    class_names: list[str] = []

    def __init__(self, **_options) -> None:
        pass

    def detect(self, frame: np.ndarray) -> list[Detection]:
        # No ML: motion gating is the recall source in this mode.
        return []
