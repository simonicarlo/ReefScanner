---
paths:
  - "**/pyproject.toml"
  - "uv.lock"
  - "**/package.json"
  - "**/package-lock.json"
---

# Dependency Management Rules

## Where a Python dependency goes
The repo is a uv workspace; put each dependency in the member that needs it.
- `core` (runs on the rig): only what detection and the data format need. No
  web stack, no torch. Heavy or optional capabilities become extras
  (`ultralytics`, `ml`, `ffmpeg`).
- `app` (field laptop): the service, UI shell and anything only the app uses.
- `edge`: rig-only dependencies, nothing the laptop needs.
- Test and dev tools go in the root `dev` dependency group, never in a member.

## Adding Dependencies
- Check whether an existing dependency already provides the functionality
- Prefer well-maintained, widely used packages
- Verify the package name and current API with context7 before using it
- Check the license: copyleft (e.g. Ultralytics' AGPL-3.0) must be noted where
  it's declared and must stay out of `core`'s required dependencies
- Make sure wheels exist for every platform we ship (macOS arm64, Linux
  aarch64 for boards) and for the Python version in `.python-version`

## Versions and Lockfiles
- Declare ranges in `pyproject.toml` (`>=X,<Y` for libraries with breaking
  majors); `uv.lock` pins exact versions and is committed
- Change dependencies with `uv add` / `uv sync`, never `uv pip install` into
  the dev venv (the next `uv run` would remove it)
- Frontend dependencies via `npm`; `package-lock.json` is committed
- Read the changelog before a major-version bump

## Hygiene
- Keep dependency lists grouped with a comment saying why each is there when
  it isn't obvious
- Commit lockfile changes only together with the dependency change behind them
- Remove a dependency when its last user goes
