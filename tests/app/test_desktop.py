"""Tests for the PyWebView shell.

The window itself can't be opened in CI, so ``webview`` is stubbed. What's
worth testing is everything around it: that a free port is chosen, that the
window opens at once on a "Starting…" page, that it is only pointed at the app
once the server really answers, and that a server that never answers produces
an explanation rather than a blank window.
"""

from __future__ import annotations

import socket
import sys
import types
import urllib.request

import pytest

from reefscanner.desktop import main as desktop


@pytest.fixture
def fake_webview(monkeypatch):
    """A stand-in for the ``webview`` module that records what it was asked."""
    calls: dict = {"windows": [], "started": False, "dialog": None}

    class FakeWindow:
        def __init__(self, title, url=None, **kwargs):
            self.title = title
            self.url = url
            self.html = kwargs.pop("html", None)
            self.kwargs = kwargs

        def load_url(self, url):
            self.url = url

        def load_html(self, html):
            self.html = html

        def create_file_dialog(self, _kind):
            return calls["dialog"]

    module = types.ModuleType("webview")
    module.FOLDER_DIALOG = "folder"

    def create_window(title, url=None, **kwargs):
        window = FakeWindow(title, url, **kwargs)
        calls["windows"].append(window)
        return window

    def start(func=None, args=(), **_kwargs):
        # The real call shows the window, then runs func on a worker thread.
        window = calls["windows"][-1]
        calls["first_html"] = window.html
        calls["url_at_open"] = window.url
        if func is not None:
            func(*args)
        if window.url:
            with urllib.request.urlopen(f"{window.url}/api/health", timeout=5) as resp:
                calls["health"] = resp.status
        calls["started"] = True

    module.create_window = create_window
    module.start = start
    monkeypatch.setitem(sys.modules, "webview", module)
    return calls


@pytest.fixture
def fake_frontend(monkeypatch, tmp_path):
    """Pretend a frontend build exists — the shell refuses to open without one."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>ok</body></html>")
    monkeypatch.setattr("reefscanner.app.main.STATIC_DIR", static)
    return static


def test_free_port_is_actually_free() -> None:
    port = desktop._free_port()
    assert 1024 < port < 65536
    # Binding it again must succeed, i.e. nothing was left holding it.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


def test_wait_until_serving_times_out_quickly() -> None:
    dead = f"http://127.0.0.1:{desktop._free_port()}"
    assert desktop._wait_until_serving(dead, timeout=0.5) is False


def test_window_opens_on_starting_page_then_loads_app(
    fake_webview, fake_frontend, tmp_path
) -> None:
    code = desktop.run(db_path=tmp_path / "desktop.db")

    assert code == 0
    assert fake_webview["started"] is True
    # Something is on screen immediately, before the server is known to be up.
    assert "Starting ReefScanner" in fake_webview["first_html"]
    assert fake_webview["url_at_open"] is None
    # ...and the app replaces it only once the server really answers.
    assert fake_webview["health"] == 200

    window = fake_webview["windows"][0]
    assert window.title == "ReefScanner"
    assert window.url.startswith("http://127.0.0.1:")
    assert window.kwargs["js_api"] is not None


def test_server_that_never_answers_explains_itself(
    fake_webview, fake_frontend, monkeypatch, tmp_path
) -> None:
    """A blank window is the worst outcome for someone who can't read a log."""
    monkeypatch.setattr(desktop, "_wait_until_serving", lambda *a, **k: False)

    assert desktop.run(db_path=tmp_path / "d.db") == 1
    window = fake_webview["windows"][0]
    assert window.url is None, "must not point the window at a dead server"
    assert "couldn't start" in window.html
    assert "reefscanner.log" in window.html


def test_run_refuses_without_a_frontend_build(
    fake_webview, monkeypatch, tmp_path
) -> None:
    """A missing build must be a clear message, not a blank window."""
    monkeypatch.setattr("reefscanner.app.main.STATIC_DIR", tmp_path / "nothing")
    assert desktop.run(db_path=tmp_path / "d.db") == 2
    assert fake_webview["started"] is False


def test_bridge_folder_picker(fake_webview) -> None:
    bridge = desktop.Bridge()
    assert bridge.pick_folder() is None, "no window attached yet"

    import webview  # the stub

    window = webview.create_window("t", "http://x")
    bridge.attach(window)

    fake_webview["dialog"] = None
    assert bridge.pick_folder() is None, "cancelling returns None"

    fake_webview["dialog"] = ("/Users/someone/footage",)
    assert bridge.pick_folder() == "/Users/someone/footage"
