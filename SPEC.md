# ReefScanner — v1 Specification

A triage tool that scans long underwater videos from a **static, mounted camera (BRUV-style)** and flags candidate sightings of large marine megafauna (sharks, rays) for human review. It is **recall-oriented**: it should over-flag rather than miss. It is not a classifier — it surfaces “worth a look” moments.

-----

## 1. Environment & constraints

- **Language:** Python (package + CLI).
- **Runs in:** Google Colab (free/Pro GPU). Browser-driven from an iPad.
- **I/O location:** Google Drive (mounted in Colab). Input folder of videos in, results out.
- **Must be resumable:** Colab disconnects after idle/~12h. Processing must checkpoint per-video so a restart skips already-completed videos and does not lose results.
- **Code lives on GitHub; footage and outputs live on Drive.** Do not assume footage is in the repo.

## 2. Input assumptions (CONFIRM / OVERRIDE — these are defaults, not facts)

- Container/codec: `.mp4`, H.264
- Resolution: 1080p
- Source frame rate: ~25–30 fps
- Batch size: unknown — design for “many hours across multiple files”

> Replace these with real values before running; they drive sampling and performance.

## 3. Pipeline

**Step 1 — Discover.** Take an input folder; recursively find video files (configurable extensions).

**Step 2 — Preprocess / optimize.** Decode at a **sampled frame rate** (default **1 fps**, configurable) rather than every frame — this is the main compute saving. Optionally downscale frames for the detection stages (keep original for clip extraction).

**Step 3 — Motion gating (no ML, cheap, runs on every sampled frame).**
Because the camera is static, use background subtraction (OpenCV MOG2 or KNN) → foreground mask → contour detection. Filter candidates by:

- **Size:** area above a min threshold (rejects small foreground baitfish).
- **Temporal persistence:** object present/coherent across N consecutive sampled frames (rejects flickery small-fish noise; favors large slow-moving animals).
  Output: candidate frames with bounding boxes + a motion score (e.g. blob area).

**Step 4 — ML confirmation (runs ONLY on gated candidate frames, so it’s cheap).**
⚠️ **Design note / known gap:** no standard pretrained detector (COCO/YOLO defaults) has “shark” or “ray” classes. Do **not** assume one does. Implement stage 2 as a **pluggable detector interface** with these options, selectable by config:

- `none` — skip ML, use motion only (always works as a fallback).
- `generic` — run a pretrained detector as a coarse “large animal-like object present?” confirmer using objectness/large-object heuristics, not class labels.
- `marine` — load a marine-megafauna model if a suitable one is available (e.g. from FathomNet / a fine-tuned YOLO). Leave a clear hook to drop in a fine-tuned model later.
  Default to `generic`. ML stage only *re-ranks/confirms* motion candidates; motion gating is the source of recall.

**Step 5 — Event aggregation.** Group consecutive candidate frames into **events** (merge if gap between candidates < `merge_gap_seconds`). Drop events shorter than `min_event_seconds`. For each event compute: start, end, duration, peak motion score, peak ML confidence (if any).

**Step 6 — Output (one clip per event).**

- **Clips:** extract one video clip per event using ffmpeg, with `pad_seconds` before/after. Default to stream-copy for speed; re-encode only if needed. Store in the Drive output folder, named by `event_id`.
- **CSV** (`reefscanner_results.csv`), one row per event:
  `event_id, source_video, start_time, end_time, duration_s, motion_score, ml_confidence, clip_path, thumbnail_path, label, species, notes`
  Leave `label`, `species`, `notes` empty — reserved for the future labeling workflow.
- Optionally save a thumbnail (peak frame) per event.

## 4. Configuration (all tunable, sensible recall-favoring defaults)

`frame_sample_fps` (1.0), `detect_downscale` (e.g. 0.5), `min_blob_area`, `persistence_frames`, `merge_gap_seconds`, `min_event_seconds`, `pad_seconds`, `detector` (none|generic|marine), `ml_confidence_threshold`, input extensions, input/output paths.

## 5. CLI

```
reefscanner process <input_folder> --out <output_folder> [--fps 1.0] [--detector generic] [...]
```

Should also be importable as a library and callable from a Colab notebook cell.

## 6. Tech

OpenCV (`cv2`), ffmpeg (clip extraction), numpy, pandas (CSV), tqdm (progress). ML stage: ultralytics/YOLO or torch behind the pluggable interface. Standard `src/reefscanner/` package layout with the detector interface isolated so models can be swapped.

## 7. Resumability (required)

Write a checkpoint/manifest to the output folder (e.g. processed-video list + partial results). On start, skip videos already completed. Append to the CSV incrementally so a disconnect mid-batch keeps finished work.

## 8. Acceptance criteria (v1 “done”)

1. Runs end-to-end on one sample video in Colab from a Drive folder.
1. Produces the CSV and one padded clip per event in the Drive output folder.
1. Motion gating rejects obvious small-baitfish noise while keeping large slow movers.
1. Re-running after interruption skips completed videos.
1. Works with `detector=none` even if no ML model is wired up yet.

## 9. Explicitly out of scope for v1 (future)

Note these so the schema/structure leaves room, but **do not build now:** species classification; individual visual ID / re-identification; periodic stillframe extraction every X minutes; a review UI for labeling clips (TP/FP, species, notes). The CSV’s reserved columns and the pluggable detector are the seams these will plug into later.