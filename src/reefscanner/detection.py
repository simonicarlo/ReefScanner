"""Detection type for the stage-2 detector interface (v2, SPEC §3 Step 4).

A ``Detection`` is one object a detector found in a single frame, in
ORIGINAL-resolution coordinates. This is what a frame-scanning detector returns
(``Detector.detect(frame) -> list[Detection]``), replacing v1's motion-confirmer
contract now that detection — not motion — is the source of recall.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Detection:
    #: Bounding box (x, y, w, h) in original-resolution pixels.
    bbox: tuple[int, int, int, int]
    #: Model class label (e.g. "elasmobranch", "shark", "ray").
    class_name: str
    #: Detection confidence in [0, 1].
    confidence: float
