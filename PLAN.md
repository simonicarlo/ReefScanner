# ReefScanner Overhaul — Working Plan / Session Handoff

> **For a fresh Claude Code session:** read this file first, then continue from
> "Progress" below. Everything above that line is settled context — decisions
> already made with the user, and findings already verified by reading the code.
> You should still spot-check anything you're about to change, but you do not
> need to re-derive the plan or re-ask the scoping questions.

Written: 2026-09-08. Author: prior session (context lost when the session
re-initialized on a model switch and the task-tracking tools dropped out).

---

## 1. What the user wants

Verbatim framing from the user:

> "I made this project as a test while on vacation. It is horrible since I had
> to make it on my iPad in an online IDE. But now I would like to make it a bit
> more serious. Let's overhaul it a bit. Basically I just want to create an app
> that analyzes video footage for certain animals. The models used here just
> happen to be the best ones I found on the go but maybe there are also better
> options. Also no ipynb. I want to make this an actual (Web/or non-web) app."

So: keep the working analysis engine, drop the notebook/Colab framing, and turn
it into a real application.

## 2. Decisions locked in (user answered these explicitly)

| Question | Decision |
|---|---|
| App shape | **Desktop app, local** |
| Desktop shell | **PyWebView** (pure Python, native OS webview, PyInstaller-packable). Tauri considered and rejected for MVP — Rust build + Python sidecar not worth it yet. |
| Domain scope | **Keep marine focus** — sharks/rays, BRUV-style static camera. Not broadened to general wildlife. |
| Triage/labeling UI | **Yes, full triage UI** — browse clips, mark TP/FP, tag species, notes, export labeled data for future fine-tuning. This closes the loop SPEC §9/§10 deferred. |
| Compute | **Local (CPU + optional GPU), with optional remote GPU offload later.** Remote worker is explicitly *not* in the first cut. |
| First-cut ambition | **Vertical slice** — end-to-end and usable, bare-bones features. Not "full v2". |

Also: **no `.ipynb`** anywhere. The notebook gets deleted, not ported.

On models: SharkTrack (YOLOv8, MIT, BRUVS-trained) stays the default `marine`
detector. `docs/model-research.md` is dated 2026-06 (~3 months old at time of
writing). The user said models were "the best ones I found on the go" and is
open to better — but the app architecture is model-agnostic behind the detector
interface, so **this is not a blocker for the overhaul**. Re-research models as
a separate task if the user wants; don't gate the app work on it.

## 3. Current state of the repo (verified by reading every engine module)

The Python engine is genuinely decent and **should be kept, not rewritten**. The
mess is at the edges (notebook, Colab/Drive assumptions, stale TODO).

```
src/reefscanner/
├── __init__.py     Public API re-exports; __version__ = "1.0.0"
├── cli.py          argparse CLI: `process` and `report` subcommands
├── config.py       ReefScannerConfig dataclass — ALL tunables, validate(),
│                   from_dict (rejects unknown keys), from_yaml, to_dict
├── discovery.py    discover_videos(root, extensions) — recursive
├── videoio.py      VideoInfo, probe_video() (OpenCV + optional ffprobe),
│                   SampledFrame, iter_sampled_frames() (grab-and-skip stride)
├── motion.py       MotionGate — MOG2/KNN bg subtraction, warm-up, morphology,
│                   size+persistence filters, bbox rescale to original res.
│                   .process() -> Candidate|None ; .has_motion() -> bool
├── detection.py    Detection(bbox, class_name, confidence)
├── detectors/      Pluggable: get_detector(cfg) factory.
│                   none (no-op, no ML deps) / marine (SharkTrack YOLO) /
│                   generic (stock COCO). yolo.py wraps Ultralytics + SAHI.
├── events.py       Candidate (unified motion-or-detection per-frame hit),
│                   Event, aggregate_events() (merge by time gap),
│                   derive_timestamp()
├── clips.py        resolve_ffmpeg(), extract_clip() (stream-copy or reencode),
│                   save_thumbnail() (peak frame + bbox drawn)
├── manifest.py     Manifest — per-video completion, atomic JSON write,
│                   source of truth for resume
├── results.py      CSV_COLUMNS contract, event_to_row(), CsvWriter
│                   (append-only, whole rows, fsync)
├── report.py       fp_report() — false-positive rate from human-filled labels
├── pipeline.py     process_folder() / process_video() — orchestration
└── weights.py      SharkTrack weights auto-download + cache
```

Docs: `README.md` (Colab-heavy), `SPEC.md` (v1 spec, still useful history),
`TODO.md` (v1 checklist, all done — delete), `docs/model-research.md` (keep),
`ReefScanner.ipynb` (delete).

Tests: `tests/` — conftest.py fabricates synthetic BRUV videos so no real
footage is needed. ~20 tests, reportedly passing. `test_config.py`,
`test_motion.py`, `test_detector.py`, `test_pipeline.py`.

### Integration hooks that matter for the app

These are the specific seams the service layer should use:

- **`pipeline.process_folder(cfg, progress=True, on_video=callback)`** — the
  `on_video` callback fires once per completed video with a `VideoResult`.
  That's the progress hook for the WebSocket. **Caveat: it's per-video
  granularity only.** For a long single video the UI would show nothing for
  minutes. Consider adding a finer-grained callback (per sampled frame or per
  N frames) to `process_folder` / `_collect_candidates`.
- **`ReefScannerConfig`** is a plain dataclass with `to_dict`/`from_dict` —
  ideal for storing per-project config as JSON and deriving API schemas.
  `from_dict` deliberately *rejects* unknown keys (typo protection); keep that.
- **`Event`** dataclass fields map almost 1:1 onto the DB `Event` model.
- **`results.CSV_COLUMNS`** is the existing export contract. Under the new
  design the CSV becomes an *export format*, not the source of truth — the
  SQLite DB takes over. `label`/`species`/`notes` columns were reserved for
  exactly the labeling workflow now being built.
- **`Manifest`** stays the resume mechanism for the engine. The DB tracks
  app-level job state; the manifest tracks per-video completion. Don't conflate
  them.
- **`MotionGate` is stateful per video** — construct one per video, never share.

## 4. Target architecture

```
ReefScanner/
├── pyproject.toml            one distribution, several subpackages
├── src/reefscanner/
│   ├── engine/               ← existing modules move here verbatim
│   ├── app/                  ← FastAPI service
│   │   ├── main.py           app factory, static mount, WS
│   │   ├── db.py             SQLModel engine + session
│   │   ├── models.py         Project / Job / Event / Label
│   │   ├── schemas.py        pydantic request/response
│   │   ├── jobs.py           in-process background job runner
│   │   ├── routers/          projects, jobs, events, labels, exports, media
│   │   └── static/           built React dist/ lands here
│   ├── desktop/main.py       ← PyWebView shell
│   └── cli.py                process | report | serve | desktop
├── frontend/                 ← React + Vite + TS + Tailwind source
└── tests/
```

**Import compatibility:** moving engine modules into `engine/` breaks every
import. Preserve the public API by re-exporting from `src/reefscanner/__init__.py`
so `from reefscanner import ReefScannerConfig, process_folder` keeps working and
the existing tests need minimal edits.

### Data model (SQLModel / SQLite)

- `Project(id, name, input_folder, output_folder, config JSON, created_at)`
- `Job(id, project_id, status, progress, started_at, finished_at, error)`
- `Event(id, job_id, event_id, source_video, start_seconds, end_seconds,
   peak_timestamp, peak_score, peak_bbox JSON, motion_score, ml_confidence,
   detected_class, clip_path, thumbnail_path)`
- `Label(id, event_id FK, verdict TP|FP, species, notes, tight_bbox JSON,
   updated_at)`

Provide a bridge that imports existing `reefscanner_results.csv` into the DB
(so prior runs aren't orphaned) and exports back out.

## 5. Task list

Originally tracked in the task tool (8 tasks); reproduced here since that state
is no longer readable.

1. **Purge Colab/notebook-era code** — delete `ReefScanner.ipynb` and `TODO.md`;
   strip Drive/Colab language from `README.md`; refresh `SPEC.md` to describe
   the desktop-app direction (keep the v1 motion-only rationale as history).
2. **Restructure repo layout** — move engine modules to `src/reefscanner/engine/`,
   add `app/`, `desktop/`, `frontend/`. Re-export public API from
   `reefscanner/__init__.py`. Update `pyproject.toml` (new deps: fastapi,
   uvicorn, sqlmodel, pywebview; new console scripts).
3. **SQLite state store** — SQLModel schema above, plus the CSV import/export
   bridge.
4. **FastAPI service** — projects CRUD, job start/status/list, event list with
   filters, label upsert, exports (CSV / COCO / YOLO), static file serving for
   clips + thumbnails, WebSocket for live job progress. Background worker calls
   `pipeline.process_folder` in-process; no external queue in the vertical slice.
5. **Scaffold React frontend** — Vite + React + TypeScript + Tailwind +
   shadcn/ui + TanStack Query + React Router. API base URL env-driven so it
   works both against a dev server and inside PyWebView.
6. **Triage UI pages** —
   (a) Projects list + create,
   (b) Project detail: config editor, Run button, jobs list with live progress,
   (c) Job detail: thumbnail grid, filters by class/confidence/labeled state,
   (d) Event review: HTML5 player scoped to the clip, motion-bbox overlay,
       keyboard shortcuts (`t`=TP, `f`=FP, `space`=play/pause, arrows=prev/next),
       species combo, notes, save. Export button.
7. **PyWebView desktop shell** — entry point that starts FastAPI on a free port
   in a background thread, waits for readiness, opens a native window at it.
   Ship the built React `dist/` inside the package. JS bridge for native folder
   picker (a plain path text input is acceptable for the first cut).
8. **Refresh docs + tests** — rewrite README for the desktop-app story; update
   SPEC.md; keep existing engine tests green; add a service smoke test (create
   project → run job on a synthetic video → list events → apply a label);
   optional Vitest render smoke test for the frontend.

Suggested order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Tasks 1–2 are the foundation and
are worth showing the user before going further.

## 6. Progress

**Tasks 1-4 are done** (session of 2026-09-08, committed to `main`).
Environment: node v24.14.1, npm 11.11.0, Python 3.11, ffmpeg present. Deps
managed with **uv** into `.venv`; user chose to work directly on `main`.

- **Task 1 (purge) — done.** Deleted `ReefScanner.ipynb`, `TODO.md`,
  `requirements.txt`. Scrubbed Colab/Drive language from engine docstrings.
  README rewritten for the desktop-app story. `SPEC.md` retitled, given a
  "how to read this" preamble framing §1-§10 as history, and extended with
  **§11 (v2 - the desktop app)** covering what changed and why, state
  ownership, the job model, and the security posture.
- **Task 2 (restructure) — done.** Engine modules moved to
  `src/reefscanner/engine/` via `git mv` (history preserved). Public API
  re-exported from `reefscanner/__init__.py`, so
  `from reefscanner import ReefScannerConfig, process_folder` still works.
  `pyproject.toml` rewritten: version 2.0.0.dev0, requires-python >=3.10,
  new `[app]` / `[desktop]` extras.
- **Task 3 (SQLite store) — done.** `app/models.py` (Project/Job/Event/Label),
  `app/db.py` (WAL, per-OS data dir, `REEFSCANNER_DB` override),
  `app/exports.py` (CSV import bridge + CSV/COCO/YOLO export).
- **Task 4 (FastAPI service) — done.** Routers for projects, jobs, events +
  labels, exports, media, and a WebSocket. `app/jobs.py` runs the engine on a
  worker thread; `app/progress.py` fans progress out to sockets.
  `reefscanner serve` added to the CLI.

**Engine changes made for the app** (the §7 open item on progress granularity,
now resolved):
- `process_folder` / `process_video` / `_collect_candidates` gained
  `on_frame` (per sampled frame, with a 0-1 fraction through the current
  video) and `should_cancel` (polled between frames).
- New `JobCancelled` exception and `BatchResult.cancelled`. A cancelled video
  is never marked complete, so it reprocesses whole on resume.

**Verification:** 33 tests pass (20 pre-existing engine + 10 new service +
3 new engine-hook). Beyond the suite, verified by hand: `reefscanner serve`
boots and answers `/api/health` and `/docs`; a live WebSocket client received
6 progress messages across a 3-video job ending `done`, `progress=1.0`,
3 events.

### Tasks 5-7 (session of 2026-09-08, second pass)

- **Task 5 (frontend scaffold) — done.** `frontend/`: Vite + React 19 + TS +
  Tailwind v4 + TanStack Query + React Router 7. Vite builds straight into
  `src/reefscanner/app/static/` and proxies `/api` + `/ws` to the backend in
  dev, so the app is same-origin in both modes and CORS never differs.
  **Deviation from the plan: no shadcn/ui.** Its installer is interactive and
  pulls a large dependency tree; the handful of components needed are
  hand-rolled in `components/ui.tsx` in the same own-the-code spirit.
  **Fonts are bundled via `@fontsource`, not Google Fonts** — a desktop app
  must render offline.
- **Task 6 (triage UI) — done.** Four pages: projects list + create, project
  detail (config editor built from `/api/projects/defaults`, run button, live
  job list), job detail (thumbnail grid, filters, review-progress bar,
  exports), and the review screen (player, bbox overlay, keyboard shortcuts,
  species datalist, notes). A verdict auto-advances to the next *unreviewed*
  event, which is what makes long runs bearable.
- **Task 7 (desktop shell) — done.** `desktop/main.py` picks a free port,
  starts uvicorn on a daemon thread, polls `/api/health` until it answers,
  *then* opens the webview — a window pointed at a not-yet-listening port shows
  an error and never retries. `reefscanner desktop` added to the CLI. A
  `pick_folder()` JS bridge exists but the UI takes typed paths, because the
  same build has to work in a plain browser tab where no bridge exists.

**Design direction** (worth keeping if the UI is extended): "deep-water
instrument". Dark abyssal ground so the footage is the brightest thing on
screen; colour spent almost nowhere so the three verdict colours carry real
meaning (cyan confirmed / coral rejected / amber unsure); IBM Plex Sans
Condensed for labels, IBM Plex Mono with tabular figures for every number.

**Verification:** 38 tests pass (20 engine + 10 service + 3 hooks + 5 desktop).
Driven in a real browser against a real seeded backend: all four pages render,
the bbox overlay lands on the animal, pressing `T` persisted a verdict through
to the database, and CSV/COCO/YOLO exports all returned correct content with
only TP events included. `reefscanner desktop` was launched for real and
registered with macOS as a foreground GUI app.

### Gotchas hit, worth not rediscovering

- **`from __future__ import annotations` breaks SQLModel `Relationship`.**
  Postponed evaluation leaves the target as an unresolvable string. That
  import is deliberately absent from `app/models.py`; there's a comment saying
  so. Don't "tidy" it back in.
- **FastAPI 0.141 wraps included routers in lazy `_IncludedRouter` objects**,
  so `app.routes` looks nearly empty when inspected. The routes are fine.
- **The synthetic test video is 12s at 5fps**, so engine-default
  `warmup_frames=10` at 1 sampled fps consumes the entire clip and emits
  nothing. Service tests use a `TEST_CONFIG` mirroring the engine tests'
  tunings. A "no events" failure is usually this, not a real bug.
- **The frontend build is gitignored** (`src/reefscanner/app/static/`). A
  fresh clone must run `npm run build` before `reefscanner desktop` works;
  the shell prints exactly that if the build is missing.
- **`erasableSyntaxOnly` is on in the TS config**, so TypeScript constructor
  parameter properties (`constructor(readonly x: number)`) are a compile
  error. Declare fields explicitly.
- **Thumbnails have the detection box drawn onto them**
  (`engine/clips.save_thumbnail`). Good for triage, bad as training images -
  the annotation exporters reference them anyway and say so in their
  docstring. Worth fixing before anyone actually fine-tunes on this data:
  either save a second clean frame or make the drawing optional.

## 7. Open items / unverified

- ~~Tooling not verified.~~ Resolved: node v24.14.1 / npm 11.11.0 are present,
  so task 5's frontend plan is viable.
- ~~No virtualenv confirmed.~~ Resolved: `.venv` managed by `uv`.
- ~~Per-video-only progress granularity.~~ Resolved: `on_frame` added, see §6.
- **Remaining: task 8 only** — and most of it is done (README rewritten, SPEC
  §11 added, service + desktop tests written). What's genuinely left: an
  optional Vitest render smoke test for the frontend, and packaging as a
  double-clickable app (PyInstaller), which the plan never scoped.
- **No database migrations.** `Database.create_all()` creates missing tables
  but will not add a column to an existing one. Adding an engine tunable is
  fine (config is a JSON blob); adding a column to `Event` or `Label` needs
  Alembic, or telling the user to delete their database.
- **Model re-research** is optional and deliberately out of the critical path.
- **Remote GPU offload** is explicitly deferred past the vertical slice. The
  intended shape is `reefscanner worker --queue <url>` pulling jobs, but don't
  build it until the local path is used and working.

## 8. Detector-first triage (2026-09-11)

Spec `docs/superpowers/specs/2026-09-11-detector-first-triage-design.md`, plan
`docs/superpowers/plans/2026-09-11-detector-first-triage.md`. All ten tasks done.

- Motion-only recall removed; `marine` is the default and torch/ultralytics are
  core dependencies. `MotionGate` kept as the optional pre-filter.
- Threshold sweep (`app/analysis.py`) + endpoint + run-page panel with Apply.
  On the real Run #5 labels (6 confirmed, 1 rejected) it recommends 0.57,
  which drops exactly the one junk detection.
- Clean frames written beside annotated thumbnails; exports and the YOLO zip
  use them.
- `Database.create_all()` now adds missing *nullable* columns, so schema growth
  no longer means deleting the database. Drops/renames/types still need Alembic.

Open, deliberately not done:
- **Motion-based tracking** of detected animals — the reason `MotionGate` stays.
- **Fine-tuning** is unblocked (clean frames exist) but needs far more labels.
- **Multi-class** (`marine-detect`: shark/ray/turtle) is AGPL; undecided.
