"""Tests for `reef`, the developer commands (tools/reef).

What matters most is `reef release`: a tag can't be moved or deleted, so it
must refuse anything that would tag the wrong thing, and write the version
everywhere it is written down. Git runs for real, against a throwaway repo
with a local "origin"; nothing touches the network.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from reef import release
from reef.release import Version
from reef.repo import ReefError, Repo, find_repo


# -- versions ----------------------------------------------------------------------

def test_versions_are_semver_as_velopack_orders_them() -> None:
    order = ["1.0.0", "1.1.0-rc.1", "1.1.0-rc.2", "1.1.0-rc.10", "1.1.0", "1.1.1", "2.0.0"]
    parsed = [Version.parse(v) for v in order]
    assert sorted(reversed(parsed)) == parsed
    assert str(Version.parse("v1.1.0-rc.4")) == "1.1.0-rc.4"
    assert Version.parse("1.1.0-rc.1").is_prerelease
    assert not Version.parse("1.1.0").is_prerelease


@pytest.mark.parametrize("text", ["1.1", "1.1.0rc1", "1.1.0-", "latest"])
def test_a_version_velopack_cant_order_is_refused(text: str) -> None:
    with pytest.raises(ReefError, match="isn't a version"):
        Version.parse(text)


# -- a throwaway copy of the repo ------------------------------------------------------

def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """A minimal ReefScanner layout at 1.0.0 on main, pushed to a local origin."""
    root = tmp_path / "repo"
    files = {
        "pyproject.toml": "[tool.uv.workspace]\nmembers = []\n",
        "app/pyproject.toml": '[project]\nname = "reefscanner-app"\nversion = "1.0.0"\n'
                              'dependencies = ["x"]\n\n[tool.other]\nversion = "9.9.9"\n',
        "core/pyproject.toml": '[project]\nname = "reefscanner-core"\nversion = "1.0.0"\n',
        "edge/pyproject.toml": '[project]\nname = "reefscanner-edge"\nversion = "1.0.0"\n',
        "core/src/reefscanner/core/__init__.py": '"""Core."""\n\n__version__ = "1.0.0"\n',
        "app/src/reefscanner/app/migrations/versions/0001_initial_db.py": "# first\n",
        "app/src/reefscanner/app/migrations/released.txt": "",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    first = root / "app/src/reefscanner/app/migrations/versions/0001_initial_db.py"
    lock = root / "app/src/reefscanner/app/migrations/released.txt"
    lock.write_text(
        "# Released migrations, locked: SHA-256 and path.\n"
        f"{hashlib.sha256(first.read_bytes()).hexdigest()}  versions/0001_initial_db.py\n"
    )

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True)
    _git(root.parent, "init", "-q", "-b", "main", str(root))
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-q", "origin", "main")
    return Repo(root)


# -- what a release writes -------------------------------------------------------------

def test_the_version_is_written_everywhere_and_nowhere_else(repo: Repo) -> None:
    release.write_version(repo, Version.parse("1.1.0"))

    assert release.current_version(repo) == Version.parse("1.1.0")
    for name in ("app/pyproject.toml", "core/pyproject.toml", "edge/pyproject.toml"):
        assert 'version = "1.1.0"' in (repo.root / name).read_text()
    assert '__version__ = "1.1.0"' in (repo.root / "core/src/reefscanner/core/__init__.py").read_text()
    # Only each file's own version: another table's "version" stays.
    assert 'version = "9.9.9"' in (repo.root / "app/pyproject.toml").read_text()


def test_new_migrations_are_locked_and_released_ones_stay(repo: Repo) -> None:
    new = repo.migrations / "versions" / "0002_add_things.py"
    new.write_text("# second\n")

    assert release.lock_migrations(repo) == ["versions/0002_add_things.py"]
    lines = (repo.migrations / "released.txt").read_text().splitlines()
    assert lines[-1] == f"{hashlib.sha256(new.read_bytes()).hexdigest()}  versions/0002_add_things.py"
    assert len(lines) == 3, "the comment and 0001 stay as they were"
    assert release.lock_migrations(repo) == [], "locking twice adds nothing"


# -- what a release refuses --------------------------------------------------------------

def test_a_release_on_main_level_with_origin_is_allowed(repo: Repo) -> None:
    assert release.check_ready(repo, Version.parse("1.1.0")) == Version.parse("1.0.0")


def test_a_release_from_another_branch_is_refused(repo: Repo) -> None:
    """rc.3 was once tagged on a feature branch and built without the fixes on main."""
    _git(repo.root, "switch", "-q", "-c", "feature")
    with pytest.raises(ReefError, match="made from main"):
        release.check_ready(repo, Version.parse("1.1.0"))


def test_a_release_with_uncommitted_changes_is_refused(repo: Repo) -> None:
    (repo.root / "core/pyproject.toml").write_text("changed\n")
    with pytest.raises(ReefError, match="uncommitted"):
        release.check_ready(repo, Version.parse("1.1.0"))


def test_a_release_with_unpushed_commits_is_refused(repo: Repo) -> None:
    (repo.root / "notes.txt").write_text("x\n")
    _git(repo.root, "add", "notes.txt")
    _git(repo.root, "commit", "-q", "-m", "local only")
    with pytest.raises(ReefError, match="level with origin/main"):
        release.check_ready(repo, Version.parse("1.1.0"))


def test_a_version_that_isnt_newer_is_refused(repo: Repo) -> None:
    for version in ("1.0.0", "0.9.0", "1.0.0-rc.1"):
        with pytest.raises(ReefError, match="isn't newer"):
            release.check_ready(repo, Version.parse(version))


def test_a_tag_that_exists_is_refused(repo: Repo) -> None:
    _git(repo.root, "tag", "v1.1.0")
    with pytest.raises(ReefError, match="already exists"):
        release.check_ready(repo, Version.parse("1.1.0"))


def test_reef_finds_the_repo_from_any_folder_inside_it(repo: Repo) -> None:
    assert find_repo(repo.root / "core" / "src").root == repo.root
    with pytest.raises(ReefError, match="Not inside"):
        find_repo(repo.root.parent)
