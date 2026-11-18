#!/usr/bin/env bash
# Set the release version everywhere it is written down.
#
#   app/scripts/set_version.sh 1.0.1        (or 1.1.0-rc.1 for a prerelease)
#
# The release workflow refuses a tag that doesn't match these. It also locks
# every migration not yet released (migrations/released.txt).
set -euo pipefail

VERSION="${1:?usage: set_version.sh <version, e.g. 1.0.1 or 1.1.0-rc.1>}"
# SemVer, because Velopack orders updates by it: a release candidate is
# 1.1.0-rc.1, not PEP 440's 1.1.0rc1 (Python reads both the same).
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$ ]]; then
  echo "error: '$VERSION' isn't a version like 1.0.1 or 1.1.0-rc.1" >&2
  exit 2
fi

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" \
  "$REPO/app/pyproject.toml" "$REPO/core/pyproject.toml" "$REPO/edge/pyproject.toml"
sed -i '' "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" \
  "$REPO/core/src/reefscanner/core/__init__.py"
(cd "$REPO" && uv lock --quiet)
echo "Version set to $VERSION"

# Lock the migrations this release ships: from now on they may not change.
MIGRATIONS="$REPO/app/src/reefscanner/app/migrations"
LOCK="$MIGRATIONS/released.txt"
for file in "$MIGRATIONS"/versions/*.py; do
  rel="versions/$(basename "$file")"
  if ! grep -q "  $rel\$" "$LOCK"; then
    (cd "$MIGRATIONS" && shasum -a 256 "$rel") >> "$LOCK"
    echo "Locked migration $rel"
  fi
done
