# ReefScanner

A local desktop app for finding animals in long underwater video.

Point it at a folder of static-camera (BRUV-style) footage. It watches the
whole thing, surfaces the moments worth a look, and gives you a review screen
to mark each one true or false positive and tag the species. Hours of watching
becomes minutes — and every verdict you record becomes labeled training data
for a better detector later.

Everything runs on your machine. No upload, no account, no cloud.

> **Status: v2 usable.** Engine, service, review UI and native window all
> work. Not yet packaged as a double-clickable app — you launch it from a
> terminal.

## Install

```bash
git clone https://github.com/simonicarlo/reefscanner.git
cd reefscanner

uv sync

# Build the review UI. Needed once, and again whenever app/frontend/ changes —
# the build is not committed to the repo.
cd app/frontend && npm install && npm run build && cd ../..
```

The repo is a uv workspace of three packages (see [Architecture](#architecture)),
and a plain `uv sync` installs all of them, editable, with the desktop window,
SAHI and the test suite. Use `uv sync` rather than `uv pip install`: `uv run`
re-syncs against the lockfile every time and removes anything it didn't record.

Plain pip works too, if you'd rather: `python3 -m venv .venv && source
.venv/bin/activate && pip install -e ./core -e './app[desktop]'`.

Needs Python ≥ 3.10 and **ffmpeg** for clip extraction — `brew install ffmpeg`
on macOS, `apt install ffmpeg` on Debian/Ubuntu, or `pip install
imageio-ffmpeg` for a bundled fallback binary.

Packages and extras:

| Package | What it adds |
|---|---|
| `reefscanner-core` | The detection engine and the `reefscanner` CLI |
| `reefscanner-core[ml]` | SAHI tiled inference for small/distant animals |
| `reefscanner-app` | The local service and review UI (FastAPI + SQLite) |
| `reefscanner-app[desktop]` | The native window (PyWebView) |
| `reefscanner-edge` | The on-rig agent (v3, in progress) |

The YOLO detectors are core, not optional — motion-only triage was removed
because it cannot tell a small fish nearby from a large one far away. A plain
`pip install reefscanner-core` can scan footage out of the box.

## Running it

```bash
uv run reefscanner desktop   # native window — the normal way to use it
uv run reefscanner serve     # same app in your browser, http://127.0.0.1:8000
```

`uv run` finds the project's virtualenv on its own, so there is nothing to
activate. With the venv activated, drop the `uv run` prefix from every command
below.

There is no authentication, deliberately — it binds to localhost and is meant
for one person on one machine. Don't put it on a network interface.

Headless, no UI required:

```bash
uv run reefscanner process ~/footage --out ~/results
uv run reefscanner report ~/results   # false-positive rate once you've labeled
```

No footage handy? Generate some synthetic dives to try the whole loop on:

```bash
uv run python scripts/make_demo_footage.py ~/ReefScanner-demo
```

## Reviewing

Create a project pointing at a footage folder, press **Scan footage**, and
watch progress live. When it finishes you get a grid of candidate events;
click one to open the review screen.

Review is built for the keyboard, because the mouse is the bottleneck when
there are six hundred events:

| Key | Action |
|---|---|
| `T` / `F` / `U` | Confirm · reject · unsure |
| `←` `→` | Previous / next event |
| `Space` | Play / pause the clip |
| `B` | Toggle the detection box |
| `S` | Jump to the species field |
| `Enter` | Save from the species field |

A verdict jumps straight to the next *unreviewed* event, so you can work
through a whole run without touching the mouse. Species you've already used
are suggested as you type, which keeps one animal from becoming three
spellings.

## Choosing a confidence threshold

Once you have labeled some events, the run page recommends a threshold measured
on *your* footage: the highest value that keeps every animal you confirmed.
Below it you review junk for nothing; above it you start missing real sightings.
**Apply to project** writes it into the scan settings, and because changing a
setting invalidates the manifest, the next scan genuinely reruns.

The sweep is simulated from detections the scan actually emitted, so it tells
you nothing about animals the detector missed below the threshold you scanned
at. It reports recall relative to what that scan found, never absolute recall.
With fewer than five labeled detections it says so and treats the number as a
hint.

## How it works

```
discover videos
  → sample frames (1 fps by default)
  → find candidates: a YOLO detector scanning every frame
  → merge nearby candidates into events
  → one padded clip + thumbnail + database row per event
  → you review each event and record a verdict
```

The detector is the recall source, chosen with `--detector`. (Motion gating
survives only as an optional cheap pre-skip of dead-static frames —
`--motion-prefilter` — not as a way of deciding what matters: on real footage
it can't tell a small fish close to the camera from a large animal far away.)

**`marine` (default) — SharkTrack.** A YOLOv8 model trained on real BRUVS
footage, single `elasmobranch` class, MIT-licensed. The weights download
automatically on first use (~6 MB, cached in `~/.cache/reefscanner`). Nothing
extra to install — the detector ships with the app. Expect scanning to be
considerably slower on a CPU than on a GPU.

**`generic`** runs a stock COCO YOLO as a crude objectness proposer. Mostly
useful for experimenting.

See [`docs/model-research.md`](docs/model-research.md) for how these were
chosen and what the alternatives were.

> Ultralytics YOLO is AGPL-3.0. Fine for research and internal use; read the
> license before distributing a product built on the `marine` or `generic`
> detectors.

## Architecture

```
core/src/reefscanner/core/       reefscanner-core: the detection engine, no web
                                 dependencies; cli.py is process | report |
                                 serve | desktop
edge/src/reefscanner/edge/       reefscanner-edge: the on-rig agent (v3)
app/src/reefscanner/app/         reefscanner-app: FastAPI service + SQLite store
app/src/reefscanner/desktop/     PyWebView shell — starts the service, opens a window
app/frontend/                    React + Vite + Tailwind review UI
app/packaging/, app/scripts/     the Mac app build
tests/core/, tests/app/          one test suite, split by package
```

`reefscanner` is a namespace package that the three share. Core never imports
from the app or the edge agent, which is what keeps `reefscanner process`
usable without the web stack, and keeps it light enough for the rig. Specs
for each version live in [`docs/specs/`](docs/specs/README.md).

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
├── frames/                     the same peak frame, clean — for training
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
training on. Annotations point at the clean frames in `frames/`, never the thumbnails —
a model trained on those would learn the drawn box. The YOLO zip includes
the images, so it is a usable dataset as downloaded.

## Resumability

Interrupt a run at any point and start it again — finished videos are skipped.
A video that was mid-analysis is not marked complete, so it reprocesses from
the beginning rather than resuming halfway and losing events at the seam.

Cancelling a job from the UI does the same thing: it stops between frames and
leaves everything already committed intact.

## Development

```bash
uv sync
uv run pytest

# Two terminals: the API with reload, and Vite with hot module replacement.
uv run reefscanner serve --reload
cd app/frontend && npm run dev    # http://localhost:5173, proxies /api
```

Fonts are bundled rather than loaded from a CDN — the app has to work with no
internet. `npm run build` writes into `app/src/reefscanner/app/static/`, which is
gitignored; the wheel picks it up from there.

### Building the Mac app

```bash
app/scripts/build_app.sh    # → app/dist/ReefScanner.dmg (Apple Silicon)
```

Builds from a clean standalone Python, bundles the UI, the SharkTrack weights
and ffmpeg, and wraps the result in a disk image. The app is unsigned, so the
first launch needs a one-time "Open Anyway" — [`docs/INSTALL-mac.md`](docs/INSTALL-mac.md)
walks a recipient through it. A running app logs to
`~/Library/Logs/ReefScanner/reefscanner.log`.

Tests fabricate synthetic BRUV videos (a large slow "animal" plus flickery
"baitfish" noise the size filter must reject), so no real footage is needed and
none is committed.

## License

MIT — see [`LICENSE`](LICENSE). Note the AGPL caveat above if you enable the
YOLO detectors.
