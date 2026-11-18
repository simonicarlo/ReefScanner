"""Tests for self-update (``reefscanner.desktop.update`` and the bridge).

Velopack is replaced by a fake manager and the signature check by a stub:
what matters here is that nothing is applied unless the download was
verified, that the app never restarts under a running scan, and that an
untrusted package can't write outside the folder it is unpacked into. The
real ``codesign`` check against a signed package was tried by hand (see the
design note); it needs a release build, not the test suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path

import pytest

from reefscanner.desktop import main as desktop
from reefscanner.desktop import update
from reefscanner.desktop.update import UpdateError, Updater, unpack_app


def _info(version: str = "1.2.0") -> types.SimpleNamespace:
    asset = types.SimpleNamespace(Version=version, FileName=f"ReefScanner-{version}-osx-full.nupkg")
    return types.SimpleNamespace(TargetFullRelease=asset)


class FakeManager:
    """Stands in for ``velopack.UpdateManager``."""

    def __init__(self, info=None, check_error: Exception | None = None,
                 download_error: Exception | None = None) -> None:
        self.info = info
        self.check_error = check_error
        self.download_error = download_error
        self.applied = None

    def check_for_updates(self):
        if self.check_error:
            raise self.check_error
        return self.info

    def download_updates(self, info, progress) -> None:
        progress(50)
        if self.download_error:
            raise self.download_error
        progress(100)

    def wait_exit_then_apply_updates(self, info, silent: bool, restart: bool) -> None:
        self.applied = (info, silent, restart)

    def get_app_id(self) -> str:
        return "ReefScanner"


def _updater(manager: FakeManager, verify=lambda _package: None) -> Updater:
    """An updater whose "downloaded package" is a real (dummy) file."""
    fd, name = tempfile.mkstemp(suffix=".nupkg")
    os.write(fd, b"package")
    os.close(fd)
    return Updater(manager, verify=verify, find_package=lambda _m, _i: Path(name))


# -- checking ------------------------------------------------------------------

def test_running_from_source_never_checks() -> None:
    updater = Updater.for_this_app()  # the test run isn't frozen
    updater.start_check()
    assert updater.status()["state"] == "off"


def test_a_newer_release_is_offered() -> None:
    updater = _updater(FakeManager(_info("1.2.0")))
    updater.check()
    assert updater.status() == {
        "state": "available", "version": "1.2.0", "progress": 0, "prereleases": False,
    }


def test_being_offline_shows_nothing() -> None:
    """In the field the laptop is usually offline; that's not an error to show."""
    updater = _updater(FakeManager(check_error=RuntimeError("no network")))
    updater.check()
    assert updater.status()["state"] == "unreachable"


# -- downloading and verifying -------------------------------------------------

def _download_inline(updater: Updater) -> None:
    """Start the background download and wait until it settles."""
    assert updater.start_download() is True
    deadline = time.monotonic() + 5
    while updater.status()["state"] in ("downloading", "verifying"):
        assert time.monotonic() < deadline, "the download never finished"
        time.sleep(0.01)


def test_a_verified_download_is_ready_to_apply() -> None:
    updater = _updater(FakeManager(_info()))
    updater.check()
    _download_inline(updater)
    assert updater.status()["state"] == "ready"
    assert updater.status()["progress"] == 100


def test_a_package_that_fails_the_signature_check_is_never_applied() -> None:
    """The whole point of our own check: Velopack would install it."""
    manager = FakeManager(_info())

    def reject(_package: Path) -> None:
        raise UpdateError("not signed by us")

    updater = _updater(manager, verify=reject)
    updater.check()
    _download_inline(updater)

    assert updater.status()["state"] == "failed"
    assert updater.apply_on_exit() is False
    assert manager.applied is None


def test_a_failed_download_offers_the_download_page_and_can_be_retried() -> None:
    manager = FakeManager(_info(), download_error=RuntimeError("checksum mismatch"))
    updater = _updater(manager)
    updater.check()
    _download_inline(updater)
    assert updater.status()["state"] == "failed"

    manager.download_error = None
    _download_inline(updater)
    assert updater.status()["state"] == "ready"


def test_nothing_downloads_without_an_offered_update() -> None:
    updater = _updater(FakeManager(None))
    updater.check()
    assert updater.start_download() is False


def test_the_verified_update_is_handed_to_velopack_to_apply_after_exit() -> None:
    manager = FakeManager(_info())
    updater = _updater(manager)
    updater.check()
    _download_inline(updater)

    assert updater.apply_on_exit() is True
    info, silent, restart = manager.applied
    assert info.TargetFullRelease.Version == "1.2.0"
    assert silent and restart


def test_a_missing_package_in_velopacks_cache_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(update, "packages_dir", lambda _app_id: tmp_path)
    with pytest.raises(UpdateError, match="not found"):
        update._cached_package(FakeManager(), _info())


# -- unpacking an untrusted package --------------------------------------------

def _package(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ReefScanner.nuspec", "<package/>")
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_unpacking_restores_velopacks_symlinks(tmp_path) -> None:
    """Velopack stores links as files; left as files, the signature fails."""
    package = _package(tmp_path / "p.nupkg", {
        "lib/app/Contents/Frameworks/lib.dylib": "binary",
        "lib/app/Contents/Frameworks/WebKit/x": "data",
        "lib/app/Contents/Resources/lib.dylib.__symlink": "../Frameworks/lib.dylib",
        "lib/app/Contents/Resources/WebKit.__symlink": "../Frameworks/WebKit/",
    })
    app = unpack_app(package, tmp_path / "out" / "ReefScanner.app")

    file_link = app / "Contents/Resources/lib.dylib"
    dir_link = app / "Contents/Resources/WebKit"
    assert file_link.is_symlink() and file_link.read_text() == "binary"
    assert dir_link.is_symlink() and str(dir_link.readlink()) == "../Frameworks/WebKit"
    assert not (app / "ReefScanner.nuspec").exists(), "only the app is unpacked"


def test_unpacking_refuses_a_name_that_appears_twice(tmp_path) -> None:
    """Python and Velopack could each take a different copy: we'd check one
    app and install another. Case counts too: macOS doesn't tell them apart."""
    package = _package(tmp_path / "p.nupkg", {
        "lib/app/Contents/MacOS/ReefScanner": "signed",
        "lib/app/Contents/MacOS/reefscanner": "other",
    })
    with pytest.raises(UpdateError, match="twice"):
        unpack_app(package, tmp_path / "out" / "ReefScanner.app")


@pytest.mark.parametrize("entries", [
    # The same name in two Unicode forms (é composed, and e + combining accent).
    {"lib/app/Contents/caf\u00e9": "a", "lib/app/Contents/cafe\u0301": "b"},
    # A second copy of the app's folder that only differs in case.
    {"lib/app/Contents/x": "a", "LIB/APP/Contents/y": "b"},
    # Windows-style separators.
    {"lib\\app\\Contents\\x": "a"},
    # Names outside lib/app/ as written, inside it once tidied up.
    {"./lib/app/Contents/x": "a"},
    {"lib//app/Contents/x": "a"},
    {"other/../lib/app/Contents/x": "a"},
    {"/lib/app/Contents/x": "a"},
], ids=["unicode-forms", "case-of-prefix", "backslashes", "dot", "double-slash",
        "dot-dot", "absolute"])
def test_unpacking_refuses_names_the_installer_might_read_differently(tmp_path, entries) -> None:
    package = _package(tmp_path / "p.nupkg", entries)
    with pytest.raises(UpdateError):
        unpack_app(package, tmp_path / "out" / "ReefScanner.app")


def test_unpacking_refuses_a_link_that_points_outside_the_app(tmp_path) -> None:
    for target in ("/etc", "../../.."):
        package = _package(tmp_path / "p.nupkg", {"lib/app/Contents/x.__symlink": target})
        with pytest.raises(UpdateError, match="links outside"):
            unpack_app(package, tmp_path / "out" / f"{abs(hash(target))}.app")


def test_unpacking_never_writes_through_a_link(tmp_path) -> None:
    """A link to a folder, then a link inside it, would land outside."""
    outside = tmp_path / "outside"
    outside.mkdir()
    package = _package(tmp_path / "p.nupkg", {
        "lib/app/Contents/a.__symlink": "b",
        "lib/app/Contents/b/keep": "x",
        "lib/app/Contents/a/evil.__symlink": "../keep",
    })
    with pytest.raises(UpdateError, match="link inside a link"):
        unpack_app(package, tmp_path / "out" / "ReefScanner.app")


def test_unpacking_refuses_links_that_leave_the_app_when_chained(tmp_path) -> None:
    """Each target stays inside on paper; followed one after the other they don't."""
    package = _package(tmp_path / "p.nupkg", {
        "lib/app/d/c.__symlink": "..",
        "lib/app/d/b.__symlink": "c/../..",
    })
    with pytest.raises(UpdateError, match="links outside"):
        unpack_app(package, tmp_path / "out" / "ReefScanner.app")


def test_unpacking_refuses_paths_outside_the_app(tmp_path) -> None:
    package = _package(tmp_path / "p.nupkg", {"lib/app/../../escaped.txt": "x"})
    with pytest.raises(UpdateError, match="unusual path"):
        unpack_app(package, tmp_path / "out" / "ReefScanner.app")
    assert not (tmp_path / "escaped.txt").exists()


# -- the bridge ------------------------------------------------------------------

class FakeWindow:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


def _ready_bridge(busy: bool) -> tuple[desktop.Bridge, FakeManager, FakeWindow]:
    manager = FakeManager(_info())
    updater = _updater(manager)
    updater.check()
    _download_inline(updater)
    bridge = desktop.Bridge(updater, busy=lambda: busy)
    window = FakeWindow()
    bridge.attach(window)
    return bridge, manager, window


def test_restarting_is_refused_while_a_scan_runs() -> None:
    bridge, manager, window = _ready_bridge(busy=True)
    assert bridge.restart_to_update() == {"ok": False, "reason": "scanning"}
    assert manager.applied is None and not window.destroyed


def test_restarting_closes_the_window_only_after_answering_the_page() -> None:
    """Closing it inside the bridge call left pywebview waiting forever to hand
    the answer back, and the process never exited: Velopack waited 60 s."""
    bridge, manager, window = _ready_bridge(busy=False)
    assert bridge.restart_to_update() == {"ok": True}
    assert manager.applied is not None and bridge.restarting
    assert not window.destroyed, "closed while the call was still running"

    deadline = time.monotonic() + 5
    while not window.destroyed:
        assert time.monotonic() < deadline, "the window never closed"
        time.sleep(0.01)


def test_restarting_without_a_verified_update_does_nothing() -> None:
    bridge = desktop.Bridge(_updater(FakeManager(_info())), busy=lambda: False)
    window = FakeWindow()
    bridge.attach(window)
    assert bridge.restart_to_update() == {"ok": False, "reason": "failed"}
    assert not window.destroyed


# -- regressions found in the packaged app ---------------------------------------

def test_velopack_never_applies_a_download_on_startup_by_itself(monkeypatch) -> None:
    """Left at its default, Velopack installed a cached package at launch,
    without asking and without our signature check."""
    calls: list[tuple[str, object]] = []

    class FakeApp:
        def set_auto_apply_on_startup(self, apply: bool) -> "FakeApp":
            calls.append(("auto_apply", apply))
            return self

        def run(self) -> None:
            calls.append(("run", None))

    monkeypatch.setitem(sys.modules, "velopack", types.SimpleNamespace(App=FakeApp))
    update.run_velopack_hooks()
    assert calls == [("auto_apply", False), ("run", None)]


def test_a_package_changed_after_the_check_is_not_applied(tmp_path) -> None:
    package = tmp_path / "ReefScanner-1.2.0-osx-full.nupkg"
    package.write_bytes(b"signed")
    manager = FakeManager(_info())
    updater = Updater(manager, verify=lambda _p: None, find_package=lambda _m, _i: package)
    updater.check()
    _download_inline(updater)
    assert updater.status()["state"] == "ready"

    package.write_bytes(b"swapped")
    assert updater.apply_on_exit() is False
    assert manager.applied is None
    assert updater.status()["state"] == "failed" and not package.exists()


def test_a_package_that_fails_the_check_is_deleted(tmp_path) -> None:
    """So nothing, Velopack included, can install it later."""
    package = tmp_path / "ReefScanner-1.2.0-osx-full.nupkg"
    package.write_bytes(b"unsigned")

    def reject(_package: Path) -> None:
        raise UpdateError("not signed by us")

    updater = Updater(FakeManager(_info()), verify=reject, find_package=lambda _m, _i: package)
    updater.check()
    _download_inline(updater)

    assert updater.status()["state"] == "failed"
    assert not package.exists()


# -- checking again (Settings → About) ------------------------------------------

def test_checking_again_finds_a_release_published_since_launch() -> None:
    manager = FakeManager(None)
    updater = _updater(manager)
    updater.check()
    assert updater.status()["state"] == "none"

    manager.info = _info("1.3.0")
    assert updater.start_check() is True
    deadline = time.monotonic() + 5
    while updater.status()["state"] == "checking":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert updater.status()["state"] == "available"


def test_checking_again_never_interrupts_a_verified_update() -> None:
    updater = _updater(FakeManager(_info()))
    updater.check()
    _download_inline(updater)
    assert updater.start_check() is False
    assert updater.status()["state"] == "ready"
