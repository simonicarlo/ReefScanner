# ReefScanner v1 — Implementation TODO

Tracking progress against `SPEC.md`. v1 is **motion-only (no ML)**, recall-oriented,
resumable, Colab/Drive-friendly.

**Status: v1 complete.** All modules implemented, 16 tests passing, end-to-end
run verified (CLI + library), notebook + README done.

## Package scaffolding
- [x] `src/reefscanner/` package layout
- [x] `pyproject.toml` with pinned core deps + optional `[ml]` / `[dev]` extras
- [x] `requirements.txt` (Colab) with pinned versions

## Core modules
- [x] `config.py` — `ReefScannerConfig` dataclass, recall-favoring defaults, load from YAML/dict (§4)
- [x] `discovery.py` — recursive video discovery by extension (§3 Step 1)
- [x] `videoio.py` — auto-detect fps/resolution/duration/creation-time (§2, §3 Step 2)
- [x] `motion.py` — MOG2/KNN background subtraction, warm-up, morphology, size+persistence filters, bbox rescaling (§3 Step 3)
- [x] `events.py` — group candidate frames into events by time gap, drop short events (§3 Step 5)
- [x] `clips.py` — ffmpeg clip extraction (stream-copy/re-encode) + peak-frame thumbnails (§3 Step 6)
- [x] `results.py` — append-only whole-row CSV writer with reserved label columns (§3, §6)
- [x] `manifest.py` — per-video completion manifest, source of truth for resume (§7)
- [x] `detectors/` — pluggable interface: `none` (default), `generic` (optional), `marine` (v2 hook) (§3 Step 4)
- [x] `pipeline.py` — orchestrates discover → per-video process → aggregate → output, resumable (§3, §7)
- [x] `cli.py` — `reefscanner process <input> --out <output> [...]` (§5)

## Quality / acceptance
- [x] Importable as a library + callable from a Colab notebook cell (§5)
- [x] `detector=none` works with no torch/ultralytics installed (§8.5)
- [x] Tests: synthetic-video end-to-end, motion gating rejects small/keeps large, resume skips completed
- [x] FP-rate reporting helper (events emitted vs. human-confirmed) (§8.6, §10)
- [x] Colab notebook updated with a runnable quickstart cell
- [x] README usage + canonical smoke-test path documented (§8.1)

## v2 — Detector-scans-frames (architecture done; pending real-footage validation)

Decision: motion's size filter can't separate near-fish from far-shark (perspective).
Research (`docs/model-research.md`) → **SharkTrack** (YOLOv8, BRUVS-trained, MIT) is
the pick. Architecture flips to detector-first; motion demotes to optional pre-skip.

- [x] `detection.py` — `Detection(bbox, class_name, confidence)` type
- [x] Unified `Candidate` (motion OR detection) + detector-aware event aggregation (peak class, class set)
- [x] `Detector` interface: `detect(frame) -> [Detection]` (was motion confirmer)
- [x] `detectors/yolo.py` — Ultralytics wrapper (marine=SharkTrack, generic=COCO), optional SAHI tiling, conf + class filtering
- [x] `marine` detector implemented (loads SharkTrack weights via config); `none` still ML-free; `generic` = COCO objectness
- [x] Config: `detector_weights`, `use_sahi` + slice params, `target_classes`, `motion_prefilter`, recall-favoring conf
- [x] Pipeline: branch motion-mode (v1) vs detector-mode; motion optional pre-skip
- [x] CSV: add `detected_class` column (model's class; `species` stays human-reserved)
- [x] CLI flags: `--weights`, `--conf`, `--sahi`, `--target-classes`, `--motion-prefilter`
- [x] Tests: detector-mode end-to-end via stub detector (no ML dep); motion path still green (20 passing)
- [x] Notebook + README: detector-mode quickstart, SharkTrack weights, Colab note

### Still TODO (needs Colab + real footage — can't run YOLO/download weights in sandbox)
- [ ] Validate SharkTrack weights in Colab on real BRUV footage: does it catch the distant shark? (tune conf, SAHI)
- [ ] Measure recall/FP vs the v1 motion baseline on the same clip
- [ ] Whales: no off-the-shelf optical detector — plan a coarse fine-tuned class + triage
- [ ] (Later) fine-tune on our own footage using OzFish negatives + elasmobranch positives

## Notes / decisions
- ffmpeg located via PATH, with optional `imageio-ffmpeg` fallback (Colab has ffmpeg preinstalled).
- No mid-video resume by design (background model state is in-memory) — §3, §7.
- Canonical smoke test path documented in README; real footage lives on Drive, not the repo.
</content>
</invoke>
