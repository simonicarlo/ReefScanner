"""The local ReefScanner service: FastAPI + SQLite behind the review UI.

Importing this package pulls in FastAPI, so the engine deliberately never does.
Install it with ``pip install 'reefscanner[app]'``.
"""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):
    # Lazy so `import reefscanner.app` doesn't cost a full FastAPI import for
    # callers that only want the submodules.
    if name == "create_app":
        from .main import create_app

        return create_app
    raise AttributeError(name)
