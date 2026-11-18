# `reef`: one command for working on the repo

Setting up, running, testing and releasing ReefScanner took knowing which of
uv, npm, a bash script or a GitHub step to reach for, and a missing piece
(an outdated venv, the wrong Node, no frontend build) showed up as a
confusing error somewhere else. `reef` makes each of these one command, and
when something isn't in place it says exactly what to run.

## Decisions

### 1. Python, as a `uv tool`, called `reef`

It must run on macOS, Windows and Linux, so not shell. The repo already
needs uv, and uv installs Python, so a Python package costs no new
prerequisite. Installed once with

```sh
uv tool install --editable tools/reef
```

it is a single word on the PATH (`reef doctor`), on every OS, from any
folder inside the repo (it finds the root by walking up to the workspace's
`pyproject.toml`). Editable, so changes to it apply without reinstalling.

It uses only the standard library and runs in uv's own tool environment,
never the project's venv: its first job is to tell whether that venv is in
order, so it can't depend on it. `just`, poethepoet, npm scripts, mise and
make were weighed: either shell underneath (two versions of every recipe for
Windows), or the real logic ends up in Python anyway, or Node would be
needed before Python could even be checked.

It is a workspace member only so the test suite can import it.

### 2. Commands

| Command | Does |
| --- | --- |
| `reef doctor` | checks everything and prints the fix for each problem |
| `reef setup` | `uv sync`, `npm ci` and the frontend build, as needed |
| `reef run` | the desktop app from source (`--browser`: server with reload + Vite) |
| `reef test` | pytest, TypeScript check and oxlint (`--py`, `--web`) |
| `reef build` | the packaged app for this OS (macOS: `app/scripts/build_app.sh`) |
| `reef release X.Y.Z` | sets the version, commits, tags and pushes |

`run`, `test` and `build` first run the checks they depend on and stop with
the fix if one fails, rather than failing halfway. They never repair on their
own: `reef setup` does that, so nothing changes without being asked.

### 3. What `doctor` checks

Required: the lockfile matches the `pyproject.toml` files (`uv lock --check`),
the venv matches the lockfile (`uv sync --check`), Node's major version
matches `app/frontend/.nvmrc`, `node_modules` matches `package-lock.json`, and
the frontend build is newer than its sources. For building the app: .NET and
`vpk` at the `velopack` version in `uv.lock`. For the edge tests: an ffmpeg
with libx264. Each failure names the command that fixes it.

### 4. `reef release` replaces `set_version.sh`

The bash script couldn't run on Windows. `reef release 1.1.0`:

1. refuses unless on `main`, with a clean tree, level with `origin/main`, the
   version is SemVer, newer than the current one, and its tag doesn't exist;
2. runs `reef test`;
3. writes the version to the three `pyproject.toml` files and
   `core/__init__.py`, runs `uv lock`, and locks new migrations in
   `released.txt`;
4. shows what will be published and asks to confirm (a tag is permanent);
5. commits `chore: release 1.1.0`, pushes `main`, then tags `v1.1.0` and
   pushes the tag, which starts the release workflow.

A release candidate (`1.1.0-rc.1`) is published as a prerelease, as before.
