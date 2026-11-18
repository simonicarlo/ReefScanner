#!/usr/bin/env bash
# Compile AppIcon.icon (Icon Composer) into what the app bundle ships:
#
#   Assets.car    the layered icon: default, dark, clear and tinted (macOS 26+)
#   AppIcon.icns  a flat fallback for older macOS (the app supports 12+)
#
#   app/packaging/icon/make_icon.sh
#
# Needs Xcode 26 or later. The outputs are committed, so the release build
# doesn't depend on which Xcode the CI runner has; rerun this after editing
# the icon (in Icon Composer, or icon.json and Assets/ by hand) and commit.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

xcrun actool "$HERE/AppIcon.icon" \
  --compile "$OUT" \
  --app-icon AppIcon \
  --platform macosx \
  --minimum-deployment-target 12.0 \
  --output-partial-info-plist "$OUT/partial.plist" \
  --output-format human-readable-text --errors --warnings >/dev/null

# actool's own .icns stops at 256 px, which blurs in large Finder views on
# older macOS, so the fallback is rendered at every size from the Default look.
ICTOOL="$(xcode-select -p)/../Applications/Icon Composer.app/Contents/Executables/ictool"
SET="$OUT/AppIcon.iconset"
mkdir -p "$SET"
for size in 16 32 128 256 512; do
  for scale in 1 2; do
    suffix=""; [ "$scale" = 2 ] && suffix="@2x"
    "$ICTOOL" "$HERE/AppIcon.icon" --export-image --platform macOS --rendition Default \
      --width "$size" --height "$size" --scale "$scale" \
      --output-file "$SET/icon_${size}x${size}${suffix}.png" >/dev/null
  done
done
iconutil -c icns "$SET" -o "$OUT/AppIcon.icns"

cp "$OUT/Assets.car" "$OUT/AppIcon.icns" "$HERE/"
echo "Wrote $HERE/Assets.car and $HERE/AppIcon.icns"
