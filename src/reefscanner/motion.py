"""Motion gating (SPEC §3 Step 3).

In v1 this was the source of recall. In v2 (detector-scans-frames) motion is
*demoted*: it's either the recall source when ``detector=none`` (the no-ML path
still works exactly as before), or an optional cheap pre-skip in detector mode
(``motion_prefilter``) that avoids running the detector on dead-static frames.

Because the camera is static, we use background subtraction (MOG2/KNN) ->
foreground mask -> contour detection, filtered by blob size and temporal
persistence. Known failure modes handled here (SPEC §3 implementation notes):
warm-up window, MOG2 shadow detection + morphological open/close, and bbox/score
rescaling from the downscaled detection frame back to original resolution.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .config import ReefScannerConfig
from .events import Candidate, MotionCandidate  # noqa: F401 (alias re-export)
from .videoio import SampledFrame


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
    *not* checkpointed — hence per-video (not mid-video) resumability
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

    def _foreground_mask(self, frame: np.ndarray) -> np.ndarray:
        """Apply the subtractor + clean the mask. Advances the background model."""
        small = self._downscale(frame)
        mask = self._sub.apply(small)
        # MOG2/KNN encode detected shadows as value 127; keep only hard
        # foreground (255) so shadows don't inflate blobs.
        _, fg = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel)
        return fg

    def _largest_blob(self, fg: np.ndarray):
        """Return (area, bbox) of the largest blob clearing the size filter, or None."""
        contours, _ = cv2.findContours(
            fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        best_area = 0.0
        best_box = None
        for c in contours:
            area = cv2.contourArea(c)
            if area >= self.cfg.min_blob_area and area > best_area:
                best_area = area
                best_box = cv2.boundingRect(c)
        return None if best_box is None else (best_area, best_box)

    def _rescale(self, area: float, box) -> tuple[tuple[int, int, int, int], float]:
        inv = 1.0 / self.cfg.detect_downscale if self.cfg.detect_downscale > 0 else 1.0
        x, y, w, h = box
        bbox = (
            int(round(x * inv)),
            int(round(y * inv)),
            int(round(w * inv)),
            int(round(h * inv)),
        )
        return bbox, area * inv * inv  # area scales with the square

    def process(self, sample: SampledFrame) -> Optional[Candidate]:
        """Update the background model and return a motion Candidate, or None.

        Returns None during warm-up, when no blob clears the size filter, or
        before temporal persistence is satisfied.
        """
        fg = self._foreground_mask(sample.frame)

        # During warm-up we still feed the subtractor (above) but never emit.
        if sample.index < self.cfg.warmup_frames:
            self._run_length = 0
            return None

        blob = self._largest_blob(fg)
        if blob is None:
            self._run_length = 0
            return None

        # Temporal persistence: require N consecutive qualifying frames.
        self._run_length += 1
        if self._run_length < self.cfg.persistence_frames:
            return None

        bbox, motion_score = self._rescale(*blob)
        return Candidate(
            sampled_index=sample.index,
            source_frame=sample.source_frame,
            timestamp=sample.timestamp,
            bbox=bbox,
            score=motion_score,
            motion_score=motion_score,
        )

    def has_motion(self, sample: SampledFrame) -> bool:
        """Cheap pre-skip test for detector mode: is anything moving here?

        Recall-safe: returns True during warm-up (when the model is unreliable)
        and ignores the persistence requirement, so we never skip a frame the
        detector might want. Advances the background model.
        """
        fg = self._foreground_mask(sample.frame)
        if sample.index < self.cfg.warmup_frames:
            return True
        return self._largest_blob(fg) is not None
