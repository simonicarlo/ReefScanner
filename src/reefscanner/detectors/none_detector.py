"""The default ``none`` detector — pure motion, zero ML deps (SPEC §3 Step 4).

This is the v1 product. It imports nothing beyond numpy and always abstains,
so every motion candidate passes through unscored (``ml_confidence`` blank).
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..motion import MotionCandidate


class NoneDetector:
    name = "none"

    def __init__(self, **_options) -> None:  # accept/ignore detector_options
        pass

    def confirm(
        self, frame: np.ndarray, candidate: MotionCandidate
    ) -> Optional[float]:
        # Abstain: motion-only triage, no ML confidence.
        return None
