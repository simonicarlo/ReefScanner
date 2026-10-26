# The field app on Camtrap DP

**Date:** 2026-10-26
**Status:** approved and built 2026-10-26
**Builds on:** [Camtrap DP data model](2026-10-26-camtrap-dp-data-model-design.md)

## Goal

The app stops keeping its own `Event` and `Label` tables. A scan writes Camtrap
DP rows (media, machine observations, per-frame detections), a review writes a
human observation, and a scan can be exported as a valid package. The rig's
event writer will later produce the same rows, so this is the one mapping from
"the detector found something" to Camtrap DP, proven on real footage first.

## The mapping: one function in core

`reefscanner.core.camtrap.build` turns a scanned video's events into rows:

- per event: a clip `Media`, a clean-frame `Media`, a machine `Observation` on
  the frame (detector class mapped to a scientific name, peak box relative to
  the frame, peak confidence), its `ObservationExtra`, and one `Detection` per
  sampled frame;
- the `Deployment`'s start and end, from the videos' times.

The pipeline already knows all of this; nothing is re-read from disk. The edge
agent will call the same function.

## Decisions

### 1. A project is a deployment

Each project is one Camtrap deployment: one folder of footage from one place.
Creating a project therefore asks for **latitude and longitude** (required, as
agreed) next to the camera timezone, plus optional depth, bait and comments.
The deployment's start and end come from the footage.

*Alternative:* one project holding several deployments (a folder per drop).
More flexible, but a laptop scan of one folder is one site in practice, and the
rig makes one package per drop anyway.

### 2. Scans stay as runs, reviews belong to a run

Today each scan ("run") has its own events and reviews, and the run page is
where reviewing happens. That stays: every machine observation records the run
that produced it (`scanID` in the sidecar, which is useful provenance in a
package too), and a review is a human observation on that run's event.
Rescanning with new settings makes a new run with fresh events, as now.

*Alternative:* one living set of observations per deployment, where a rescan
replaces the machine observations and carries reviews over to matching events.
Tidier data, but matching events across different settings is guesswork, and
a wrong match silently moves someone's verdict.

### 3. Videos without a recorded start time

Camtrap needs a timestamp on every media file and observation. When a video has
no creation time (rare for cameras, common for edited or converted files), the
scan falls back to the file's modification time and marks the deployment
`timestampIssues: true`, the standard's own flag for "don't trust these
times". The run page says so.

*Alternative:* refuse to scan such videos. Safe, but it blocks reviewing
footage that is otherwise fine.

## What else changes

- **Review** writes a human observation following the verdict table in the
  data-model note: TP, FP (nothing there), FP-other (something else, optional
  name), unsure. The review screen gains the FP split. Species are scientific
  names, free text for now, with the run's previous names suggested.
- **Boxes** are relative (0 to 1) end to end, as Camtrap stores them, so the
  review UI no longer needs the frame size.
- **Thumbnails** stop being a separate file in the app: the grid shows the
  clean frame with the box drawn over it, as the review screen already does.
  The engine keeps writing them for CLI users.
- **Export:** a run exports as a Camtrap DP package into its results folder
  (the clips and frames are already there, at the paths the media rows name).
  COCO and YOLO exports stay, read from observations; the results-CSV export
  goes, since the package replaces it.
- **Threshold analysis** reads machine probability and human verdict from
  observations instead of events and labels. Same maths.
- **Database:** a migration drops `event` and `label` and adds the project's
  deployment link. No data is carried over, as agreed.

## Notes from building it

- IDs are joined with `:` rather than `/` so they survive in URL paths:
  `<deployment>:scan-<run>:<video-stem>_<seq>`.
- Each run writes its files to `<results>/scan-<run>/`, which is also the
  package root, so a rescan never overwrites an earlier run and the folder is
  a self-contained package.
- The manifest is per run too. A shared one let a new run skip videos an
  earlier run had finished, so its package silently lacked them. Instead a new
  run scans everything, and a cancelled or failed run can be **resumed**: the
  same run continues in its own folder, skipping only what it already did.
- The sidecar gained `scanID`, `sourceVideo`, `videoStartSeconds`,
  `videoEndSeconds`, `peakSeconds` and `detectorClass`.
- The package's required contributor is the local user name for now.

## Out of scope

Importing packages from the rig (the next app item), species lists, editing
deployment details after a scan, and the CLI writing packages (it keeps its
CSV for now).
