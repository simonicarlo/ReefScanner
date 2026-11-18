"""PyWebView shell — ReefScanner as a native window.

Starts uvicorn on a free port in a daemon thread, waits until it actually
answers, then opens a webview at it. The wait is not optional: a webview that
loads before the server is listening shows a connection error and does not
retry, so a race here looks to the user like a broken app.

The window is just a browser pointed at localhost, so everything the UI does
here it also does in ``reefscanner serve`` + a browser tab. What the shell
adds is reachable from JavaScript as ``window.pywebview.api.*``: a native
folder picker, self-update (``update.py``), and showing the data folder or the
log in Finder. Updating goes through here rather than the HTTP API, so no
other program on the machine can start one; the folders shown are fixed
paths the app knows, never one passed in from the page.
"""

from __future__ import annotations

import html
import logging
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import paths
from .update import DOWNLOAD_URL, Updater

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

    def __init__(
        self,
        updater: Updater | None = None,
        busy: Callable[[], bool] = lambda: False,
        db_path: Path | None = None,
    ) -> None:
        self._window = None
        self._updater = updater or Updater(None)
        self._busy = busy
        self._db_path = db_path

    def attach(self, window) -> None:
        self._window = window

    def pick_folder(self) -> str | None:
        """Open the OS folder chooser. Returns None if the user cancels."""
        import webview

        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not result:
            return None
        return str(result[0])

    # -- self-update ------------------------------------------------------------
    def update_status(self) -> dict[str, Any]:
        """``{"state", "version", "progress", "prereleases"}``; see ``update.State``."""
        return self._updater.status()

    def check_for_updates(self) -> bool:
        """Ask GitHub again. False if updates are off or one is under way."""
        return self._updater.start_check()

    def start_update(self) -> bool:
        """Download and verify the waiting update. False if there is none."""
        return self._updater.start_download()

    def restart_to_update(self) -> dict[str, Any]:
        """Quit so Velopack can install the verified update and reopen the app.

        Refused while a scan runs: quitting would cancel it halfway.
        """
        if self._busy():
            return {"ok": False, "reason": "scanning"}
        if not self._updater.apply_on_exit():
            return {"ok": False, "reason": "failed"}
        if self._window is not None:
            # Closing the window ends webview.start(); run() then stops the
            # server and the process exits, which Velopack is waiting for.
            self._window.destroy()
        return {"ok": True}

    def open_download_page(self) -> None:
        """Open the latest release in the browser, for a manual update."""
        webbrowser.open(DOWNLOAD_URL)

    # -- Settings → About ---------------------------------------------------------
    def show_data_folder(self) -> bool:
        """Show the database in Finder: projects, reviews and their backups."""
        return self._db_path is not None and _reveal(self._db_path)

    def show_log(self) -> bool:
        """Show the log file in Finder, e.g. to send it with a problem."""
        return _reveal(paths.log_file())


def run(db_path: str | Path | None = None, debug: bool = False) -> int:
    """Open the desktop window. Returns a process exit code."""
    try:
        import webview
    except ImportError:
        print(
            "error: the desktop window needs PyWebView.\n"
            "Install it with:  pip install 'reefscanner-app[desktop]'"
        )
        return 2

    try:
        import uvicorn

        from ..app.db import SchemaMismatch
        from ..app.main import STATIC_DIR, create_app
    except ImportError as exc:
        print(
            f"error: the service dependencies are missing ({exc}).\n"
            "Install them with:  pip install 'reefscanner-app[desktop]'"
        )
        return 2

    if not (STATIC_DIR / "index.html").exists():
        print(
            "error: no frontend build found inside the package.\n"
            f"Expected: {STATIC_DIR / 'index.html'}\n"
            "Build it with:  cd app/frontend && npm install && npm run build"
        )
        return 2

    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    try:
        app = create_app(db_path=db_path, allow_dev_origins=False)
    except SchemaMismatch as exc:
        print(f"error: {exc}")
        return 2
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

    updater = Updater.for_this_app()
    bridge = Bridge(updater, busy=app.state.runner.any_running, db_path=app.state.db.path)
    # The window opens straight away on a "Starting…" page rather than once the
    # server answers. A packaged app's first launch can take a while (macOS
    # verifying a large unsigned bundle, then Python loading OpenCV and the web
    # stack), and to someone new a double-click that shows nothing looks like it
    # failed — so they click again.
    window = webview.create_window(
        "ReefScanner",
        html=STARTING_HTML,
        js_api=bridge,
        width=1440,
        height=920,
        min_size=(1024, 680),
        # Match macOS, so opening the window doesn't flash the other mode.
        background_color="#1E1E20" if _system_is_dark() else "#F5F5F7",
    )
    bridge.attach(window)

    outcome = {"served": False}
    # Blocks until the window closes. The callback runs on pywebview's worker
    # thread once the window exists, and swaps in the app when it is ready.
    webview.start(_load_when_ready, (window, url, outcome, updater), debug=debug)

    # Closing the window means quitting, so bring the server down with it
    # rather than leaving a daemon thread mid-write on someone's footage.
    server.should_exit = True
    thread.join(timeout=10)
    return 0 if outcome["served"] else 1


def _load_when_ready(window, url: str, outcome: dict, updater: Updater) -> None:
    """Point the window at the app once the server answers, or explain why not.

    Only then is GitHub asked for an update, so the check never delays the app.
    """
    if _wait_until_serving(url):
        logger.info("ReefScanner service ready on %s", url)
        outcome["served"] = True
        window.load_url(url)
        updater.start_check()
    else:
        logger.error("ReefScanner service did not start on %s", url)
        window.load_html(FAILED_HTML)


def _reveal(path: Path) -> bool:
    """Select ``path`` in the OS file manager (its folder, if it's missing)."""
    target = path if path.exists() else path.parent
    if not target.exists():
        return False
    if sys.platform == "darwin":
        command = ["open", "-R", str(target)]
    elif sys.platform == "win32":
        command = ["explorer", f"/select,{target}"]
    else:
        command = ["xdg-open", str(target if target.is_dir() else target.parent)]
    try:
        subprocess.run(command, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        logger.warning("Couldn't show %s", target, exc_info=True)
        return False
    return True


def _system_is_dark() -> bool:
    """Whether macOS is in dark mode. False elsewhere or if it can't tell."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.stdout.strip() == "Dark"


# The app's own colours (styles/tokens.css), in both modes.
_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
  :root{{color-scheme:light dark}}
  html,body{{margin:0;height:100%;background:#F5F5F7;color:#1D1D1F;
    font:15px -apple-system,BlinkMacSystemFont,sans-serif}}
  main{{height:100%;display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:14px;text-align:center;padding:0 2rem}}
  .dot{{width:12px;height:12px;border-radius:50%;background:{color};
    animation:p 1.4s ease-in-out infinite}}
  @keyframes p{{50%{{opacity:.25}}}}
  small{{color:rgba(60,60,67,.62);max-width:32rem;line-height:1.5}}
  @media (prefers-color-scheme:dark){{html,body{{background:#1E1E20;color:#F5F5F7}}
    small{{color:rgba(235,235,245,.62)}}}}
</style></head><body><main><div class="dot"></div>
<div>{title}</div><small>{body}</small></main></body></html>"""

STARTING_HTML = _PAGE.format(
    color="#0A84FF",
    title="Starting ReefScanner…",
    body="The first launch can take a little while.",
)

FAILED_HTML = _PAGE.format(
    color="#FF453A",
    title="ReefScanner couldn't start",
    body="Quit and open it again. If it keeps happening, send the log file "
    f"from {html.escape(paths.shown(paths.log_file()))} to whoever gave you the app.",
)
