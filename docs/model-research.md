# ReefScanner — Pretrained Model Research (v2 detector)

Research date: 2026-06. Goal: find a pretrained detector (or the most realistic
path to one) for flagging large marine megafauna — **sharks, rays, whales** — in
long **static BRUV-style** underwater video, for the "detector scans frames"
architecture (recall-oriented, human-in-the-loop triage).

Method: 5 parallel web-research agents (model zoos; elasmobranch-specific;
generic fish recall engines; BRUV tooling; cetacean + fine-tuning path),
primary-source-verified where possible. (HuggingFace blocks automated fetch, so
some HF model-card numbers are search-snippet level — flagged below.)

## TL;DR

- **Winner: SharkTrack** — a YOLOv8 detector purpose-built for BRUVS, single
  `elasmobranch` (shark+ray) class, **MIT-licensed, ships runnable weights**,
  generalizes to unseen sites. It is essentially our exact tool.
- **Its published failure modes are *our* two hard problems, verbatim:** the
  paper states it *"confused reef fish (false positives) and missed distant
  elasmobranchs, with performance degrading in turbid water."* So even the SOTA
  BRUV model struggles here — this calibrates expectations: run it recall-first
  (low confidence), add small-object tiling (SAHI), keep the human in the loop,
  and fine-tune on our footage.
- **No off-the-shelf underwater optical WHALE detector exists.** Cetacean ML is
  almost all acoustic or aerial/drone. Whales will need fine-tuning + triage.
- **Replicating the "Underwater-Animal-Detection" aquarium model is *not* worth
  it** — SharkTrack is strictly better (right domain, MIT, ships weights).
- **License watch:** SharkTrack and MegaFishDetector code are **MIT** (clean).
  But raw Ultralytics YOLO and Orange marine-detect are **AGPL-3.0** (copyleft +
  network clause) — fine for internal/research use, a problem if we ever host it
  as a public service without an enterprise license.

## Ranked candidates

### 1. SharkTrack — PRIMARY ✅
- **Classes:** single `elasmobranch` (sharks **and** rays); species assigned by a
  human in a fast review step. No whales, no teleosts.
- **Arch:** YOLOv8 (Ultralytics) + multi-object tracking → ssMaxN. Ingests `.mp4`
  folders; has a `--peek` mode that extracts only frames with detections.
- **Domain:** REAL BRUVS — 6,862 training images / 77 deployments / 25 locations;
  evaluated on 207 h of out-of-sample BRUVS (Red Sea, Caribbean, Maldives).
- **Weights/License:** open, **MIT**; weights on GitHub Releases + Zenodo.
- **Metrics:** 89% *MaxN-counting* accuracy (NOT per-frame recall — verify
  distant-shark recall ourselves), ~95% reduction in human review time.
- **Fit:** strongest possible — same domain, same task framing, open weights,
  drop-in. Caveats = our exact hard cases (distant misses, reef-fish FPs).
- Sources: https://github.com/filippovarini/sharktrack ·
  https://arxiv.org/abs/2407.20623 · https://zenodo.org/records/15625845

### 2. marine-detect (Orange) — SECONDARY (multi-class, AGPL)
- **Classes:** `shark`, `ray`, `turtle` (separate FishInv model adds fish+inverts).
- **Arch:** YOLOv8, underwater wild footage (~8,130 images).
- **Metrics:** shark mAP50 ≈ 0.74, ray ≈ 0.86 (no recall reported).
- **License:** **AGPL-3.0** (verified from repo LICENSE).
- **Fit:** good multi-class alternative / second opinion; gives a `turtle` class
  for free. AGPL is the catch. Source: https://github.com/Orange-OpenSource/marine-detect

### 3. MegaFishDetector (warplab) — RECALL ENGINE / BACKBONE
- **Classes:** single generic `fish` (fires on sharks as "fish", can't separate
  megafauna from reef fish). **Arch:** YOLOv5, color, up to 1280px. **MIT** code.
- **Domain:** marine mix *including BRUVS (OzFish)*; ~210k train images.
- **Fit:** good high-recall "is there an animal here?" pre-filter or fine-tuning
  backbone; pair with a classifier. Source: https://github.com/warplab/megafishdetector

### 4. Shark Detector / sharkDetectoR (sharkPulse) — SPECIES ID (later stage)
- Sharks-only fine-grained classifier (~69 species), TensorFlow, weights on
  Kaggle (~4 GB), license unstated (verify). Base training = citizen-science/web
  photos (BRUV domain gap). Use for *species ID after flagging*, not recall.
  Source: https://github.com/sharkPulse/Shark-Detector

### Datasets for fine-tuning / evaluation
- **OzFish** (open-AIMS) — BRUVS, class-agnostic fish boxes, **CC BY 3.0**.
  Bony fish only (no sharks) → use as **fish negatives** to suppress daytime-fish
  FPs. https://github.com/open-AIMS/ozfish
- **SharkTrack training set** (Roboflow) — elasmobranch positives in-domain.
- **Roboflow "Aquarium"** — has shark/stingray but aquarium domain; **CC BY**;
  smoke-test only, do not train for BRUV. https://public.roboflow.com/object-detection/aquarium
- **fish-datasets index** (licensed dataset map): https://github.com/filippovarini/fish-datasets

### Ruled out (wrong domain / no weights)
- FathomNet (megalodon class-agnostic; MBARI-315k; benthic) — deep-sea ROV domain.
- VIAME / NOAA bundles (HabCam scallops, MOUSS pollock, grayscale fish) — survey
  gear domain, heavyweight runtime.
- NOAA `*-fish-grayscale` (akridge/NMFS-OSI) — grayscale + 416px + deep survey.
- Villon 2024, FishID platform — good methods, **no released weights**.
- eLasmobranch dataset — out-of-water classification, no boxes.

## Recommended path

1. **Adopt SharkTrack's YOLOv8 weights as the `marine` detector** inside our
   existing pipeline (which already has discovery, sampling, resumability,
   manifest, CSV, clip + thumbnail extraction — things SharkTrack's CLI lacks).
   Run recall-first: **low confidence threshold**, keep everything for triage.
2. **Add SAHI tiled inference** for distant/small sharks (the published +38%
   small-object mAP fix; SAHI is MIT). This directly targets the missed-distant
   case from our first test run.
3. **Use motion only as an optional cheap pre-skip** of dead-static frames — no
   longer the recall source.
4. **Whales:** no off-the-shelf option → coarse fine-tuned class later +
   human triage; treat as the weakest leg.
5. **Fine-tune on our own footage** over time (the v1 data-factory plan), using
   OzFish as fish-negatives and SharkTrack/Roboflow elasmobranch positives.
6. **License:** SharkTrack (MIT) keeps us clean; if we later mix in Ultralytics
   training or marine-detect, we inherit **AGPL-3.0** — fine for research, decide
   before any hosted/distributed product.

## Testing constraint
This dev sandbox can't reach huggingface.co / model-weight hosts (off network
allowlist; `pip` works). **Actual model evaluation must happen in Colab**, where
HF/GitHub releases are reachable. Here we build the integration + can eyeball
sampled frames from an uploaded clip to gauge difficulty.
