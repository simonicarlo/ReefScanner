# ReefScanner v2 — The Desktop App

> **Status:** shipped (2026-09). Builds on the [v1 spec](../v1/spec.md), whose reasoning — recall over precision, per-video resumability, the CSV column contract — still governs the engine. Where v1 describes Colab, Google Drive or notebook execution it is history; where the two conflict, this document wins. Feature-level specs and plans written during v2 are in [`features/`](features/); the session handoff log is [`plan.md`](plan.md).

v1 proved the engine and produced exactly the problem it predicted: candidate events pile up faster than a CSV and a folder of clips can be reviewed. [v1 §9](../v1/spec.md) deferred a review UI and [v1 §10](../v1/spec.md) said the labels are the point. v2 builds that.

## 1. What changed and why

| v1 | v2 | Why |
|---|---|---|
| Colab notebook, iPad browser | Local desktop app | The notebook was a vacation constraint, not a design choice. Footage is large and local; uploading it to review it is backwards. |
| Google Drive I/O | Local folders | Same reason. No mount to lose, no session to reconnect. |
| CSV is the source of truth | SQLite is; CSV is an export | A CSV cannot represent "which of these 900 events have I reviewed" without being rewritten in place, which is exactly what an append-only crash-safe writer is designed not to do. |
| Labels typed into a spreadsheet | A review UI with keyboard shortcuts | Reviewing is the bottleneck. Its ergonomics are the product. |
| Motion gate is the recall source | Detector is (`marine` default); motion is an optional pre-filter | Tested on real BRUV footage: motion cannot separate a small fish nearby from a large animal far away. Monocular video has no depth cue, so `min_blob_area` is a proxy for distance the data does not support. |

**Unchanged:** recall over precision, the engine's tunables and their defaults, per-video resumability via the manifest, and the CSV column contract.

## 2. Shape

A local FastAPI service with a SQLite store, a React review UI, and a PyWebView window wrapping both. One Python distribution; the native window is an optional extra.

The engine stays a standalone, web-free package. `reefscanner process` must keep working with nothing installed but OpenCV — the app is a client of the engine, never the other way round.

## 3. State

Two stores, deliberately not merged:

- **Manifest** — per-video processing completion, in the output folder. Owns resumability. A results folder must stay interpretable without the database.
- **Database** — projects, jobs, events, labels, in the user's app-data directory. Owns everything the engine doesn't know about, above all the human verdicts.

`Label` is one row per event, upserted. Verdicts are three-valued — `TP`, `FP`, `unsure` — and an unreviewed event has *no* label row, which is a different state from `unsure`. Only `TP` events are exported as training annotations.

## 4. Jobs

One worker thread per job, in-process. No broker: single-user app, queue depth ~1, and an external service is one more thing to install and keep alive.

Two progress granularities, because per-video alone leaves the UI frozen for minutes on a long file:
- `on_video` — exact, once per finished video.
- `on_frame` — per sampled frame, throttled to a couple of writes a second before it reaches the database or the WebSocket.

Cancellation is cooperative and checked between sampled frames. A cancelled video is not marked complete, so it reprocesses whole rather than resuming mid-file and dropping events at the seam. Jobs still marked running at startup are reconciled to failed — a thread does not survive a force-quit, and a stale `running` row would block the project forever.

## 5. Security posture

Single-user, localhost, no authentication — stated so it isn't mistaken for an oversight. Two rules follow from having no auth:

- Media is addressed by **event id**, never by a client-supplied path, and every resolved path is checked to be inside the owning project's output folder. A `?path=` media endpoint on an unauthenticated local server is an arbitrary-file-read for anything else on the machine.
- Binding to anything other than localhost warns loudly.

## 6. Out of scope (still)

Individual re-identification. Multi-user or shared projects. Remote GPU offload — the intended shape is a `reefscanner worker --queue <url>` pulling jobs, but not before the local path is in real use. Model re-research is worthwhile but deliberately off the critical path: the detector interface is model-agnostic, so a better model is a swap, not a rewrite.
