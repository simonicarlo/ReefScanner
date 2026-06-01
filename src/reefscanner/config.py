"""Configuration for the ReefScanner v1 pipeline.

All tunables live here with recall-favoring defaults (SPEC §4). The pipeline
is deliberately motion-only in v1; the ``detector`` field selects the (mostly
stubbed) stage-2 confirmer interface (SPEC §3 Step 4).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# Detector names recognised by the pluggable stage-2 interface (SPEC §3 Step 4).
DETECTOR_NONE = "none"
DETECTOR_GENERIC = "generic"
DETECTOR_MARINE = "marine"
VALID_DETECTORS = (DETECTOR_NONE, DETECTOR_GENERIC, DETECTOR_MARINE)

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

    # --- Step 4: detector / ML stage (pluggable; v1 default = none) --------
    #: none = motion-only (no ML deps); marine = YOLO (SharkTrack / fine-tuned,
    #: the v2 recall source); generic = stock COCO YOLO objectness (experimental).
    detector: str = DETECTOR_NONE
    #: Path/name of detector weights (e.g. a SharkTrack or fine-tuned `.pt`).
    #: Required for detector=marine; generic falls back to a stock COCO model.
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

    def __post_init__(self) -> None:
        self.validate()

    # -- validation ---------------------------------------------------------
    def validate(self) -> None:
        if self.detector not in VALID_DETECTORS:
            raise ValueError(
                f"detector must be one of {VALID_DETECTORS}, got {self.detector!r}"
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
        if self.detector == DETECTOR_MARINE and not (
            self.detector_weights or self.detector_options.get("weights")
        ):
            raise ValueError(
                "detector='marine' requires detector_weights (a SharkTrack / "
                "fine-tuned YOLO .pt path). See docs/model-research.md."
            )
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
