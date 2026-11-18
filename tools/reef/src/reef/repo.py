"""The repo `reef` works on, and the small helpers every command needs.

Commands are run as argument lists, never through a shell, so they behave
the same on macOS, Windows and Linux. Programs are found with
``shutil.which``, which also finds Windows' ``npm.cmd``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class ReefError(Exception):
    """Stops a command with a message for the person running it."""


@dataclass(frozen=True)
class Repo:
    root: Path

    @property
    def frontend(self) -> Path:
        return self.root / "app" / "frontend"

    @property
    def static_index(self) -> Path:
        """The frontend build the app serves."""
        return self.root / "app" / "src" / "reefscanner" / "app" / "static" / "index.html"

    @property
    def migrations(self) -> Path:
        return self.root / "app" / "src" / "reefscanner" / "app" / "migrations"


def find_repo(start: Path | None = None) -> Repo:
    """The repo containing ``start`` (default: the current folder).

    Its root is the folder whose ``pyproject.toml`` declares the uv workspace,
    so `reef` works from any folder inside the repo.
    """
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file() and "[tool.uv.workspace]" in pyproject.read_text():
            return Repo(folder)
    raise ReefError("Not inside the ReefScanner repo. Run reef from the repo or a folder in it.")


# -- running programs -----------------------------------------------------------

def which(name: str) -> str | None:
    return shutil.which(name)


def which_on(name: str, env: dict[str, str] | None) -> str | None:
    """``which``, but on ``env``'s PATH when given (e.g. .nvmrc's Node first)."""
    return shutil.which(name, path=env.get("PATH")) if env else shutil.which(name)


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> int:
    """Run a program with its output shown; returns its exit code."""
    program = which_on(args[0], env) or args[0]
    try:
        return subprocess.run([program, *args[1:]], cwd=cwd, env=env, check=False).returncode
    except FileNotFoundError:
        raise ReefError(f"{args[0]} isn't installed (or not on the PATH).") from None


def capture(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run a program quietly; returns its exit code and combined output."""
    program = which_on(args[0], env)
    if program is None:
        return 127, f"{args[0]} not found"
    result = subprocess.run(
        [program, *args[1:]], cwd=cwd, env=env, capture_output=True, text=True, check=False,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


# -- output ---------------------------------------------------------------------

def _color(code: str) -> str:
    use = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    return f"\033[{code}m" if use else ""


GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    _color("32"), _color("31"), _color("33"), _color("2"), _color("1"), _color("0"),
)


def heading(text: str) -> None:
    print(f"\n{BOLD}{text}{RESET}")


def step(text: str) -> None:
    print(f"\n{BOLD}==> {text}{RESET}", flush=True)
