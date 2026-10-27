# SAHI tiling for the ONNX backend

Phase 0 item. `use_sahi` finds small, distant animals by running the detector
on overlapping tiles as well as on the whole frame. Today it needs the
Ultralytics backend and the `sahi` package, so the rig can't use it.

## Decisions

### 1. Tiling lives in core, around any detector

`TiledDetector` (`core/detectors/tiling.py`) wraps a detector: it cuts the
frame into tiles, runs the inner detector on each and on the whole frame,
moves every box back onto the frame and merges duplicates. It needs only
NumPy, so it runs on the rig, and it works with any backend, including the
board backends to come.

### 2. Same algorithm as `sahi`, so `sahi` can be the reference

It mirrors `sahi.predict.get_sliced_prediction` (0.12) with its defaults:

- **Tiles**: `sahi`'s `get_slice_bboxes`. Tiles step by `size - int(overlap
  × size)`, and a tile that would run past the edge is moved back inside the
  frame, so every tile is full-size.
- **Whole frame too** (`perform_standard_pred`), when there is more than one
  tile, so large animals that span tiles are still found whole.
- **Merging**, per class: greedy non-maximum *merging*. Boxes are taken by
  score; each kept box absorbs the lower-scored boxes whose intersection
  covers at least half of the smaller box (IoS ≥ 0.5). An absorbed box
  widens the kept one to the union of both, if the overlap with the grown box
  is still above 0.5; the score is the higher of the two.
- **Low thresholds**: below a confidence of 0.1, `sahi` switches to plain NMS
  on IoU 0.5, since merging many weak boxes inflates them. We do the same.

The Ultralytics backend keeps using `sahi` itself as the reference, as the
TODO's decisions say. `scripts/check_onnx_parity.py --sahi` compares the two
on the test dives.

### 3. A bug found on the way

`sahi` takes NumPy images as RGB and flips them to BGR for Ultralytics. Our
wrapper passed it OpenCV's BGR frames, so with `use_sahi` on, SharkTrack saw
red and blue swapped. The wrapper now hands `sahi` RGB.

### 4. Bounds

Tile count grows fast as tiles shrink or overlap grows, and these settings
can arrive in an imported package. `validate()` now requires tiles of
64–4096 px and an overlap from 0 to 0.5.

## Cost, to keep in mind

Tiling multiplies detector runs: 16 per 1080p frame (15 tiles plus the whole
frame), 21 at 1920×1440. Fine for laptop rescans. On the rig it only helps on
full-resolution pixels; on today's 640 px detection stream it makes 3 runs and
magnifies little. If the rig moves to higher-resolution detection and hits a
performance bottleneck, one option is to tile only at the idle rate (first
sightings) and never during bursts.

## Not now

- Batching tiles into one inference call. Worth it on a GPU or a board with a
  batch-capable runtime; on CPU it saves little.
