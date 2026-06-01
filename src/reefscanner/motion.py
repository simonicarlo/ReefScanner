"""Step 3 — Motion gating (SPEC §3 Step 3).

The core of v1 and the source of recall. Because the camera is static, we use
background subtraction (MOG2/KNN) -> foreground mask -> contour detection,
filtered by blob size and temporal persistence.

Known failure modes handled here (SPEC §3 implementation notes):
  * warm-up / burn-in window excluded from detection,
  * MOG2 shadow detection + morphological open/close to suppress speckle,
  * detection runs on downscaled frames; all bboxes/scores are scaled back to
    original resolution before leaving this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .config import ReefScannerConfig
from .videoio import SampledFrame


@dataclass
class MotionCandidate:
    """A motion detection on a single sampled frame, in ORIGINAL coordinates."""

    sampled_index: int
    source_frame: int
    timestamp: float
    #: Bounding box (x, y, w, h) in original-resolution pixels.
    bbox: tuple[int, int, int, int]
    #: Motion score = largest blob area, in original-resolution pixels.
    motion_score: float


def _make_subtractor(cfg: ReefScannerConfig):
    if cfg.bg_subtractor.upper() == "KNN":
        return cv2.createBackgroundSubtractorKNN(
            history=cfg.bg_history, detectShadows=cfg.detect_shadows
        )
    return cv2.createBackgroundSubtractorMOG2(
        history=cfg.bg_history,
        varThreshold=cfg.mog2_var_threshold,
        detectShadows=cfg.detect_shadows,
    )


class MotionGate:
    """Stateful background-subtraction motion gate for a single video.

    State (background model, persistence run-length) lives in memory and is
    *not* checkpointed — hence v1's per-video (not mid-video) resumability
    (SPEC §3, §7). Construct a fresh gate per video.
    """

    def __init__(self, cfg: ReefScannerConfig):
        self.cfg = cfg
        self._sub = _make_subtractor(cfg)
        k = max(1, cfg.morph_kernel_size)
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        #: Consecutive sampled frames (so far) with a qualifying blob.
        self._run_length = 0

    def _downscale(self, frame: np.ndarray) -> np.ndarray:
        s = self.cfg.detect_downscale
        if s >= 1.0:
            return frame
        return cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)

    def process(self, sample: SampledFrame) -> Optional[MotionCandidate]:
        """Update the background model and return a candidate, or None.

        Returns None during warm-up, when no blob clears the size filter, or
        before temporal persistence is satisfied.
        """
        cfg = self.cfg
        small = self._downscale(sample.frame)

        mask = self._sub.apply(small)
        # MOG2/KNN encode detected shadows as value 127; keep only hard
        # foreground (255) so shadows don't inflate blobs.
        _, fg = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)

        # Morphological open (remove speckle) then close (fill the blob).
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel)

        # During warm-up we still feed the subtractor (above) but never emit.
        if sample.index < cfg.warmup_frames:
            self._run_length = 0
            return None

        contours, _ = cv2.findContours(
            fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Largest blob clearing the (downscaled) size threshold.
        best_area = 0.0
        best_box: Optional[tuple[int, int, int, int]] = None
        for c in contours:
            area = cv2.contourArea(c)
            if area >= cfg.min_blob_area and area > best_area:
                best_area = area
                best_box = cv2.boundingRect(c)

        if best_box is None:
            self._run_length = 0
            return None

        # Temporal persistence: require N consecutive qualifying frames.
        self._run_length += 1
        if self._run_length < cfg.persistence_frames:
            return None

        # Scale bbox + area back to original resolution (SPEC §3).
        inv = 1.0 / cfg.detect_downscale if cfg.detect_downscale > 0 else 1.0
        x, y, w, h = best_box
        bbox = (
            int(round(x * inv)),
            int(round(y * inv)),
            int(round(w * inv)),
            int(round(h * inv)),
        )
        motion_score = best_area * inv * inv  # area scales with the square

        return MotionCandidate(
            sampled_index=sample.index,
            source_frame=sample.source_frame,
            timestamp=sample.timestamp,
            bbox=bbox,
            motion_score=motion_score,
        )
