"""PyWebView shell — ReefScanner as a native window.

Starts uvicorn on a free port in a daemon thread, waits until it actually
answers, then opens a webview at it. The wait is not optional: a webview that
loads before the server is listening shows a connection error and does not
retry, so a race here looks to the user like a broken app.

The window is just a browser pointed at localhost, so everything the UI does
here it also does in ``reefscanner serve`` + a browser tab. The one thing the
shell adds is a native folder picker, exposed to JavaScript as
``window.pywebview.api.pick_folder()``.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("reefscanner.desktop")

#: How long to wait for the server before giving up and telling the user.
STARTUP_TIMEOUT_S = 30.0


def _free_port() -> int:
    """Ask the OS for an unused port.

    Binding to port 0 and reading back the assignment leaves a small race
    (something else could take it before uvicorn binds), but it beats guessing
    a fixed port that may already be in use by another copy of the app.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_serving(url: str, timeout: float = STARTUP_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    return False


class Bridge:
    """Methods reachable from the page as ``window.pywebview.api.*``.

    Deliberately tiny. The UI accepts typed paths for everything, so this is a
    convenience rather than a dependency — the same build has to work in a
    plain browser tab where no bridge exists.
    """

    def __init__(self) -> None:
        self._window = None

    def attach(self, window) -> None:
        self._window = window

    def pick_folder(self) -> Optional[str]:
        """Open the OS folder chooser. Returns None if the user cancels."""
        import webview

        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        return str(result[0])


def run(db_path: Optional[str | Path] = None, debug: bool = False) -> int:
    """Open the desktop window. Returns a process exit code."""
    try:
        import webview
    except ImportError:
        print(
            "error: the desktop window needs PyWebView.\n"
            "Install it with:  pip install 'reefscanner[desktop]'"
        )
        return 2

    try:
        import uvicorn

        from ..app.main import STATIC_DIR, create_app
    except ImportError as exc:
        print(
            f"error: the service dependencies are missing ({exc}).\n"
            "Install them with:  pip install 'reefscanner[desktop]'"
        )
        return 2

    if not (STATIC_DIR / "index.html").exists():
        print(
            "error: no frontend build found inside the package.\n"
            f"Expected: {STATIC_DIR / 'index.html'}\n"
            "Build it with:  cd frontend && npm install && npm run build"
        )
        return 2

    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    app = create_app(db_path=db_path, allow_dev_origins=False)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="debug" if debug else "warning",
        )
    )

    thread = threading.Thread(target=server.run, name="reefscanner-server", daemon=True)
    thread.start()

    if not _wait_until_serving(url):
        print(f"error: the ReefScanner service did not start on {url}")
        return 1

    logger.info("ReefScanner service ready on %s", url)

    bridge = Bridge()
    window = webview.create_window(
        "ReefScanner",
        url,
        js_api=bridge,
        width=1440,
        height=920,
        min_size=(1024, 680),
        # The UI is dark; a white window background flashes on open otherwise.
        background_color="#060D11",
    )
    bridge.attach(window)

    # Blocks until the window closes.
    webview.start(debug=debug)

    # Closing the window means quitting, so bring the server down with it
    # rather than leaving a daemon thread mid-write on someone's footage.
    server.should_exit = True
    thread.join(timeout=10)
    return 0
