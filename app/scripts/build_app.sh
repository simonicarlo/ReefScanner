#!/usr/bin/env bash
# Build app/dist/ReefScanner.dmg — the downloadable Mac app — and
# app/dist/velopack/, the Velopack release the app updates itself from.
#
#   app/scripts/build_app.sh
#
# Builds from a clean uv-managed standalone Python, never the dev venv, so
# nothing from the developer's machine (Anaconda, Homebrew) leaks into the app,
# with package versions taken from uv.lock (the root's `build` group).
# Needs: uv, node/npm and Velopack's vpk (on PATH, or set VPK; it runs on
# .NET, `brew install dotnet@10`). The app ships without torch; the detector
# is the published SharkTrack ONNX export, downloaded and hash-checked.
#
# Signing and notarization happen only when these are set (CI sets them; see
# docs/specs/v3/features/2026-11-18-distribution-design.md):
#   REEFSCANNER_SIGN_IDENTITY   Developer ID Application identity (name or SHA-1)
#   NOTARY_KEY_PATH, NOTARY_KEY_ID, NOTARY_ISSUER_ID   App Store Connect API key
#   VPK_NOTARY_PROFILE, VPK_KEYCHAIN   the same key as a notarytool profile, for vpk
# Without them the app is ad-hoc signed, as a local build always was.
#
# With VPK_PREVIOUS_DIR set to a folder holding the latest published release
# (CI fetches it with `vpk download github`), vpk adds a delta package to it.
# See docs/specs/v3/features/2026-11-18-self-update-design.md.
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

step "Velopack CLI matches the app's velopack"
# vpk writes the release and the velopack package reads it inside the app;
# Velopack requires the same version on both sides. uv.lock decides it, and
# CI installs vpk from there; this catches a local vpk left behind.
VPK="${VPK:-vpk}"
vpk_version="$({ "$VPK" -x --skip-updates pack 2>&1 || true; } \
  | sed -n 's/.*Velopack CLI \([^,]*\),.*/\1/p' | head -1)"
lib_version="$("$PY" -c 'from importlib.metadata import version; print(version("velopack"))')"
if [ "$vpk_version" != "$lib_version" ]; then
  echo "error: vpk is ${vpk_version:-missing}, but uv.lock has velopack $lib_version." >&2
  echo "       dotnet tool update -g vpk --version $lib_version" >&2
  exit 1
fi
echo "vpk and velopack: $lib_version"

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

rm -rf dist/ReefScanner.dmg dist/velopack build/velopack-app
if [ -n "${VPK_PREVIOUS_DIR:-}" ] && [ -d "$VPK_PREVIOUS_DIR" ]; then
  step "Previous release (for the delta package)"
  mkdir -p dist/velopack
  cp -R "$VPK_PREVIOUS_DIR"/. dist/velopack/
fi

step "Velopack release${IDENTITY:+ (signed${VPK_NOTARY_PROFILE:+, notarized})}"
# Velopack adds its updater (Contents/MacOS/UpdateMac) to the bundle, so it
# signs and notarizes the app itself. It insists on the .entitlements suffix.
cp packaging/entitlements.plist build/reefscanner.entitlements
vpk_sign=()
if [ -n "$IDENTITY" ]; then
  vpk_sign=(--signAppIdentity "$IDENTITY" --signEntitlements build/reefscanner.entitlements)
fi
"$VPK" --skip-updates -x pack --packId ReefScanner --packVersion "$VERSION" \
  --packDir dist/ReefScanner.app --mainExe ReefScanner --packTitle ReefScanner \
  --noInst --outputDir dist/velopack ${vpk_sign[@]+"${vpk_sign[@]}"}
# Velopack's output reached by people (the DMG) must be the same app, updater
# included, or an app installed from the DMG could never update itself.
mkdir -p build/velopack-app
ditto -x -k dist/velopack/ReefScanner-osx-Portable.zip build/velopack-app
APP=build/velopack-app/ReefScanner.app
if [ -z "$IDENTITY" ]; then
  # Unsigned, vpk adds its updater without re-signing; seal it ad hoc again.
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"

step "Disk image"
# The window layout (app, Applications shortcut, arrow background) is in
# packaging/dmg/settings.py; dmgbuild writes it without driving Finder.
"$VENV/bin/dmgbuild" -s packaging/dmg/settings.py -D app="$APP" \
  -D background=packaging/dmg/background.tiff -D icon=packaging/icon/AppIcon.icns \
  "ReefScanner" dist/ReefScanner.dmg

if [ -n "$IDENTITY" ]; then
  step "Sign and notarize the disk image"
  codesign --sign "$IDENTITY" --timestamp dist/ReefScanner.dmg
  notarize dist/ReefScanner.dmg
  xcrun stapler staple dist/ReefScanner.dmg
  spctl --assess --type open --context context:primary-signature -v dist/ReefScanner.dmg
  spctl --assess --type execute -v "$APP"
  xcrun stapler validate "$APP"
fi

step "Done ($VERSION)"
du -sh "$APP" dist/ReefScanner.dmg dist/velopack/*
