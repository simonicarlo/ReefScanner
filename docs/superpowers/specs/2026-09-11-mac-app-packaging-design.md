# Downloadable Mac app

**Date:** 2026-09-11
**Status:** approved, in progress

## Goal

Someone with no command-line experience downloads one file, drags the app to
Applications, and scans footage. No Python, no Homebrew, no terminal.

## Decisions

| Question | Decision |
|---|---|
| Target | macOS on Apple Silicon first. Windows and Intel Macs later, from the same build recipe on CI runners. |
| Tool | **PyInstaller**, one-folder `.app`, wrapped in a `.dmg` with the built-in `hdiutil`. |
| Signing | **None for now.** The recipient does a one-time "Open Anyway". Signing can be added to the same build later. |
| Hosting | A GitHub Release asset. The repo is public, which also satisfies the AGPL source requirement. |

Rejected: Briefcase (weaker with torch/OpenCV binary wheels), and a
download-and-install script (terminal, ~1 GB on first run, its own security
prompts — the worst fit for the audience).

## Build

`scripts/build_app.sh` builds from a **clean uv-managed standalone CPython
3.11**, never the developer's environment. The dev venv is based on Anaconda,
and a bundle built from it can link against libraries that don't exist on the
recipient's machine.

Steps: fresh venv → install `.[desktop]`, `imageio-ffmpeg`, `pyinstaller` →
`npm run build` → PyInstaller with `packaging/reefscanner.spec` →
`hdiutil` → `dist/ReefScanner.dmg`.

## What goes inside the app

- The built React UI (already package data of `reefscanner.app`).
- **The SharkTrack weights (6 MB).** Without them the first scan needs the
  internet and fails with a confusing error if there is none.
- **ffmpeg, via `imageio-ffmpeg`.** An app launched from Finder gets a minimal
  `PATH` without Homebrew, so the system `ffmpeg` is invisible even on a
  developer's machine. `resolve_ffmpeg` already falls back to `imageio-ffmpeg`.

## Code changes

1. **Weights:** `ensure_sharktrack_weights` checks for a copy bundled beside
   the app before the cache and before downloading.
2. **Frozen entry point:** a launcher that calls
   `multiprocessing.freeze_support()` before anything else. Without it, any
   child process torch spawns re-executes the whole app and opens a second
   window.
3. **Startup feedback:** importing torch takes several seconds, and until now
   the window only appeared once the server was ready. A non-technical user
   seeing nothing will double-click again. The window opens immediately on a
   "Starting…" page and switches to the app once the server answers.

User data stays where it is — the database in
`~/Library/Application Support/ReefScanner`, weights cache in
`~/.cache/reefscanner` — so replacing the app with a newer build keeps every
label.

## For the recipient

`docs/INSTALL-mac.md`: download, open the `.dmg`, drag to Applications, the
"Open Anyway" step in System Settings → Privacy & Security, and where the demo
footage generator is not needed (they bring their own videos).

## Verification

Build the `.dmg`, install the `.app` from it, and launch the real app — not the
dev venv — with the weights cache moved aside, so the run proves the app is
self-contained. It must start, show the UI, and produce events from a scan of
demo footage.

## Risks

- **Size:** roughly 600–900 MB, mostly torch. Fine for a download link.
- **torch under PyInstaller** has known quirks (it inspects its own source at
  runtime). Expect a few rounds of fixes to the spec file.
- **Gatekeeper** blocks the first launch. Mitigated by the written guide, and
  removable later by signing.

## Out of scope

Signing and notarization, auto-update, Windows and Intel builds.
