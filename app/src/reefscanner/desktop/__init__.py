"""The native desktop window.

Optional: ``pip install 'reefscanner-app[desktop]'``. Without it the app is still
fully usable through ``reefscanner serve`` and a browser.
"""

__all__ = ["run"]


def __getattr__(name: str):
    if name == "run":
        from .main import run

        return run
    raise AttributeError(name)
