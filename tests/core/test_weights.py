"""Where the SharkTrack weights come from, in order of preference."""

from __future__ import annotations

import sys

import pytest

from reefscanner.core import weights


@pytest.fixture
def no_network(monkeypatch) -> None:
    def refuse(*_args, **_kwargs) -> None:
        raise AssertionError("must not download")

    monkeypatch.setattr(weights.urllib.request, "urlretrieve", refuse)


def test_packaged_app_uses_bundled_weights(tmp_path, monkeypatch, no_network) -> None:
    """Inside the app the weights ship with it, so a first scan needs no internet."""
    bundle = tmp_path / "bundle"
    (bundle / "weights").mkdir(parents=True)
    bundled = bundle / "weights" / weights.SHARKTRACK_FILENAME
    bundled.write_bytes(b"weights")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("REEFSCANNER_CACHE", str(tmp_path / "empty-cache"))

    assert weights.ensure_sharktrack_weights() == str(bundled)


def test_source_install_ignores_bundle_and_uses_cache(tmp_path, monkeypatch, no_network) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    cache = tmp_path / "cache"
    cache.mkdir()
    cached = cache / weights.SHARKTRACK_FILENAME
    cached.write_bytes(b"weights")
    monkeypatch.setenv("REEFSCANNER_CACHE", str(cache))

    assert weights.ensure_sharktrack_weights() == str(cached)
