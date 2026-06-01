# ReefScanner

Recall-oriented **motion triage** for long underwater videos from a static,
mounted camera (BRUV-style). ReefScanner scans hours of footage and flags
candidate sightings of large marine megafauna (sharks, rays) for human review —
turning hours of watching into minutes.

> **v1 is deliberately motion-only (no ML).** It over-flags rather than misses:
> a false positive costs ~10 seconds of attention, a missed animal is the
> expensive failure. Every event it emits (clip + peak frame + motion bbox) is a
> pre-labeled candidate that becomes training data for a future fine-tuned
> detector. See [`SPEC.md`](SPEC.md).

## How it works

```
Discover videos → sample frames (1 fps) → motion gating (background
subtraction + size/persistence filters) → [optional ML confirm] →
aggregate into events → one padded clip + thumbnail + CSV row per event
```

Motion gating is the source of recall. The ML stage (§3 Step 4) is a pluggable
*confirmer* that is **off by default** (`detector=none`) and needs no
torch/CUDA.

## Install

```bash
pip install git+https://github.com/simonicarlo/reefscanner.git
# or, from a clone:
pip install -e .
```

Requires Python ≥ 3.9 and **ffmpeg** for clip extraction (preinstalled on
Colab; otherwise `apt install ffmpeg`, or `pip install imageio-ffmpeg` for a
bundled fallback). The v1 default (`detector=none`) needs **no** ML
dependencies.

## Usage

### CLI

```bash
reefscanner process <input_folder> --out <output_folder> [options]
```

Common options (all have recall-favoring defaults — see `reefscanner process -h`):

| Flag | Meaning | Default |
|------|---------|---------|
| `--fps` | Sampled decode frame rate | `1.0` |
| `--detect-downscale` | Downscale factor for detection | `0.5` |
| `--warmup-frames` | Background-model burn-in to skip | `10` |
| `--min-blob-area` | Min foreground blob area (reject baitfish) | `500` |
| `--persistence-frames` | Frames a blob must persist | `2` |
| `--merge-gap-seconds` | Merge candidates closer than this | `3.0` |
| `--min-event-seconds` | Drop events shorter than this | `1.0` |
| `--pad-seconds` | Padding before/after each clip | `2.0` |
| `--reencode` | Re-encode clips (accurate cuts) vs. stream-copy | off |
| `--detector` | `none` / `marine` / `generic` | `none` |
| `--weights` | Detector weights `.pt` (required for `marine`) | — |
| `--conf` | Detector confidence threshold (recall-first = low) | `0.2` |
| `--target-classes` | Keep only these model classes (e.g. `elasmobranch shark ray`) | all |
| `--sahi` | SAHI tiled inference (better recall on distant/small animals) | off |
| `--motion-prefilter` | In detector mode, skip dead-static frames | off |

Report the false-positive rate after a human fills the `label` column with
`TP`/`FP` (acceptance criterion 6, the v2 go/no-go):

```bash
reefscanner report <output_folder>
```

### Library / Colab

```python
from reefscanner import ReefScannerConfig, process_folder, fp_report

cfg = ReefScannerConfig(
    input_folder="/content/drive/MyDrive/ReefScanner/input",
    output_folder="/content/drive/MyDrive/ReefScanner/output",
    frame_sample_fps=1.0,
    detector="none",
)
batch = process_folder(cfg)
print(batch.n_events, "events ->", batch.csv_path)
```

The [`ReefScanner.ipynb`](ReefScanner.ipynb) notebook
([open in Colab](https://colab.research.google.com/github/simonicarlo/ReefScanner/blob/main/ReefScanner.ipynb))
drives the whole pipeline stage-by-stage from Google Drive.

## Detection modes

ReefScanner has two recall strategies, chosen by `detector`:

- **`none` (v1, default) — motion-only.** Background subtraction + size/persistence
  gating is the recall source. No ML dependencies. Cheap and robust, but its size
  filter can't separate a *near small fish* from a *far large shark* (in pixels
  they're the same), so it over-flags close fish and can miss distant animals.

- **`marine` (v2) — detector scans frames.** A YOLO model runs on every sampled
  frame, localizing *and* classifying animals — so a distant shark is found by
  appearance, not motion size. Motion demotes to an optional cheap pre-skip
  (`--motion-prefilter`). This is the recommended path for separating megafauna
  from daytime fish.

  ```bash
  reefscanner process <in> --out <out> \
      --detector marine --weights /path/to/sharktrack.pt \
      --conf 0.2 --sahi --target-classes elasmobranch
  ```

  Recommended weights: **SharkTrack** (YOLOv8, single `elasmobranch` class,
  trained on real BRUVS, MIT-licensed) — see
  [`docs/model-research.md`](docs/model-research.md) for the model evaluation and
  why it beats off-the-shelf/aquarium models. Any Ultralytics-compatible `.pt`
  (e.g. a model fine-tuned on your own footage) drops in via `--weights`.
  `--sahi` enables tiled inference, which markedly improves recall on
  *distant/small* animals.

- **`generic` — experimental.** Stock COCO YOLO as a coarse objectness proposer.
  COCO has no shark/ray classes and underwater domain shift is severe; expect it
  to *hurt* recall. For experimentation only.

> **Licensing:** `detector=none` is dependency-free. `marine`/`generic` need the
> `ml` extra (`pip install 'reefscanner[ml]'`), which pulls in **Ultralytics
> YOLO (AGPL-3.0)** — a copyleft license with a network clause. Fine for internal
> research; if you ever distribute or host this as a service, read
> [`docs/model-research.md`](docs/model-research.md) first. SharkTrack's own code
> is MIT.

## Output

All outputs land in `<output_folder>`:

```
output/
├── reefscanner_results.csv     # one row per event (see columns below)
├── reefscanner_manifest.json   # resume checkpoint (source of truth for "done")
├── clips/        <event_id>.<ext>   # one padded clip per event
└── thumbnails/   <event_id>.jpg     # peak frame with the motion bbox drawn
```

CSV columns:
`event_id, source_video, start_seconds, end_seconds, duration_s,
start_timestamp, motion_score, ml_confidence, detected_class, clip_path,
thumbnail_path, label, species, notes`. `detected_class` is the *model's*
predicted class (detector mode; blank for motion-only). The last three
(`label`, `species`, `notes`) are **reserved for the human labeling workflow**
and left blank — fill them during triage.

## Resumability

Colab disconnects after idle/~12h. ReefScanner checkpoints **per video**: the
manifest is the source of truth for what's complete, and a video is marked done
only after its clips, thumbnails, and CSV rows are all flushed. Re-running skips
completed videos. An interrupted video restarts from frame 0 (no mid-video
resume — the background model's state is in memory, by design).

## Canonical smoke test

Acceptance criterion 1 asks for a documented canonical smoke-test file. Real
footage lives on Drive, not in this repo (§1), so the canonical end-to-end
smoke test is:

- **Input video:** `MyDrive/ReefScanner/smoke/smoke_sample.mp4` (place one short
  BRUV clip here on your Drive).
- **Run:**
  ```bash
  reefscanner process /content/drive/MyDrive/ReefScanner/smoke \
      --out /content/drive/MyDrive/ReefScanner/smoke_out --fps 1
  ```
- **Pass condition:** the run completes, writes `reefscanner_results.csv`, and
  produces at least one clip + thumbnail under `smoke_out/`.

For CI / offline development the test suite fabricates synthetic BRUV videos
(no real footage needed):

```bash
pip install -e '.[dev]'
pytest
```

## Roadmap (v2 — earned by v1 data)

Adding ML is **gated on the v1 false-positive rate measured on real footage**.
If motion-only triage is usable, ML may not be needed. If FPs (caustics, rig
sway, baitfish swarms) make it tedious, a detector **fine-tuned on our own
labeled footage** drops in behind the `marine` hook as a confirmer/suppressor —
never as the recall source. See [`SPEC.md`](SPEC.md) §10.
