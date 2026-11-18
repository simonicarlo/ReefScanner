"""What `reef doctor` checks, each with the command that fixes it.

A check never changes anything; `reef setup` does. Checks are grouped by what
needs them, so `run`, `test` and `build` can ask only for theirs.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .repo import DIM, GREEN, RED, RESET, YELLOW, ReefError, Repo, capture, heading, which


@dataclass
class Result:
    ok: bool
    what: str
    #: What to run when it isn't ok.
    fix: str = ""
    #: Not needed for the task at hand: shown as a warning, never fails.
    optional: bool = False


Check = Callable[[Repo], Result]


# -- Python -----------------------------------------------------------------------

def lockfile(repo: Repo) -> Result:
    code, _ = capture(["uv", "lock", "--check"], repo.root)
    if code == 0:
        return Result(True, "uv.lock matches the pyproject.toml files")
    return Result(False, "uv.lock is out of date with the pyproject.toml files",
                  "uv lock, then reef setup")


def venv(repo: Repo) -> Result:
    code, _ = capture(["uv", "sync", "--locked", "--check"], repo.root)
    if code == 0:
        return Result(True, "The Python environment matches uv.lock")
    return Result(False, "The Python environment doesn't match uv.lock", "reef setup")


# -- Frontend ---------------------------------------------------------------------

def wanted_node(repo: Repo) -> str:
    return (repo.frontend / ".nvmrc").read_text().strip().removeprefix("v")


def _nvm_node_dir(want: str) -> Path | None:
    """The newest nvm-installed Node with ``want``'s major version, if any.

    nvm is a shell function, so `reef` can't `nvm use`; putting that Node's
    folder first on the PATH does the same for the commands reef runs.
    """
    root = Path(os.environ.get("NVM_DIR") or Path.home() / ".nvm") / "versions" / "node"
    major = want.split(".")[0]
    found = sorted(
        (v for v in root.glob(f"v{major}.*") if (v / "bin").is_dir()),
        key=lambda v: tuple(int(n) for n in v.name[1:].split(".") if n.isdigit()),
    )
    return found[-1] / "bin" if found else None


def node_env(repo: Repo, base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for npm and Node: .nvmrc's Node first, when nvm has it."""
    env = dict(base if base is not None else os.environ)
    folder = _nvm_node_dir(wanted_node(repo))
    if folder is not None:
        env["PATH"] = os.pathsep.join([str(folder), env.get("PATH", "")])
    return env


def node(repo: Repo) -> Result:
    want = wanted_node(repo)
    install = f"install Node {want}: `nvm install {want}` (or from nodejs.org)"
    code, out = capture(["node", "--version"], repo.root, env=node_env(repo))
    if code != 0:
        return Result(False, "Node isn't installed", install)
    have = out.strip().removeprefix("v")
    if have.split(".")[0] != want.split(".")[0]:
        return Result(False, f"Node {have}, but app/frontend/.nvmrc wants {want}", install)
    return Result(True, f"Node {have}")


def npm_packages(repo: Repo) -> Result:
    installed = repo.frontend / "node_modules" / ".package-lock.json"
    lock = repo.frontend / "package-lock.json"
    if not installed.exists():
        return Result(False, "The frontend's npm packages aren't installed", "reef setup")
    if installed.stat().st_mtime < lock.stat().st_mtime:
        return Result(False, "The npm packages are older than package-lock.json", "reef setup")
    return Result(True, "The npm packages match package-lock.json")


def frontend_build(repo: Repo) -> Result:
    if not repo.static_index.exists():
        return Result(False, "The frontend isn't built", "reef setup")
    sources = [
        *(p for p in (repo.frontend / "src").rglob("*") if p.is_file()),
        repo.frontend / "index.html",
        repo.frontend / "package-lock.json",
        *repo.frontend.glob("vite.config.*"),
    ]
    newest = max(p.stat().st_mtime for p in sources if p.exists())
    if repo.static_index.stat().st_mtime < newest:
        return Result(False, "The frontend build is older than its sources", "reef setup")
    return Result(True, "The frontend build is up to date")


# -- Building the app ---------------------------------------------------------------

#: Homebrew's keg-only .NET 10, which doesn't put itself on the PATH.
BREW_DOTNET = Path("/opt/homebrew/opt/dotnet@10")


def dotnet_env() -> dict[str, str]:
    """The environment for running vpk: .NET and dotnet tools on the PATH."""
    env = dict(os.environ)
    paths = [str(Path.home() / ".dotnet" / "tools")]
    if which("dotnet") is None and (BREW_DOTNET / "bin" / "dotnet").exists():
        env.setdefault("DOTNET_ROOT", str(BREW_DOTNET / "libexec"))
        paths.append(str(BREW_DOTNET / "bin"))
    env["PATH"] = os.pathsep.join([*paths, env.get("PATH", "")])
    return env


def locked_velopack(repo: Repo) -> str | None:
    lock = tomllib.loads((repo.root / "uv.lock").read_text())
    return next((p["version"] for p in lock.get("package", []) if p["name"] == "velopack"), None)


def vpk_version(repo: Repo) -> str | None:
    env = dotnet_env()
    vpk = which_in(env, "vpk")
    if vpk is None:
        return None
    # vpk has no --version; every command starts with "Velopack CLI x.y.z,".
    _, out = capture([vpk, "-x", "--skip-updates", "pack"], repo.root, env=env)
    found = re.search(r"Velopack CLI ([^,\s]+),", out)
    return found.group(1) if found else None


def which_in(env: dict[str, str], name: str) -> str | None:
    return shutil.which(name, path=env.get("PATH"))


def dotnet(repo: Repo) -> Result:
    if which_in(dotnet_env(), "dotnet") is None:
        fix = "brew install dotnet@10" if sys.platform == "darwin" else "install the .NET 10 SDK"
        return Result(False, ".NET isn't installed (needed by Velopack's vpk)", fix)
    return Result(True, ".NET is installed")


def vpk(repo: Repo) -> Result:
    want = locked_velopack(repo)
    have = vpk_version(repo)
    install = f"dotnet tool install -g vpk --version {want}"
    if have is None:
        return Result(False, "Velopack's vpk isn't installed", install)
    if have != want:
        return Result(False, f"vpk is {have}, but uv.lock has velopack {want}",
                      f"dotnet tool update -g vpk --version {want}")
    return Result(True, f"vpk {have}, as in uv.lock")


# -- Edge tests -------------------------------------------------------------------

def ffmpeg(repo: Repo) -> Result:
    """The edge tests need an ffmpeg with libx264: the system's or imageio-ffmpeg's."""
    candidates = [which("ffmpeg")]
    code, out = capture(
        ["uv", "run", "--no-sync", "python", "-c",
         "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
        repo.root,
    )
    if code == 0:
        candidates.append(out.splitlines()[-1].strip())
    for exe in filter(None, candidates):
        code, out = capture([exe, "-hide_banner", "-encoders"], repo.root)
        if code == 0 and "libx264" in out:
            return Result(True, "ffmpeg with libx264", optional=True)
    return Result(False, "No ffmpeg with libx264 (the edge tests need one)",
                  "reef setup (installs imageio-ffmpeg), or install ffmpeg", optional=True)


# -- groups -----------------------------------------------------------------------

PYTHON: list[Check] = [lockfile, venv]
FRONTEND: list[Check] = [node, npm_packages, frontend_build]
BUILD: list[Check] = [dotnet, vpk]

GROUPS: list[tuple[str, list[Check], bool]] = [
    ("Python", PYTHON, False),
    ("Frontend", FRONTEND, False),
    ("Building the app (reef build)", BUILD, True),
    ("Edge tests", [ffmpeg], True),
]


def report(repo: Repo, groups: Iterable[tuple[str, list[Check], bool]]) -> int:
    """Run the checks, print them, and return how many required ones failed."""
    failed = 0
    for title, checks, optional in groups:
        heading(title)
        for check in checks:
            result = check(repo)
            result.optional = result.optional or optional
            if result.ok:
                print(f"  {GREEN}✓{RESET} {result.what}")
                continue
            mark = f"{YELLOW}!{RESET}" if result.optional else f"{RED}✗{RESET}"
            print(f"  {mark} {result.what}")
            if result.fix:
                print(f"      {DIM}→{RESET} {result.fix}")
            failed += not result.optional
    return failed


def require(repo: Repo, checks: Iterable[Check]) -> None:
    """Stop unless every check passes, saying what to run."""
    problems = [r for r in (check(repo) for check in checks) if not r.ok]
    if problems:
        lines = "\n".join(f"  ✗ {r.what}\n      → {r.fix}" for r in problems)
        raise ReefError(f"Not ready yet:\n{lines}")
