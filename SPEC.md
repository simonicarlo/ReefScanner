# ReefScanner — v1 Specification

A triage tool that scans long underwater videos from a **static, mounted camera (BRUV-style)** and flags candidate sightings of large marine megafauna (sharks, rays) for human review. It is **recall-oriented**: it should over-flag rather than miss. It is not a classifier — it surfaces “worth a look” moments.

**v1 is deliberately motion-only (no ML).** The goal of v1 is to cut a human's watch time from hours to minutes by surfacing candidate clips, with a human in the loop on every output. A false positive costs ~10 seconds of attention; a missed animal is the expensive failure — so the design fails toward over-flagging. v1 is also a **labeling-data factory**: every event it emits (clip + peak frame + motion bbox) is a pre-labeled candidate that, once reviewed, becomes training data for a future fine-tuned detector. See §10.

-----

## 1. Environment & constraints

- **Language:** Python (package + CLI).
- **Runs in:** Google Colab (free/Pro GPU). Browser-driven from an iPad.
- **I/O location:** Google Drive (mounted in Colab). Input folder of videos in, results out.
- **Must be resumable:** Colab disconnects after idle/~12h. Processing must checkpoint per-video so a restart skips already-completed videos and does not lose results.
- **Code lives on GitHub; footage and outputs live on Drive.** Do not assume footage is in the repo.

## 2. Input assumptions

Can vary. Best to support various and detect format / framerate automatically.

## 3. Pipeline

**Step 1 — Discover.** Take an input folder; recursively find video files (configurable extensions).

**Step 2 — Preprocess / optimize.** Decode at a **sampled frame rate** (default **1 fps**, configurable) rather than every frame — this is the main compute saving. Optionally downscale frames for the detection stages (keep original for clip extraction).

**Step 3 — Motion gating (no ML, cheap, runs on every sampled frame). This is the core of the tool and the source of recall.**
Because the camera is static, use background subtraction (OpenCV MOG2 or KNN) → foreground mask → contour detection. Filter candidates by:

- **Size:** area above a min threshold (rejects small foreground baitfish).
- **Temporal persistence:** object present/coherent across N consecutive sampled frames (rejects flickery small-fish noise; favors large slow-moving animals).
  Output: candidate frames with bounding boxes + a motion score (e.g. blob area).

**Implementation notes / known failure modes (the static-camera assumption is load-bearing):**

- **Warm-up / burn-in.** Background subtractors need to learn the background before they're reliable; the first frames of every video are otherwise all false positives. Exclude a configurable warm-up window (`warmup_frames`) from detection while still feeding it to the model.
- **Shadow + morphology.** Enable MOG2 shadow detection and apply a morphological open/close to the foreground mask to suppress speckle before contour detection.
- **Expect real-world noise.** A "static" BRUV rig still sways; sediment drifts; caustics (dancing surface light) and bait-attracted fish swarms produce large, persistent foreground. The size/persistence/shadow filters mitigate but won't eliminate these. The honest expectation for v1 is a *false-positive* problem (annoying-but-usable), not a false-negative one — and the FP rate must be **measured on real footage** to judge whether ML (v2) is worth it. See §10.
- **Coordinate scaling.** Detection runs on downscaled frames (Step 2); scale all bboxes/scores back to original resolution before they reach the CSV, thumbnails, and clip extraction.
- **No mid-video resume.** The background model's state is in memory and is not checkpointed. Resumability is per-*video* (§7): an interrupted video restarts from frame 0. This is an accepted tradeoff, not a bug.

**Step 4 — ML confirmation (optional; runs ONLY on gated candidate frames, so it’s cheap). Not built in v1 beyond the interface + `none`.**
⚠️ **Design note / known gap:** no standard pretrained detector (COCO/YOLO defaults) has “shark” or “ray” classes, and underwater footage has severe domain shift. Do **not** assume an off-the-shelf detector helps. An out-of-domain confirmer can only *throw motion candidates away*, which risks recall — the one thing v1 must protect. Implement stage 2 as a **pluggable detector interface** so a real model can drop in later, with these options selectable by config:

- `none` — **default.** Skip ML, use motion only. This is the v1 product; it works with no torch/CUDA dependency.
- `generic` — experimental. Run a pretrained detector as a coarse “large animal-like object present?” confirmer using objectness/large-object heuristics, not class labels. Off by default; expect it to *hurt* recall on underwater footage. Provided only for experimentation.
- `marine` — the real ML path (v2): load a marine-megafauna model fine-tuned on *our own* labeled footage (see §10), or a suitable external model (e.g. FathomNet). This is the clear hook to drop in a fine-tuned model later.

  The ML stage only ever *re-ranks/confirms* motion candidates; **motion gating is and remains the source of recall.**

**Step 5 — Event aggregation.** Group consecutive candidate frames into **events** (merge if gap between candidates < `merge_gap_seconds`). Drop events shorter than `min_event_seconds`. For each event compute: start, end, duration, peak motion score, peak ML confidence (if any).

> Note: v1 aggregates by **time gap only**, not spatial separation. Two animals on screen at once — or one leaving as another enters — will merge into a single event. Acceptable for triage in v1; spatial splitting is a future concern.

**Step 6 — Output (one clip per event).**

- **Clips:** extract one video clip per event using ffmpeg, with `pad_seconds` before/after. Default to stream-copy (`-c copy`) for speed, re-encode switchable via config.
  - ⚠️ **Stream-copy only cuts on keyframes**, so clip boundaries can drift by seconds and a clip may start on a non-keyframe (brief freeze/garble). `pad_seconds` is partly there to absorb this drift. If accurate boundaries matter for a given dataset, switch to re-encode — expect to need it more often than "rarely."
  - Store in the Drive output folder, named by `event_id`.
- **`event_id` must be unique across the whole batch**, not per video (all clips land in one folder). Use a scheme like `{video_stem}_{NNN}` to avoid collisions.
- **CSV** (`reefscanner_results.csv`), one row per event:
  `event_id, source_video, start_seconds, end_seconds, duration_s, start_timestamp, motion_score, ml_confidence, clip_path, thumbnail_path, label, species, notes`
  - `start_seconds`/`end_seconds` are **offsets into the source file** (for seeking). `start_timestamp` is wall-clock derived from video metadata where available, else blank. Including both avoids ambiguity for the downstream labeling workflow.
  - Leave `label`, `species`, `notes` empty — reserved for the future labeling workflow (§9, §10).
  - **Write whole rows per event** (no partial flushes) so a mid-write disconnect can't leave a torn row; the manifest (§7) is the source of truth for "completed", the CSV is append-only.
- Save a thumbnail (peak frame) per event — used both for quick human triage and as a pre-labeled training frame later (§10).

## 4. Configuration (all tunable, sensible recall-favoring defaults)

`frame_sample_fps` (1.0), `detect_downscale` (e.g. 0.5), `warmup_frames`, `min_blob_area`, `persistence_frames`, `detect_shadows` (true), `merge_gap_seconds`, `min_event_seconds`, `pad_seconds`, `reencode_clips` (false = stream-copy), `detector` (none|generic|marine, **default `none`**), `ml_confidence_threshold`, input extensions, input/output paths.

## 5. CLI

```
reefscanner process <input_folder> --out <output_folder> [--fps 1.0] [--detector none] [...]
```

Should also be importable as a library and callable from a Colab notebook cell.

## 6. Tech

OpenCV (`cv2`), ffmpeg (clip extraction), numpy, pandas (CSV), tqdm (progress). ML stage: ultralytics/YOLO or torch behind the pluggable interface — **an optional/extra dependency, not required for v1** (`detector=none` must work without it). Standard `src/reefscanner/` package layout with the detector interface isolated so models can be swapped.

**Pin versions** (especially OpenCV and, when added, ultralytics) for Colab reproducibility — Colab's preinstalled package set drifts.

## 7. Resumability (required)

Write a checkpoint/manifest to the output folder (e.g. processed-video list + partial results). On start, skip videos already completed. Append to the CSV incrementally so a disconnect mid-batch keeps finished work.

- The **manifest is the source of truth** for what's "done" — a video is marked complete only after its clips, thumbnails, and CSV rows are all flushed. A video interrupted mid-processing is *not* marked complete and is reprocessed from frame 0 on restart (no mid-video resume — see §3).
- CSV is append-only and written in whole rows (§6) so a crash can't corrupt earlier results. On restart, reconcile: don't duplicate rows for videos the manifest already marks complete.

## 8. Acceptance criteria (v1 “done”)

1. Runs end-to-end on one sample video in Colab from a Drive folder. *(The sample video lives on Drive, not in the repo — §1. Decide and document which file/path is the canonical smoke test.)*
1. Produces the CSV and one padded clip per event in the Drive output folder.
1. Motion gating rejects obvious small-baitfish noise while keeping large slow movers.
1. Re-running after interruption skips completed videos (per-video; an interrupted video reprocesses from frame 0).
1. Runs with `detector=none` (the v1 default) **without** any ML/torch dependency installed.
1. Reports a **false-positive rate on a real video** (events emitted vs. events a human confirms) — this number is the input to the §10 go/no-go on ML.

## 9. Explicitly out of scope for v1 (future)

Note these so the schema/structure leaves room, but **do not build now:** species classification; individual visual ID / re-identification; periodic stillframe extraction every X minutes; a review UI for labeling clips (TP/FP, species, notes). The CSV’s reserved columns and the pluggable detector are the seams these will plug into later.

## 10. ML roadmap (v2 — earned by v1 data, not assumed)

The decision to add ML is **gated on the v1 false-positive rate measured on real footage** (acceptance criterion 6). If motion-only triage is usable, ML may not be needed at all. If FPs (caustics, rig sway, baitfish swarms) make it tedious, ML earns its place — as a *confirmer/suppressor* on motion candidates, never as the recall source.

**Why off-the-shelf models don't solve this:** COCO/YOLO defaults have no shark/ray classes and suffer severe underwater domain shift. The real path is a model **fine-tuned on our own footage**, dropped in behind the `marine` detector hook (§3, Step 4).

**v1 is the data factory for this.** Each emitted event already ships a clip, a peak-frame thumbnail, and a motion bbox — a *pre-localized* candidate. A human doing normal triage (confirming TP/FP, optionally species) is simultaneously building the training set, for free, as a byproduct of use. The reserved CSV columns (`label`, `species`, `notes`) are where those labels land.

**Data caveats to design the future labeling step around:**

- Clip-level / rough-spatial labels ("something happening around here") are *weak* labels — good for classification and confirmation, weaker for training a precise detector that wants tight boxes. Motion's bboxes + a human's rough spatial hint together get close to detector-grade labels with little manual boxing; the eventual labeling UI should aim to capture tight-ish boxes.
- **Class imbalance:** target animals are rare across hours of footage, so "empty/baitfish" will vastly outnumber "shark/ray." This favors the label-as-you-triage approach (label v1's candidates) over labeling raw video cold, and shapes how much footage must be reviewed before fine-tuning is worthwhile.

**Path:** v1 motion-only → use it, humans label its output → once enough labeled frames exist, fine-tune a detector → drop in via `marine`, which can then suppress motion FPs *and* seed the species classification listed in §9.
