"""Pluggable stage-2 detector interface (SPEC §3 Step 4).

The ML stage only ever *re-ranks/confirms* motion candidates — motion gating
is and remains the source of recall. A detector receives the original-
resolution frame and the motion bbox and returns a confidence in [0, 1], or
None if it abstains (treated as "keep, unscored").
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import numpy as np

from ..motion import MotionCandidate


@runtime_checkable
class Detector(Protocol):
    """Confirmer/suppressor over motion candidates.

    Implementations must be import-safe even when their heavy ML dependencies
    are missing; defer such imports to ``__init__`` so that ``detector=none``
    never imports torch/ultralytics (SPEC §8.5).
    """

    name: str

    def confirm(
        self, frame: np.ndarray, candidate: MotionCandidate
    ) -> Optional[float]:
        """Return a confidence in [0, 1] for the candidate, or None to abstain."""
        ...
