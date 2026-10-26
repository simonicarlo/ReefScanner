#!/usr/bin/env bash
# Build app/dist/ReefScanner.dmg — the downloadable Mac app.
#
#   app/scripts/build_app.sh
#
# Builds from a clean uv-managed standalone Python, never the dev venv, so
# nothing from the developer's machine (Anaconda, Homebrew) leaks into the app.
# Needs: uv, node/npm, and the dev workspace synced (`uv sync` at the repo
# root), whose ultralytics extra exports SharkTrack to ONNX. The app itself
# ships without torch.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="build/venv"
PY="$VENV/bin/python"
WEIGHTS="build/weights/sharktrack.onnx"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"

step() { printf '\n==> %s\n' "$*"; }

step "Build environment (standalone Python from .python-version)"
if [ ! -x "$PY" ]; then
  uv venv --managed-python --python "$(cat "$ROOT/../.python-version")" "$VENV"
fi
uv pip install --python "$PY" -e ../core -e ".[desktop]" imageio-ffmpeg pyinstaller

step "Review UI"
(cd frontend && npm ci && npm run build)

step "Detector model (SharkTrack, exported to ONNX)"
if [ ! -s "$WEIGHTS" ]; then
  (cd "$ROOT/.." && uv run reefscanner export-onnx --out "$ROOT/$WEIGHTS")
fi

step "Package ReefScanner.app"
REEFSCANNER_BUNDLE_WEIGHTS="$ROOT/$WEIGHTS" REEFSCANNER_VERSION="$VERSION" \
  "$VENV/bin/pyinstaller" --noconfirm --clean \
    --distpath dist --workpath build/pyinstaller \
    packaging/reefscanner.spec

step "Disk image"
STAGE="build/dmg"
rm -rf "$STAGE" dist/ReefScanner.dmg
mkdir -p "$STAGE"
cp -R dist/ReefScanner.app "$STAGE/"
# The Applications shortcut is what makes "drag the app across" obvious.
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "ReefScanner" -srcfolder "$STAGE" -ov -format UDZO \
  dist/ReefScanner.dmg >/dev/null

step "Done"
du -sh dist/ReefScanner.app dist/ReefScanner.dmg
