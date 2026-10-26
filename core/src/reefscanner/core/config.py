"""Configuration for the ReefScanner pipeline.

All tunables live here with recall-favoring defaults (SPEC §4). The
``detector`` field selects the pluggable detector that scans every sampled
frame and is the pipeline's recall source (SPEC §3 Step 4).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# Detector names recognised by the pluggable detector interface.
#
# Motion-only recall (the old ``none``) was removed: on real footage the motion
# gate cannot separate a small fish close to the camera from a large animal far
# away, because monocular video carries no depth cue. ``MotionGate`` survives as
# an optional pre-filter, not as the thing that decides what matters.
DETECTOR_GENERIC = "generic"
DETECTOR_MARINE = "marine"
VALID_DETECTORS = (DETECTOR_MARINE, DETECTOR_GENERIC)

# How a detector's model is run. ONNX Runtime is the default everywhere; the
# Ultralytics backend needs the `ultralytics` extra (torch) and is kept for
# SAHI, PyTorch `.pt` checkpoints, and as the reference ONNX is checked against.
BACKEND_ONNX = "onnx"
BACKEND_ULTRALYTICS = "ultralytics"
VALID_BACKENDS = (BACKEND_ONNX, BACKEND_ULTRALYTICS)

# Default video extensions to discover (lower-case, with leading dot).
DEFAULT_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mpg", ".mpeg")


@dataclass
class ReefScannerConfig:
    """Tunable parameters for a processing run.

    Defaults favour recall: the pipeline should over-flag rather than miss a
    large animal (SPEC intro). A false positive costs ~10s of human attention;
    a missed animal is the expensive failure.
    """

    # --- I/O ---------------------------------------------------------------
    input_folder: str | None = None
    output_folder: str | None = None
    #: Video file extensions to discover (case-insensitive), with leading dot.
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS

    # --- Step 2: sampling / downscale -------------------------------------
    #: Decode at this sampled frame rate rather than every frame (main compute
    #: saving). 1 fps is plenty for large, slow megafauna.
    frame_sample_fps: float = 1.0
    #: Downscale factor applied to frames *for detection only*. Clip extraction
    #: always uses the original video, so bboxes are rescaled back (SPEC §3).
    detect_downscale: float = 0.5

    # --- Step 3: motion gating --------------------------------------------
    #: Background-subtractor warm-up: detections in this many initial sampled
    #: frames are discarded (the model is still learning the background).
    warmup_frames: int = 10
    #: Minimum foreground blob area (in *detection-resolution* pixels) to keep.
    #: Rejects small baitfish noise.
    min_blob_area: int = 500
    #: An object must persist across this many consecutive sampled frames to
    #: count (rejects flickery noise; favours large slow movers).
    persistence_frames: int = 2
    #: Background-subtractor algorithm: "MOG2" or "KNN".
    bg_subtractor: str = "MOG2"
    #: Enable shadow detection in the background subtractor (SPEC §3).
    detect_shadows: bool = True
    #: History length (frames) for the background model.
    bg_history: int = 100
    #: MOG2 variance threshold (ignored for KNN).
    mog2_var_threshold: float = 16.0
    #: Kernel size (px) for the morphological open/close that suppresses speckle.
    morph_kernel_size: int = 5

    # --- Step 5: event aggregation ----------------------------------------
    #: Merge consecutive candidate frames into one event if the gap between
    #: them is below this many seconds.
    merge_gap_seconds: float = 3.0
    #: Drop events shorter than this many seconds.
    min_event_seconds: float = 1.0

    # --- Step 6: clip / thumbnail output ----------------------------------
    #: Seconds of padding before/after each event in the extracted clip. Also
    #: absorbs keyframe drift when stream-copying (SPEC §3 Step 6).
    pad_seconds: float = 2.0
    #: Re-encode clips (accurate boundaries) vs. stream-copy (fast, keyframe
    #: drift). Default stream-copy for speed.
    reencode_clips: bool = False
    #: Thumbnail image format extension.
    thumbnail_ext: str = ".jpg"
    #: Optional explicit ffmpeg binary path. If None, located on PATH (then an
    #: imageio-ffmpeg fallback if installed).
    ffmpeg_path: str | None = None

    # --- Step 4: detector / ML stage (pluggable; the recall source) --------
    #: marine = SharkTrack YOLO (the default; trained on real BRUVS footage);
    #: generic = stock COCO YOLO objectness (experimental).
    detector: str = DETECTOR_MARINE
    #: How the model runs: onnx (ONNX Runtime, no torch; the default) or
    #: ultralytics (PyTorch, needs the `ultralytics` extra).
    detector_backend: str = BACKEND_ONNX
    #: Path to detector weights: a `.onnx` export for the onnx backend, a `.pt`
    #: checkpoint for ultralytics. Unset, marine uses SharkTrack (fetched or
    #: exported on first use) and generic a stock COCO model.
    detector_weights: str | None = None
    #: Confidence threshold for the detector. Recall-favoring (low) by default —
    #: a false positive costs ~10s of triage; a missed animal is expensive.
    ml_confidence_threshold: float = 0.2
    #: Keep only these model class names (case-insensitive); None = keep all
    #: (recall-first). e.g. ["elasmobranch", "shark", "ray"].
    target_classes: list[str] | None = None
    #: In detector mode, skip running the detector on frames with no motion
    #: (cheap pre-skip). Off by default = run the detector on every sampled
    #: frame (maximum recall). Recall-safe: never skips during warm-up.
    motion_prefilter: bool = False
    #: SAHI tiled inference — improves recall on distant/small animals (the
    #: missed-distant-shark failure mode). Needs the optional `sahi` package.
    use_sahi: bool = False
    sahi_slice_height: int = 512
    sahi_slice_width: int = 512
    sahi_overlap: float = 0.2
    #: Free-form options forwarded to the active detector implementation.
    detector_options: dict[str, Any] = field(default_factory=dict)

    # --- Output filenames --------------------------------------------------
    csv_name: str = "reefscanner_results.csv"
    manifest_name: str = "reefscanner_manifest.json"
    clips_dirname: str = "clips"
    thumbnails_dirname: str = "thumbnails"
    #: Clean peak frames, with no annotation drawn. These are the images the
    #: annotation exporters reference — a model trained on the annotated
    #: thumbnails would learn the red rectangle.
    frames_dirname: str = "frames"

    def __post_init__(self) -> None:
        self.validate()

    # -- validation ---------------------------------------------------------
    def validate(self) -> None:
        if self.detector not in VALID_DETECTORS:
            raise ValueError(
                f"detector must be one of {VALID_DETECTORS}, got {self.detector!r}"
            )
        if self.detector_backend not in VALID_BACKENDS:
            raise ValueError(
                f"detector_backend must be one of {VALID_BACKENDS}, "
                f"got {self.detector_backend!r}"
            )
        if self.detector_backend == BACKEND_ONNX:
            if self.use_sahi:
                raise ValueError(
                    "use_sahi needs detector_backend='ultralytics' "
                    "(SAHI tiling is not implemented for ONNX yet)"
                )
            if self.detector_weights and not self.detector_weights.endswith(".onnx"):
                raise ValueError(
                    f"detector_backend='onnx' needs an .onnx model, got "
                    f"{self.detector_weights!r}. Convert a .pt checkpoint with "
                    "`reefscanner export-onnx --weights <file.pt>`, or set "
                    "detector_backend='ultralytics'."
                )
        if self.frame_sample_fps <= 0:
            raise ValueError("frame_sample_fps must be > 0")
        if not (0 < self.detect_downscale <= 1.0):
            raise ValueError("detect_downscale must be in (0, 1]")
        if self.bg_subtractor.upper() not in ("MOG2", "KNN"):
            raise ValueError("bg_subtractor must be 'MOG2' or 'KNN'")
        if self.min_blob_area < 0:
            raise ValueError("min_blob_area must be >= 0")
        if self.persistence_frames < 1:
            raise ValueError("persistence_frames must be >= 1")
        if self.warmup_frames < 0:
            raise ValueError("warmup_frames must be >= 0")
        # detector='marine' without an explicit detector_weights path is fine:
        # the marine builder auto-downloads SharkTrack weights (see weights.py).
        # Normalise extensions to lower-case with a leading dot.
        self.extensions = tuple(
            (e if e.startswith(".") else "." + e).lower() for e in self.extensions
        )
        if self.target_classes is not None:
            self.target_classes = list(self.target_classes)

    # -- (de)serialisation --------------------------------------------------
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReefScannerConfig":
        """Build a config from a mapping, ignoring unknown keys gracefully?

        We *reject* unknown keys to catch typos in user-supplied config, which
        is the more helpful behaviour for a tunable-heavy tool.
        """
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        kwargs = dict(data)
        if "extensions" in kwargs and kwargs["extensions"] is not None:
            kwargs["extensions"] = tuple(kwargs["extensions"])
        return cls(**kwargs)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ReefScannerConfig":
        import yaml  # local import: keep PyYAML optional for pure-API use

        with open(path, "r") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["extensions"] = list(self.extensions)
        return d

    # -- resumability -------------------------------------------------------
    #: Fields that only say *where* things go, not *what* gets found. Changing
    #: one of these must not invalidate a completed video.
    _FINGERPRINT_EXCLUDES = frozenset(
        {
            "input_folder",
            "output_folder",
            "extensions",
            "ffmpeg_path",
            "csv_name",
            "manifest_name",
            "clips_dirname",
            "thumbnails_dirname",
            "frames_dirname",
        }
    )

    def scan_fingerprint(self) -> str:
        """A short hash of every setting that changes what a scan produces.

        The manifest stores this alongside each completed video, so re-running
        with a different detector (or threshold, or sample rate) reprocesses
        instead of skipping. Without it, changing a setting and pressing scan
        again appears to do nothing at all — the run finishes instantly with no
        new events, which reads as a broken app rather than a cache hit.
        """
        import hashlib
        import json

        payload = {
            key: value
            for key, value in self.to_dict().items()
            if key not in self._FINGERPRINT_EXCLUDES
        }
        encoded = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()[:12]
