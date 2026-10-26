"""The native desktop window.

Optional: ``pip install 'reefscanner-app[desktop]'``. Without it the app is still
fully usable through ``reefscanner serve`` and a browser.
"""

from __future__ import annotations

from typing import Any

__all__ = ["run"]


def __getattr__(name: str) -> Any:
    if name == "run":
        from .main import run

        return run
    raise AttributeError(name)
