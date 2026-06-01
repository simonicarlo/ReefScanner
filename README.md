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
| `--detector` | `none` / `generic` / `marine` | `none` |

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
start_timestamp, motion_score, ml_confidence, clip_path, thumbnail_path,
label, species, notes`. The last three are **reserved for the labeling
workflow** and left blank — fill them during triage.

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
