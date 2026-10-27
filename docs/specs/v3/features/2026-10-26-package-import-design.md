# Importing Camtrap DP packages into the field app

**Date:** 2026-10-26
**Status:** built 2026-10-26
**Builds on:** [app on Camtrap DP](2026-10-26-app-on-camtrap-design.md),
[edge agent](2026-10-26-edge-agent-design.md)

## Goal

A package folder from the rig (or an SD card, or another laptop's export)
becomes a project whose events are in the normal review flow, with the same
keyboard shortcuts and the same export. Device sync over Wi-Fi or USB (phase 2)
will end in this same import.

## Decisions

### 1. A package becomes a project with one imported run

A project is a deployment, so a package with one deployment becomes a new
project. Its rows go into an **import run**: a job like a scan, with
`source` set to the folder it came from. Its observations carry the run's
`scanID`, so every existing query (event list, counts, threshold analysis,
exports) works unchanged. The rig's own `scanID` (`agent`) is replaced. The
provenance that matters, the model and backend, stays in the sidecar.

A package with several deployments is refused, and so is one whose deployment
is already in the database (409). Its reviews are already here.

### 2. Files are copied, as a job

The clips and frames are copied into the run folder (`<output>/scan-<run>/`),
so the SD card can go back into the rig. Copying a day of clips takes minutes,
so the import runs on the job runner, with progress, cancel and retry like a
scan. Rows are inserted in one transaction only after every file is in place:
a failed or cancelled import leaves no half-imported events, and retrying it
starts over cleanly.

### 3. The package is untrusted

The package is read with core's `read_package` and checked with `validate`.
On top of that it must be ReefScanner-shaped: every machine observation needs
its sidecar row and its clip and frame media. Every media `filePath` has to
name a regular file inside the package folder through no symlink at all (the
rig never writes one). Files are opened one path component at a time with
`O_NOFOLLOW`, again when copying, so a link swapped in after the check fails
instead of pulling in an outside file. The import job also rereads the package
and refuses it if it has become a different deployment. All problems
are returned together (422). Only files named by media rows are copied, to
the same relative path.
The project's settings take only tuning values from the package (an explicit
allowlist). Programs, model files and output file names (`ffmpeg_path`,
`detector_weights`, `detector_options`, the folder and file names) stay at the
laptop's defaults, so a package can't choose what a later rescan runs.

### 4. Human observations come along

A package exported after a review already holds human observations; they are
imported too, so a review can move between laptops.

## Notes from building it

- The edge agent now writes `camera_timezone` and `camera_clock` into the
  sidecar's `detectorConfig`, as the app's scans do; the import requires them.
  Packages the agent wrote before that are refused, and say why.
- Problems come back as `{message, problems}` in a 422's `detail`. The UI's
  error note lists them, for any endpoint that sends them.
- Checked end to end: a real dive replayed by the agent, imported in the UI,
  and reviewed in the normal grid.

## Out of scope

Merging a package into an existing project, packages that aren't
ReefScanner-shaped (no sidecar), and keeping the package's contributors,
which waits for the settings page.
