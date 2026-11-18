#!/usr/bin/env bash
# Build app/dist/ReefScanner.dmg — the downloadable Mac app — and
# app/dist/ReefScanner-macOS.zip, the bare .app the self-updater fetches.
#
#   app/scripts/build_app.sh
#
# Builds from a clean uv-managed standalone Python, never the dev venv, so
# nothing from the developer's machine (Anaconda, Homebrew) leaks into the app,
# with package versions taken from uv.lock (the root's `build` group).
# Needs: uv and node/npm. The app ships without torch; the detector is the
# published SharkTrack ONNX export, downloaded and hash-checked.
#
# Signing and notarization happen only when these are set (CI sets them; see
# docs/specs/v3/features/2026-11-18-distribution-design.md):
#   REEFSCANNER_SIGN_IDENTITY   Developer ID Application identity (name or SHA-1)
#   NOTARY_KEY_PATH, NOTARY_KEY_ID, NOTARY_ISSUER_ID   App Store Connect API key
# Without them the app is ad-hoc signed, as a local build always was.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="build/venv"
PY="$VENV/bin/python"
WEIGHTS="build/weights/sharktrack.onnx"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
IDENTITY="${REEFSCANNER_SIGN_IDENTITY:-}"

step() { printf '\n==> %s\n' "$*"; }

# Submit a file to Apple's notary service and fail the build unless accepted.
notarize() {
  local file="$1" out status id
  out="$(xcrun notarytool submit "$file" --wait --output-format json \
    --key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER_ID")"
  status="$(printf '%s' "$out" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  if [ "$status" != "Accepted" ]; then
    id="$(printf '%s' "$out" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
    echo "Notarization of $file: $status" >&2
    xcrun notarytool log "$id" \
      --key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER_ID" >&2
    exit 1
  fi
}

step "Build environment (standalone Python, versions from uv.lock)"
# Exactly the versions the tests ran against: the root's `build` group, frozen
# from the lockfile, never re-resolved at build time.
(cd "$ROOT/.." && UV_PROJECT_ENVIRONMENT="$ROOT/$VENV" \
  uv sync --frozen --managed-python --no-default-groups --group build)

step "Review UI"
(cd frontend && npm ci && npm run build)

step "Detector model (SharkTrack as ONNX, published and hash-checked)"
if [ ! -s "$WEIGHTS" ]; then
  mkdir -p "$(dirname "$WEIGHTS")"
  cp "$("$PY" -c 'from reefscanner.core.weights import ensure_sharktrack_onnx; print(ensure_sharktrack_onnx())')" "$WEIGHTS"
fi

step "Package ReefScanner.app${IDENTITY:+ (signed)}"
REEFSCANNER_BUNDLE_WEIGHTS="$ROOT/$WEIGHTS" REEFSCANNER_VERSION="$VERSION" \
  "$VENV/bin/pyinstaller" --noconfirm --clean \
    --distpath dist --workpath build/pyinstaller \
    packaging/reefscanner.spec
codesign --verify --deep --strict dist/ReefScanner.app

rm -f dist/ReefScanner-macOS.zip dist/ReefScanner.dmg
if [ -n "$IDENTITY" ]; then
  step "Notarize the app"
  # Stapled to the app itself, so a first launch in the field works offline.
  ditto -c -k --keepParent dist/ReefScanner.app build/notarize-app.zip
  notarize build/notarize-app.zip
  xcrun stapler staple dist/ReefScanner.app
fi
ditto -c -k --keepParent dist/ReefScanner.app dist/ReefScanner-macOS.zip

step "Disk image"
# The window layout (app, Applications shortcut, arrow background) is in
# packaging/dmg/settings.py; dmgbuild writes it without driving Finder.
"$VENV/bin/dmgbuild" -s packaging/dmg/settings.py -D app=dist/ReefScanner.app \
  -D background=packaging/dmg/background.tiff -D icon=packaging/icon/AppIcon.icns \
  "ReefScanner" dist/ReefScanner.dmg

if [ -n "$IDENTITY" ]; then
  step "Sign and notarize the disk image"
  codesign --sign "$IDENTITY" --timestamp dist/ReefScanner.dmg
  notarize dist/ReefScanner.dmg
  xcrun stapler staple dist/ReefScanner.dmg
  spctl --assess --type open --context context:primary-signature -v dist/ReefScanner.dmg
  spctl --assess --type execute -v dist/ReefScanner.app
fi

step "Done ($VERSION)"
du -sh dist/ReefScanner.app dist/ReefScanner-macOS.zip dist/ReefScanner.dmg
