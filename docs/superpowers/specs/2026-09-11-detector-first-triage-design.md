# Detector-first triage: threshold tuning from labels

**Date:** 2026-09-11
**Status:** approved, not yet implemented

## Context

ReefScanner v2 works end to end: scan footage, review events, record a TP/FP/unsure
verdict per event. Two things are now true that weren't when v1 was specified.

**Motion-only triage doesn't work on real footage.** Tested against four real BRUV
dives, the motion gate cannot distinguish a small fish close to the camera from a
large animal far away — monocular video has no depth cue, so a 20cm fish at 1m and
a 2m shark at 10m project the same blob. `min_blob_area` is a proxy for distance
that the data does not support. v1's SPEC anticipated the "missed distant shark"
failure without noticing that its inverse is equally unavoidable.

**The detector does work.** SharkTrack found 7 elasmobranchs across the same four
dives, at confidences from 0.32 to 0.84, and the labels are now piling up with
nothing consuming them.

This spec does three things: removes motion as a recall source, turns the labels
into a confidence-threshold recommendation, and fixes the export images so a
future fine-tune is possible.

## Decisions taken

| Question | Decision |
|---|---|
| Motion-only (`detector=none`) | **Remove completely.** Not deprecated. |
| `MotionGate` itself | **Keep** — still the `motion_prefilter`, and the intended basis for post-detection tracking. |
| ML dependencies | **Standard, not optional.** `torch`/`ultralytics` install with the app; `marine` becomes the default detector. |
| Primary payoff from labels | **Threshold tuning**, not fine-tuning. |
| Export images | **Both** — annotated thumbnail for triage, clean frame for training. |
| Multi-class / species models | **Out of scope.** |

### Why ML becomes a standard dependency

With motion-only gone, an install without `torch` produces an app that cannot
scan anything. Shipping that as the default guarantees a first run that fails —
the same shape of failure as the `dill` bug, which cost a full debugging cycle.
The install grows by roughly 300MB. That is the correct trade for a tool whose
only job requires a detector.

The engine's import stays light regardless: detector construction is lazy, so
`import reefscanner` still costs nothing until a detector is built.

## Part 1 — Remove motion as a recall source

**Delete:** `engine/detectors/none_detector.py`, the `DETECTOR_NONE` constant and
its re-exports, and the `if cfg.detector == DETECTOR_NONE` branch in
`_collect_candidates`.

**Change:** `VALID_DETECTORS` becomes `("marine", "generic")`; `ReefScannerConfig.detector`
defaults to `"marine"`.

**Keep:** `MotionGate` and every config field it reads (`warmup_frames`,
`min_blob_area`, `persistence_frames`, `bg_subtractor`, `detect_shadows`,
`bg_history`, `mog2_var_threshold`, `morph_kernel_size`). These stop being
recall controls and become *prefilter* controls, and the UI must label them that
way — they now only matter when `motion_prefilter` is on.

**Keep:** the `motion_score` CSV column, blank in detector mode. The v1 column
contract is an interchange format and should not churn.

### Test consequences

Most of `test_pipeline.py` currently exercises the pipeline end to end in
motion-only mode: resumability, CSV contract, clip and thumbnail emission, the
progress and cancellation hooks, and the new manifest fingerprint all depend on
it. Those tests must switch to a **stub detector** injected the way
`test_detector.py` already does it, so the suite keeps testing the pipeline
without requiring real model weights or GPU time.

`test_motion.py` tests `MotionGate` directly and stays as-is — the gate survives.

Two tests are deleted outright, because what they assert ceases to exist:
`test_get_detector_none_finds_nothing` and `test_detector_none_imports_no_torch`.

## Part 2 — Threshold analysis

### The idea

A scan run at confidence 0.2 emits every detection above 0.2, and the reviewer
labels them. Raising the threshold afterwards is therefore perfectly simulatable:
the surviving events are known, and so are their verdicts. Precision and
recall-relative-to-this-scan can be computed exactly, with no rescan.

### What cannot be computed

Anything the detector missed *below* 0.2 is invisible. The analysis therefore
reports recall **relative to what this scan found**, never bare "recall", and the
UI must say so. Presenting this as absolute recall would be a lie, and a
recall-oriented tool cannot afford that particular lie.

### Endpoint

`GET /api/jobs/{job_id}/threshold-analysis`

```json
{
  "labeled": 7, "confirmed": 4, "rejected": 3, "undecided": 0, "unscored": 0,
  "reliable": true,
  "scan_threshold": 0.2,
  "recommended": 0.32,
  "recommendation": "Highest threshold that keeps every confirmed animal.",
  "points": [
    {"threshold": 0.2, "kept": 7, "confirmed_kept": 4, "rejected_kept": 3,
     "confirmed_lost": 0, "precision": 0.571}
  ]
}
```

**Sweep points are the distinct confidence values of the job's labeled events**,
not fixed bins. Those are the only thresholds at which the answer changes, so the
result is exact rather than sampled, and the list stays short.

**`unsure` counts as neither confirmed nor rejected.** A verdict a human could not
reach is not evidence either way; it is reported separately as `undecided` so it
cannot silently skew precision.

**Recommendation rule:** the highest threshold at which `confirmed_lost == 0`.
This is the project's stated philosophy expressed as a number — below it you
review junk for nothing, above it you start paying in missed animals, which is
the expensive failure.

**Degenerate case — nothing confirmed.** If every labeled event was rejected, the
rule is vacuous: `confirmed_lost == 0` holds at every threshold, so it would
"recommend" discarding all detections. In that case `recommended` is `null` with
the reason *"No confirmed animals yet — nothing to protect."* A tool must not
answer a question the data cannot answer.

**Events with no confidence.** Events scanned under the old motion-only mode have
`ml_confidence = null` and cannot appear in a confidence sweep. They are excluded
from the analysis and counted in `unscored`, so a job that predates this change
reports honestly rather than appearing to have no labels. A job where every
labeled event is unscored returns `recommended: null` with that reason.

**Insufficient data:** with fewer than 5 scored, labeled events the response still
computes, but sets `"reliable": false` so the UI can caution rather than mislead.
No hard block — a caveat is more useful than a locked door.

### UI

A panel on the run page showing the sweep table, the recommendation, and an
**Apply** button that PATCHes the project's `ml_confidence_threshold`. Because
the manifest is now config-aware, applying it means the next scan genuinely
reruns rather than skipping.

The existing min-confidence slider reads from the same computation, showing
"would keep N · lose M confirmed" as it is dragged.

## Part 3 — Two images per event

The peak frame is decoded **once** and written twice:

- `thumbnails/<event_id>.jpg` — detection box drawn, for triage (unchanged)
- `frames/<event_id>.jpg` — clean, for training

Today the COCO and YOLO exporters reference the thumbnail, which has the box
burned into it in red. A model trained on those would learn the annotation. This
is a latent bug in shipped code, not a new feature.

**Changes:** a `frames_dirname` config field; one frame read serving both writes;
`Event.frame_path` in the database; a `/api/media/frame/{event_id}` route;
exporters preferring `frame_path` and falling back to `thumbnail_path` for events
scanned before this change. The YOLO export starts including the images, since
label files without images are not a dataset.

## Part 4 — Settings UX

`ml_confidence_threshold` moves into the primary settings — in a detector-first
tool it is the most consequential dial, and it is currently buried behind
"Show all settings".

Motion fields render only when `motion_prefilter` is enabled, and are labelled as
prefilter controls. Showing background-subtractor tuning to someone running a
YOLO detector is noise.

## Schema migration

`Event.frame_path` is a new column, and the app has no migration framework —
`create_all()` creates missing tables but never alters existing ones. Dropping the
database would destroy real labels.

This adds a minimal, idempotent startup step: for each mapped table, compare
`PRAGMA table_info` against the model's columns and `ALTER TABLE ADD COLUMN` any
that are missing and nullable. Roughly twenty lines. It deliberately does **not**
handle drops, renames, or type changes — those need Alembic, and this states
plainly that it is a stopgap for adding nullable columns.

## Testing

- Threshold sweep: exact point values, `unsure` excluded from both counts, the
  recommendation rule at boundaries, all-confirmed and all-rejected edge cases,
  a job with no labels, and a job whose events predate confidence scoring.
- `recommended: null` when nothing is confirmed, rather than a threshold that
  would discard every detection.
- `reliable: false` below the label threshold.
- Clean frame written alongside the annotated one, and the exporters preferring it.
- Migration: an old database file gains the column and keeps its rows.
- Pipeline tests pass on a stub detector with no model weights present.

## Out of scope

Multi-class detection (`marine-detect` offers shark/ray/turtle but is AGPL-3.0,
and that licensing decision is not ready to be made). Species classification.
Any actual model training. Motion-based tracking of detected animals — a good
idea, and the reason `MotionGate` is being kept, but a separate piece of work.

## Risks

**Install size.** ~300MB of torch. Accepted: the tool cannot work without it.

**Overfitting to a small sample.** A recommendation from 7 labels is weak
evidence. Mitigated by `reliable: false`, not by hiding the number.

**Recall framing.** If the UI ever says plain "recall", the number becomes
misleading. The wording is a correctness requirement, not copy.
