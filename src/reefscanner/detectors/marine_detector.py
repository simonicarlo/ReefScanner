"""The ``marine`` detector hook — the real v2 ML path (SPEC §3 Step 4, §10).

This is the clear seam where a marine-megafauna model fine-tuned on *our own*
labeled footage (the data factory of §10) — or a suitable external model such
as FathomNet — drops in later. v1 ships only the hook: it raises with a
pointer rather than pretending to confirm.

When implemented, it must remain a *confirmer/suppressor* over motion
candidates; motion gating stays the source of recall.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..motion import MotionCandidate


class MarineDetector:
    name = "marine"

    def __init__(self, weights: Optional[str] = None, **_options) -> None:
        raise NotImplementedError(
            "detector='marine' is the v2 hook for a fine-tuned marine-megafauna "
            "model and is not implemented in v1. The v1 decision to add ML is "
            "gated on the measured motion-only false-positive rate (SPEC §10). "
            "Use detector='none' for v1."
        )

    def confirm(
        self, frame: np.ndarray, candidate: MotionCandidate
    ) -> Optional[float]:  # pragma: no cover - unreachable in v1
        raise NotImplementedError
