"""`reef`: set up, run, test, build and release ReefScanner, on any OS.

    reef doctor          what's missing, and how to fix it
    reef setup           install what's missing or out of date
    reef run             the desktop app from source (--browser: server + Vite)
    reef test            Python tests, TypeScript check, lint (--py, --web, -- pytest args)
    reef build           the packaged app for this OS
    reef release 1.1.0   set the version, commit, tag and push

See docs/specs/v3/features/2026-11-19-dev-tool-design.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

from . import checks, release
from .repo import BOLD, DIM, GREEN, RED, RESET, ReefError, Repo, find_repo, run, step, which, which_on

REPO_SLUG = "simonicarlo/ReefScanner"


# -- doctor / setup -------------------------------------------------------------

def cmd_doctor(repo: Repo, _args: argparse.Namespace) -> int:
    failed = checks.report(repo, checks.GROUPS)
    print()
    if failed:
        print(f"{RED}{failed} thing{'s' if failed > 1 else ''} to fix{RESET}, in the order above.")
        return 1
    print(f"{GREEN}All set.{RESET} {DIM}(! marks what only some tasks need.){RESET}")
    return 0


def cmd_setup(repo: Repo, _args: argparse.Namespace) -> int:
    step("Python packages (uv sync)")
    if checks.lockfile(repo).ok is False:
        raise ReefError("uv.lock is out of date with the pyproject.toml files.\n  → uv lock")
    if run(["uv", "sync", "--locked"], repo.root) != 0:
        return 1

    step("Frontend")
    checks.require(repo, [checks.node])
    node_env = checks.node_env(repo)
    if not checks.npm_packages(repo).ok:
        if run(["npm", "ci"], repo.frontend, env=node_env) != 0:
            return 1
    else:
        print("npm packages already match package-lock.json")
    if not checks.frontend_build(repo).ok:
        if run(["npm", "run", "build"], repo.frontend, env=node_env) != 0:
            return 1
    else:
        print("Frontend build already up to date")

    print()
    return cmd_doctor(repo, _args)


# -- run ----------------------------------------------------------------------------

def cmd_run(repo: Repo, args: argparse.Namespace) -> int:
    if not args.browser:
        checks.require(repo, [*checks.PYTHON, checks.frontend_build])
        # Already checked, so don't let uv sync behind our back.
        return run(["uv", "run", "--no-sync", "reefscanner", "desktop"], repo.root)

    checks.require(repo, [*checks.PYTHON, checks.node, checks.npm_packages])
    node_env = checks.node_env(repo)
    print(f"{BOLD}Server{RESET} http://127.0.0.1:8000 (reloads on Python changes)")
    print(f"{BOLD}UI{RESET}     http://localhost:5173 (open this; reloads on frontend changes)")
    print(f"{DIM}Ctrl+C stops both.{RESET}\n", flush=True)
    processes = [
        subprocess.Popen([which("uv") or "uv", "run", "--no-sync", "reefscanner", "serve", "--reload"],
                         cwd=repo.root),
        subprocess.Popen([which_on("npm", node_env) or "npm", "run", "dev"],
                         cwd=repo.frontend, env=node_env),
    ]
    try:
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


# -- test -----------------------------------------------------------------------------

def cmd_test(repo: Repo, args: argparse.Namespace) -> int:
    py = args.py or not args.web
    web = args.web or not args.py
    needed = [*(checks.PYTHON if py else []), *(checks.FRONTEND[:2] if web else [])]
    checks.require(repo, needed)

    outcomes: list[tuple[str, int]] = []
    if py:
        step("Python tests (pytest)")
        outcomes.append(("pytest", run(["uv", "run", "--no-sync", "pytest", *args.pytest_args], repo.root)))
    if web:
        step("TypeScript check")
        node_env = checks.node_env(repo)
        outcomes.append(("tsc", run(["npx", "tsc", "-b", "--noEmit"], repo.frontend, env=node_env)))
        step("Lint (oxlint)")
        outcomes.append(("oxlint", run(["npm", "run", "lint", "--silent"], repo.frontend, env=node_env)))

    print()
    for name, code in outcomes:
        print(f"  {GREEN + '✓' if code == 0 else RED + '✗'}{RESET} {name}")
    return 0 if all(code == 0 for _, code in outcomes) else 1


# -- build ------------------------------------------------------------------------------

def cmd_build(repo: Repo, _args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        raise ReefError(
            f"Building on {sys.platform} isn't set up yet: only the Mac app exists so far "
            "(docs/specs/v3/TODO.md, Distribution)."
        )
    checks.require(repo, [checks.lockfile, checks.node, *checks.BUILD])
    # build_app.sh runs vpk (on .NET) and npm (with .nvmrc's Node).
    env = checks.node_env(repo, base=checks.dotnet_env())
    env["VPK"] = checks.which_in(env, "vpk") or "vpk"
    return run(["bash", "app/scripts/build_app.sh"], repo.root, env=env)


# -- release ----------------------------------------------------------------------------

def cmd_release(repo: Repo, args: argparse.Namespace) -> int:
    version = release.Version.parse(args.version)
    current = release.check_ready(repo, version)
    kind = "release candidate (prerelease)" if version.is_prerelease else "release, marked Latest"
    print(f"{BOLD}{current} → {version}{RESET} {DIM}({kind}){RESET}")

    if not args.skip_tests:
        step("Tests first")
        if cmd_test(repo, argparse.Namespace(py=False, web=False, pytest_args=[])) != 0:
            raise ReefError("Tests failed: nothing was changed. Fix them, then release.")

    step(f"Version {version}")
    for name in release.write_version(repo, version):
        print(f"  {name}")
    if run(["uv", "lock", "--quiet"], repo.root) != 0:
        _undo(repo)
        return 1
    for rel in release.lock_migrations(repo):
        print(f"  locked migration {rel}")

    tag = f"v{version}"
    print(f"\nThis publishes {BOLD}ReefScanner {version}{RESET}: it commits to main, pushes it,")
    print(f"then pushes the tag {tag}, which starts the release workflow. A tag can't be undone.")
    if not args.yes and input("Publish? [y/N] ").strip().lower() not in ("y", "yes"):
        _undo(repo)
        print("Nothing published; the version changes were undone.")
        return 1

    release.git(repo, "commit", "--quiet", "-am", f"chore: release {version}")
    step("Pushing main")
    if run(["git", "push", "origin", "main"], repo.root) != 0:
        raise ReefError("Pushing main failed, so no tag was made. Fix that, then:\n"
                        f"  → git push origin main && git tag {tag} && git push origin {tag}")
    release.git(repo, "tag", tag)
    step(f"Pushing {tag}")
    if run(["git", "push", "origin", tag], repo.root) != 0:
        raise ReefError(f"Pushing the tag failed. Retry:\n  → git push origin {tag}")

    print(f"\n{GREEN}Release workflow started.{RESET} https://github.com/{REPO_SLUG}/actions")
    if which("gh"):
        print(f"{DIM}Follow it:{RESET} gh run watch")
    return 0


def _undo(repo: Repo) -> None:
    files = [*release.VERSION_FILES, "uv.lock", "app/src/reefscanner/app/migrations/released.txt"]
    release.git(repo, "checkout", "--", *files)


# -- main ----------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reef", description="Set up, run, test, build and release ReefScanner.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="command")
    sub.add_parser("doctor", help="what's missing, and how to fix it").set_defaults(func=cmd_doctor)
    sub.add_parser("setup", help="install what's missing or out of date").set_defaults(func=cmd_setup)

    r = sub.add_parser("run", help="the desktop app from source")
    r.add_argument("--browser", action="store_true",
                   help="server with reload and the Vite dev server, in a browser")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("test", help="Python tests, TypeScript check and lint")
    t.add_argument("--py", action="store_true", help="only the Python tests")
    t.add_argument("--web", action="store_true", help="only the frontend checks")
    t.add_argument("pytest_args", nargs="*",
                   help="passed to pytest after --, e.g. reef test --py -- -k update")
    t.set_defaults(func=cmd_test)

    sub.add_parser("build", help="the packaged app for this OS").set_defaults(func=cmd_build)

    rel = sub.add_parser("release", help="set the version, commit, tag and push")
    rel.add_argument("version", help="e.g. 1.1.0, or 1.1.0-rc.1 for a release candidate")
    rel.add_argument("--yes", action="store_true", help="don't ask before publishing")
    rel.add_argument("--skip-tests", action="store_true", help="don't run the tests first")
    rel.set_defaults(func=cmd_release)
    return p


def main(argv: list[str] | None = None) -> int:
    # Windows consoles may not be UTF-8: never fail over a ✓. Line-buffered,
    # so reef's lines and the programs it runs stay in order when piped.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace", line_buffering=True)
    args = parser().parse_args(argv)
    try:
        return args.func(find_repo(), args)
    except ReefError as exc:
        print(f"{RED}{exc}{RESET}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
