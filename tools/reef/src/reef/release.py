"""`reef release X.Y.Z`: set the version, commit, tag and push.

Pushing the tag starts `.github/workflows/release.yml`, which builds, signs,
notarizes and publishes. A tag can't be moved or deleted (the repo's tag
rules), so everything that could make it wrong is checked first: the branch,
the tree, the version, and the tests.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .repo import ReefError, Repo, capture

#: SemVer, as Velopack orders updates by it: 1.1.0, or 1.1.0-rc.1 for a
#: release candidate (not PEP 440's 1.1.0rc1; Python reads both the same).
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*))?")

#: Where the version is written down; the first match in each file is it.
VERSION_FILES = {
    "app/pyproject.toml": re.compile(r'^version = "(.*)"$', re.M),
    "core/pyproject.toml": re.compile(r'^version = "(.*)"$', re.M),
    "edge/pyproject.toml": re.compile(r'^version = "(.*)"$', re.M),
    "core/src/reefscanner/core/__init__.py": re.compile(r'^__version__ = "(.*)"$', re.M),
}


@dataclass(frozen=True, order=False)
class Version:
    major: int
    minor: int
    patch: int
    pre: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> Version:
        found = _SEMVER.fullmatch(text.strip().removeprefix("v"))
        if not found:
            raise ReefError(
                f"'{text}' isn't a version like 1.1.0, or 1.1.0-rc.1 for a release candidate."
            )
        major, minor, patch, pre = found.groups()
        return cls(int(major), int(minor), int(patch), tuple(pre.split(".")) if pre else ())

    @property
    def is_prerelease(self) -> bool:
        return bool(self.pre)

    def _key(self) -> tuple:
        # SemVer: a release ranks above its prereleases; numeric identifiers
        # compare as numbers and rank below text ones.
        pre = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in self.pre)
        return (self.major, self.minor, self.patch, 0 if self.pre else 1, pre)

    def __lt__(self, other: Version) -> bool:
        return self._key() < other._key()

    def __str__(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        return f"{core}-{'.'.join(self.pre)}" if self.pre else core


def current_version(repo: Repo) -> Version:
    text = (repo.root / "app" / "pyproject.toml").read_text()
    return Version.parse(VERSION_FILES["app/pyproject.toml"].search(text).group(1))


def write_version(repo: Repo, version: Version) -> list[str]:
    """Write ``version`` everywhere it is written down; returns the files."""
    changed = []
    for name, pattern in VERSION_FILES.items():
        path = repo.root / name
        text = path.read_text()
        found = pattern.search(text)
        if not found:
            raise ReefError(f"No version found in {name}")
        start, end = found.span(1)
        path.write_text(text[:start] + str(version) + text[end:])
        changed.append(name)
    return changed


def lock_migrations(repo: Repo) -> list[str]:
    """Append every migration not yet in ``released.txt`` with its SHA-256.

    From this release on they have run on someone's database and must never
    change (``test_released_migrations_are_unchanged`` enforces it).
    """
    lock = repo.migrations / "released.txt"
    text = lock.read_text() if lock.exists() else ""
    listed = {
        line.split(maxsplit=1)[1]
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }
    if text and not text.endswith("\n"):
        text += "\n"
    added = []
    for path in sorted((repo.migrations / "versions").glob("*.py")):
        rel = f"versions/{path.name}"
        if rel not in listed:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            text += f"{digest}  {rel}\n"
            added.append(rel)
    if added:
        lock.write_text(text)
    return added


def git(repo: Repo, *args: str) -> str:
    code, out = capture(["git", *args], repo.root)
    if code != 0:
        raise ReefError(f"git {' '.join(args)} failed:\n{out}")
    return out


def check_ready(repo: Repo, version: Version) -> Version:
    """Refuse anything that would tag the wrong thing; returns the current version."""
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise ReefError(f"Releases are made from main, but this is {branch}.\n  → git switch main")
    if git(repo, "status", "--porcelain"):
        raise ReefError("There are uncommitted changes.\n  → commit or stash them first")
    git(repo, "fetch", "--quiet", "--tags", "origin", "main")
    if git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", "origin/main"):
        raise ReefError("main isn't level with origin/main.\n  → git pull (or push your commits)")

    current = current_version(repo)
    if not current < version:
        raise ReefError(f"{version} isn't newer than the current version, {current}.")
    tag = f"v{version}"
    if git(repo, "tag", "--list", tag):
        raise ReefError(f"The tag {tag} already exists, and tags can't be reused. Pick the next version.")
    return current
