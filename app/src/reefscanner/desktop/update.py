"""Self-update: Velopack does the work, the app checks who signed it.

See docs/specs/v3/features/2026-11-18-self-update-design.md.

The flow, each step started by the one before or by the user:

    checking → available → (user) downloading → verifying → ready → (user) restart
        ↘ none                       ↘ failed ↙

Velopack finds the newest release on GitHub, downloads the full package or a
delta (rebuilt into a full package), and checks it against the SHA-256 in the
release's feed. That catches a damaged or swapped file, but the hash comes
from the same release as the package, so it says nothing about who built it,
and macOS doesn't check either: Velopack's downloads carry no quarantine
flag. So on the Mac the package is unpacked and must be signed with our Team
ID before it may be applied, which mostly guards against our own mistake of
publishing an unsigned build.

Nothing here updates on its own. A failed check is only logged (in the field
the laptop is usually offline); a failed download or signature check offers
the download page instead. Velopack, left to its defaults, would install a
downloaded package at the next launch without asking and without our check,
so that is switched off (``run_velopack_hooks``) and a package that fails the
check is deleted at once.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("reefscanner.desktop.update")

REPO_URL = "https://github.com/simonicarlo/ReefScanner"
#: Where someone goes when the app can't update itself.
DOWNLOAD_URL = f"{REPO_URL}/releases/latest"
#: Set to include prereleases, for trying a release candidate before testers.
PRERELEASE_ENV = "REEFSCANNER_UPDATE_PRERELEASE"

TEAM_ID = "T5M8S8M8ZT"
BUNDLE_ID = "io.github.simonicarlo.reefscanner"
#: What `codesign` must find on the downloaded app: Apple's chain, our bundle,
#: our Developer ID team.
CODE_REQUIREMENT = (
    f'anchor apple generic and identifier "{BUNDLE_ID}" '
    f'and certificate leaf[subject.OU] = "{TEAM_ID}"'
)

#: Inside a Velopack package the app sits under this folder.
_APP_PREFIX = "lib/app/"
#: Velopack stores a symlink as a file named like this, holding the target
#: (with a trailing "/" for a directory).
_SYMLINK_SUFFIX = ".__symlink"
#: Generous: a deep check of a 300 MB bundle takes a few seconds.
_CODESIGN_TIMEOUT_S = 300

State = Literal[
    "off", "checking", "none", "available", "downloading", "verifying", "ready", "failed"
]


class UpdateError(RuntimeError):
    """A downloaded update can't be used."""


def run_velopack_hooks() -> None:
    """Velopack's startup hook, first thing in the packaged app.

    When Velopack starts the app for an install or update event, this handles
    it and exits. Applying a downloaded update on startup is turned off: the
    only way in is ``Updater.apply_on_exit``, after the signature check.
    """
    import velopack

    velopack.App().set_auto_apply_on_startup(False).run()


def unpack_app(package: Path, dest: Path) -> Path:
    """Unpack the app inside a Velopack package to ``dest`` and return it.

    The package isn't trusted until ``codesign`` accepts what this unpacks,
    and Velopack unpacks it again to install it, so both must see the same
    files: a name that appears twice anywhere in the package (also differing
    only in case or Unicode form, which macOS doesn't tell apart), a
    backslash, or a path not in plain form refuses the package.
    Every path, and every link's target, must stay inside ``dest``. Links
    are made last, never in a folder reached through another link, and each
    must still resolve inside ``dest`` once all exist.
    """
    dest.mkdir(parents=True)
    root = dest.resolve()
    seen: set[str] = set()
    links: list[tuple[Path, str]] = []
    with zipfile.ZipFile(package) as archive:
        for entry in archive.infolist():
            name = entry.filename
            # Every entry, not only the app's: a name like "./lib/app/x" is
            # skipped here but could be read as part of the app by Velopack.
            if not _is_plain(name.removesuffix("/")):
                raise UpdateError(f"The update contains an unusual path: {name}")
            # Compared as the Mac's file system would: case and Unicode form
            # don't matter, and a link counts as the file it becomes.
            key = _fold(name.removesuffix("/").removesuffix(_SYMLINK_SUFFIX))
            if key in seen:
                raise UpdateError(f"The update contains {name} twice")
            seen.add(key)
            if not name.startswith(_APP_PREFIX):
                if key.startswith(_fold(_APP_PREFIX)):
                    raise UpdateError(f"The update contains an unusual path: {name}")
                continue
            if entry.is_dir():
                continue
            relative = name[len(_APP_PREFIX):]
            path = relative.removesuffix(_SYMLINK_SUFFIX)

            target = root / path
            if relative.endswith(_SYMLINK_SUFFIX):
                link_target = archive.read(entry).decode().rstrip("/")
                pointed = Path(os.path.normpath(target.parent / link_target))
                if os.path.isabs(link_target) or not pointed.is_relative_to(root):
                    raise UpdateError(f"The update links outside the app: {name}")
                links.append((target, link_target))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            mode = (entry.external_attr >> 16) & 0o777
            if mode:
                target.chmod(mode)

    for link, link_target in links:
        _refuse_links_on_the_way(root, link.parent)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(link_target)
    for link, _ in links:
        # Each target was inside on its own; chained, links can still leave.
        if not Path(os.path.realpath(link)).is_relative_to(root):
            raise UpdateError(f"The update links outside the app: {link.relative_to(root)}")
    return dest


def _fold(name: str) -> str:
    """A name as APFS compares it: case- and normalization-insensitive."""
    return unicodedata.normalize("NFD", name).casefold()


def _is_plain(relative: str) -> bool:
    """A relative path with no empty, "." or ".." parts and no backslashes
    (so not starting with "/" either)."""
    parts = relative.split("/")
    return "\\" not in relative and all(part not in ("", ".", "..") for part in parts)


def _refuse_links_on_the_way(root: Path, folder: Path) -> None:
    """Raise if any existing folder between ``root`` and ``folder`` is a link,
    so making a link there can't write outside ``root``."""
    current = root
    for part in folder.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise UpdateError(f"The update puts a link inside a link: {folder.relative_to(root)}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(package: Path) -> None:
    """Raise ``UpdateError`` unless the package's app is signed by us.

    Mac only for now. Windows gets the same check (Authenticode signer) once
    its build is signed; until then, as on Linux, Velopack's hash is all.
    """
    if sys.platform != "darwin":
        logger.warning("No signature check for updates on %s yet", sys.platform)
        return
    with tempfile.TemporaryDirectory(prefix="reefscanner-update-") as tmp:
        app = unpack_app(package, Path(tmp) / "ReefScanner.app")
        result = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", f"-R={CODE_REQUIREMENT}", str(app)],
            capture_output=True, text=True, timeout=_CODESIGN_TIMEOUT_S, check=False,
        )
    if result.returncode != 0:
        raise UpdateError(
            f"The update isn't signed by ReefScanner's developer ({TEAM_ID}): "
            f"{result.stderr.strip()}"
        )


def packages_dir(app_id: str) -> Path:
    """Where Velopack keeps downloaded packages (its locator's default)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "velopack" / app_id / "packages"
    raise UpdateError(f"Don't know where Velopack keeps packages on {sys.platform}")


class Updater:
    """The update's state, shared by the background threads and the window.

    ``manager`` is a ``velopack.UpdateManager``, or None where updating isn't
    possible (running from source, or a build not packaged by Velopack).
    """

    def __init__(
        self,
        manager: Any | None,
        verify: Callable[[Path], None] = verify_package,
        find_package: Callable[[Any, Any], Path] | None = None,
    ) -> None:
        self._manager = manager
        self._verify = verify
        self._find_package = find_package or _cached_package
        self._lock = threading.Lock()
        self._state: State = "off" if manager is None else "none"
        self._info: Any | None = None
        self._progress = 0
        #: The package that passed the check, and its SHA-256 then: it must
        #: be the same file when it is handed to Velopack.
        self._verified: tuple[Path, str] | None = None

    @classmethod
    def for_this_app(cls) -> Updater:
        """The updater for the running app; off unless it was installed by Velopack."""
        if not getattr(sys, "frozen", False):
            return cls(None)
        try:
            import velopack

            source = velopack.GithubSource(
                REPO_URL, prerelease=bool(os.environ.get(PRERELEASE_ENV))
            )
            return cls(velopack.UpdateManager(source))
        except Exception:
            # Velopack raises plain exceptions, e.g. for an app it didn't package.
            logger.exception("Updates are off: Velopack couldn't start")
            return cls(None)

    def status(self) -> dict[str, Any]:
        with self._lock:
            target = self._info.TargetFullRelease.Version if self._info is not None else None
            return {"state": self._state, "version": target, "progress": self._progress}

    # -- checking ------------------------------------------------------------
    def start_check(self) -> None:
        if self._manager is None:
            return
        self._set("checking")
        threading.Thread(target=self.check, name="reefscanner-update-check", daemon=True).start()

    def check(self) -> None:
        """Ask the release feed for a newer version."""
        try:
            info = self._manager.check_for_updates()
        except Exception:
            # Usually just offline. Logged, never shown.
            logger.warning("Update check failed", exc_info=True)
            self._set("none")
            return
        if info is None:
            logger.info("ReefScanner is up to date")
            self._set("none")
            return
        logger.info("Update available: %s", info.TargetFullRelease.Version)
        with self._lock:
            self._info = info
        self._set("available")

    # -- downloading -----------------------------------------------------------
    def start_download(self) -> bool:
        """Download and verify the update in the background, if one is waiting."""
        with self._lock:
            if self._state not in ("available", "failed") or self._info is None:
                return False
            self._state, self._progress = "downloading", 0
        threading.Thread(target=self.download, name="reefscanner-update-download", daemon=True).start()
        return True

    def download(self) -> None:
        info = self._info
        package: Path | None = None
        try:
            self._manager.download_updates(info, self._on_progress)
            self._set("verifying")
            package = self._find_package(self._manager, info)
            self._verify(package)
            verified = (package, _sha256(package))
        except Exception:
            # Velopack's own errors (network, hash mismatch) and ours alike: the
            # user gets the download page, the log gets the reason.
            logger.exception("Update to %s failed", info.TargetFullRelease.Version)
            if package is not None:
                # Never leave an unverified package where Velopack looks for one.
                package.unlink(missing_ok=True)
            self._set("failed")
            return
        logger.info("Update %s downloaded and verified", info.TargetFullRelease.Version)
        with self._lock:
            self._verified = verified
            self._state = "ready"

    def _on_progress(self, percent: int) -> None:
        with self._lock:
            self._progress = int(percent)

    # -- applying --------------------------------------------------------------
    def apply_on_exit(self) -> bool:
        """Have Velopack install the verified update once this process exits.

        Velopack starts a helper that waits for the exit, swaps the app and
        starts the new version. False if there is nothing verified to apply.
        """
        with self._lock:
            if self._state != "ready" or self._info is None or self._verified is None:
                return False
            package, sha256 = self._verified
        if not package.is_file() or _sha256(package) != sha256:
            logger.error("The verified update at %s changed before it was applied", package)
            package.unlink(missing_ok=True)
            self._set("failed")
            return False
        try:
            self._manager.wait_exit_then_apply_updates(self._info, silent=True, restart=True)
        except Exception:
            logger.exception("Couldn't hand the update to Velopack")
            self._set("failed")
            return False
        return True

    def _set(self, state: State) -> None:
        with self._lock:
            self._state = state


def _cached_package(manager: Any, info: Any) -> Path:
    """The full package Velopack just downloaded (or rebuilt from a delta)."""
    package = packages_dir(manager.get_app_id()) / info.TargetFullRelease.FileName
    if not package.is_file():
        raise UpdateError(f"Downloaded update not found at {package}")
    return package
