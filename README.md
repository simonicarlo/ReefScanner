# ReefScanner

A local desktop app for finding animals in long underwater video.

Point it at a folder of static-camera (BRUV-style) footage. It watches the
whole thing, surfaces the moments worth a look, and gives you a review screen
to mark each one true or false positive and tag the species. Hours of watching
becomes minutes — and every verdict you record becomes labeled training data
for a better detector later.

Everything runs on your machine. No upload, no account, no cloud.

> **Status: v2 in progress.** The analysis engine and the local service are
> done and tested; the React review UI and the native window are being built.
> Until then the engine works headlessly via the CLI and the HTTP API.

## Install

```bash
git clone https://github.com/simonicarlo/reefscanner.git
cd reefscanner
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[app]'
```

Needs Python ≥ 3.10 and **ffmpeg** for clip extraction — `brew install ffmpeg`
on macOS, `apt install ffmpeg` on Debian/Ubuntu, or `pip install
imageio-ffmpeg` for a bundled fallback binary.

Extras, all optional:

| Extra | What it adds |
|---|---|
| `[app]` | The local service and review UI (FastAPI + SQLite) |
| `[desktop]` | The native window (PyWebView) |
| `[ml]` | YOLO detectors — torch, ultralytics, SAHI |
| `[dev]` | Tests |

`pip install reefscanner` with no extras still gives you a working CLI: the
default motion-only mode needs no ML dependencies at all.

## Running it

```bash
reefscanner serve            # http://127.0.0.1:8000  (API docs at /docs)
```

There is no authentication, deliberately — it binds to localhost and is meant
for one person on one machine. Don't put it on a network interface.

Headless, no service required:

```bash
reefscanner process ~/footage --out ~/results
reefscanner report ~/results          # false-positive rate once you've labeled
```

## How it works

```
discover videos
  → sample frames (1 fps by default)
  → find candidates: motion gating, or a YOLO detector scanning every frame
  → merge nearby candidates into events
  → one padded clip + thumbnail + database row per event
  → you review each event and record a verdict
```

Two ways to generate candidates, chosen with `--detector`:

**`none` (default) — motion only.** Background subtraction (MOG2/KNN) with
size and persistence filters. No ML dependencies, runs fine on a laptop CPU.
Tuned to over-flag rather than miss: a false positive costs you ten seconds, a
missed animal costs you the observation.

**`marine` — SharkTrack.** A YOLOv8 model trained on real BRUVS footage,
single `elasmobranch` class, MIT-licensed. The weights download automatically
on first use. This is the better option if you have the ML extra installed.

**`generic`** runs a stock COCO YOLO as a crude objectness proposer. Mostly
useful for experimenting.

See [`docs/model-research.md`](docs/model-research.md) for how these were
chosen and what the alternatives were.

> Ultralytics YOLO is AGPL-3.0. Fine for research and internal use; read the
> license before distributing a product built on the `marine` or `generic`
> detectors.

## Architecture

```
src/reefscanner/
├── engine/      the analysis core — no web dependencies, importable alone
├── app/         FastAPI service + SQLite state store
├── desktop/     PyWebView shell (in progress)
└── cli.py       process | report | serve
frontend/        React review UI (in progress)
```

The engine never imports from the app, which is what keeps `reefscanner
process` usable with nothing but OpenCV installed.

Two separate pieces of state, on purpose:

- The **manifest** (`reefscanner_manifest.json`, in your output folder) tracks
  which videos have finished processing. It's what makes an interrupted run
  resumable, and it lives next to the clips so a results folder stays
  self-describing even without the database.
- The **database** (SQLite, in your OS's app-data directory) holds projects,
  job history, and your labels.

`reefscanner_results.csv` is still written, and is still the same column
contract as v1 — but it's now an export format rather than the source of truth.
An old results folder can be adopted into a project without re-running
anything (`POST /api/jobs/{id}/import/csv`).

## Output

```
results/
├── clips/                      one padded clip per event
├── thumbnails/                 peak frame with the detection box drawn
├── reefscanner_results.csv     one row per event
└── reefscanner_manifest.json   which videos are finished
```

## Exports

Once you've labeled events, confirmed ones can leave as training data:

| Endpoint | Format |
|---|---|
| `/api/jobs/{id}/export/csv` | The v1 CSV, label columns filled in |
| `/api/jobs/{id}/export/coco` | COCO detection JSON |
| `/api/jobs/{id}/export/yolo` | YOLO label files + `classes.txt`, zipped |

Only events marked **TP** are exported — an `unsure` verdict is not a box worth
training on. Note that the exported images are the thumbnails, which have the
detection box drawn onto them; re-extract clean frames before actually
fine-tuning.

## Resumability

Interrupt a run at any point and start it again — finished videos are skipped.
A video that was mid-analysis is not marked complete, so it reprocesses from
the beginning rather than resuming halfway and losing events at the seam.

Cancelling a job from the UI does the same thing: it stops between frames and
leaves everything already committed intact.

## Development

```bash
pip install -e '.[dev]'
pytest
reefscanner serve --reload
```

Tests fabricate synthetic BRUV videos (a large slow "animal" plus flickery
"baitfish" noise the size filter must reject), so no real footage is needed and
none is committed.

## License

MIT — see [`LICENSE`](LICENSE). Note the AGPL caveat above if you enable the
YOLO detectors.
