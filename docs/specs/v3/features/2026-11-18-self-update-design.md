# Self-update with Velopack

Testers install ReefScanner once from the DMG
([distribution](2026-11-18-distribution-design.md)); from then on the app
should update itself, on the Mac now and on Windows and Linux later, without
anything to host. This replaces the hand-written updater planned in the
distribution note's decision 5.

## Decisions

### 1. Velopack does the updating

[Velopack](https://docs.velopack.io) checks a feed, downloads full or delta
packages, verifies their SHA-256, swaps the app after it exits and relaunches
it, on macOS, Windows and Linux, with the same Python API
(`velopack` on PyPI, Rust underneath, wheels for every platform we need).
Writing that ourselves would mean one swap helper per OS; with Velopack the
per-OS part is only how a download is checked for our signature (decision 4).

Its packaging tool, `vpk`, is a .NET program, so the build needs the .NET SDK
(`actions/setup-dotnet` in CI, `brew install dotnet@10` locally). `vpk` and
the Python package must be the same version: `uv.lock` decides it, CI
installs `vpk` at the version found there, and `build_app.sh` refuses to
build when the two differ (a local `vpk` left behind).

### 2. What a trial showed

Tried on 2026-11-18 on the branch `velopack-spike` (not merged), on this Mac
and in CI:

| Check | Result |
| --- | --- |
| `vpk pack` on the PyInstaller `.app`, with our identity and entitlements | Signed with Team ID `T5M8S8M8ZT`, hardened runtime; adds only `Contents/MacOS/UpdateMac` and a version file |
| Notarization by `vpk` in CI | Accepted and stapled; the DMG built from its app is accepted as "Notarized Developer ID" with a quarantine flag set |
| Update rc.1 → rc.2, and as a delta rc.2 → rc.3 | Swapped and relaunched in about 2 s; a delta is rebuilt into a full package before anything is applied |
| A package with one byte changed | Refused (SHA-256 mismatch); the old version keeps running |
| A correctly hashed but unsigned package | **Installed.** Velopack checks integrity, not who signed it, and macOS doesn't check either, since its downloads carry no quarantine flag |
| An app in `/Applications` | Updated without a password: an app dragged there from the DMG belongs to the user |

### 3. The DMG holds Velopack's app

The updater lives inside the bundle, so the app people install must be the one
`vpk pack` produced, never PyInstaller's. `build_app.sh` unpacks Velopack's
portable zip and builds the DMG from that app. Velopack's `.pkg` installer is
skipped (`--noInst`): it would need a second certificate (Developer ID
Installer) and could leave the app owned by root, so that every update asked
for a password.

### 4. Our own signature check before applying

Velopack's hash check catches a corrupted or swapped file, but the hash comes
from the same release as the package. So before applying, the app unpacks the
downloaded full package from Velopack's cache
(`~/Library/Caches/velopack/ReefScanner/packages/<file>`) and requires

```
codesign --verify --deep --strict -R='anchor apple generic
  and identifier "io.github.simonicarlo.reefscanner"
  and certificate leaf[subject.OU] = "T5M8S8M8ZT"'
```

Velopack would also, by default, install a downloaded package by itself at
the next launch, without asking and without this check (seen when the
packaged app first ran with a package left in the cache). The startup hook
turns that off (`set_auto_apply_on_startup(False)`), and a package that fails
the check is deleted at once.

Against an attacker this adds little (whoever controls the GitHub account can
also run the signing workflow), but it stops our own mistakes: a release
accidentally built unsigned is refused instead of installed. Velopack stores
symlinks as `<name>.__symlink` files holding the target (a trailing `/` for a
directory); unpacking must turn them back into links, or the signature check
fails. Windows gets the equivalent check (Authenticode signer) once the exe is
signed; until then, and on Linux, the hash is all there is.

### 5. The app asks; it never updates on its own

- After the window is open, a background thread asks GitHub
  (`GithubSource`, stable releases only) for a newer version. Any failure is
  logged and otherwise silent: in the field the laptop is usually offline.
  Running from source never checks.
- If there is one, the UI shows a banner: "ReefScanner 1.2.0 is available ·
  Update and restart". The download starts when that is clicked, with
  progress in the banner.
- After the download and the signature check, the app refuses to restart
  while a scan is running, then closes the window and stops the server;
  Velopack applies the update once the process has exited
  (`wait_exit_then_apply_updates`) and starts the new version.
- The banner talks to the desktop shell through the pywebview bridge
  (`Bridge` in `desktop/main.py`), not through the HTTP API, so no other
  program on the machine can start an install. In a browser (`serve`) the
  banner never appears.
- `GithubSource` takes no timeout, so a stalled connection leaves the check
  (or a download) pending. Nothing is shown for a check; a stuck download
  is left by quitting, and the next launch starts over.
- The new version migrates the database with its usual backup
  (`reefscanner.db.bak-<revision>`). Updates only go forward; going back
  means installing an older DMG and restoring that backup by hand.

The code goes in `reefscanner/desktop/update.py`, with Velopack stubbed in the
tests the way `webview` is.

### 6. Release files

`vpk pack` writes to `app/dist/velopack/`. A release carries:

| Asset | For |
| --- | --- |
| `ReefScanner.dmg` | people; the stable link is unchanged |
| `releases.osx.json` | the app: the feed, with versions, files and hashes |
| `ReefScanner-<version>-osx-full.nupkg` | the app: the whole update |
| `ReefScanner-<version>-osx-delta.nupkg` | the app: only what changed since the last release |

`ReefScanner-macOS.zip` goes; Velopack's portable zip isn't published (the
DMG is the way in). For deltas, CI first fetches the previous release's
packages (`vpk download github`), logged in with the workflow's token:
anonymous API calls are counted per IP, and the shared Mac runners' IPs are
often out of them (this failed the first `v1.1.0-rc.2` build). If the fetch
fails anyway, the release goes out without a delta. On Windows and Linux, `releases.win.json`
and `releases.linux.json` sit in the same release, with `Setup.exe` and an
AppImage for people.

Velopack needs SemVer versions: a release candidate is `1.1.0-rc.1`
(`set_version.sh` has to accept that form, not only PEP 440's `1.1.0rc1`).

### 7. The workflow publishes in two steps

A published release can't take more files (release immutability), and once
Windows and Linux build on their own runners, each uploads separately. So the
build jobs upload to a draft release and a last job publishes it. A manual run
still only keeps the files as an artifact; the workflow already installs .NET
and `vpk` and creates the notarytool profile in the throwaway keychain from
the existing secrets, so no secret changes.

## Rollout

1.0.0 has no updater: the tester installs the first release with one from the
DMG, once. A release candidate published as a prerelease is invisible to
`GithubSource` without `prerelease=True`, so it can be tried on our own Mac
first (an environment variable switches the check to prereleases).

### 8. Model releases stay as they are

`GithubSource` lists the 10 newest releases and reads `releases.osx.json`
from each; a release without one, such as `models-v1`, is skipped without an
error (`get_git_release_feed` in Velopack's source). So model weights keep
their own releases, pinned by URL and SHA-256 in `core/weights.py`, bundled
into the app, and never marked Latest; a new model reaches testers with the
next app update. The one rule: fewer than ten releases may come between two
app releases, or the newest one drops out of what the updater sees.

## Where it lives

- `app/src/reefscanner/desktop/update.py`: `Updater` (the states above),
  `unpack_app` and `verify_package`. Where Velopack keeps a download
  (`~/Library/Caches/velopack/<app>/packages`) is its locator's default on
  the Mac, read from its source; if the package isn't there the update fails
  closed and offers the download page.
- `desktop/main.py`: `Bridge.update_status`, `start_update`,
  `restart_to_update`, `open_download_page`; the check starts once the app
  has loaded. `JobRunner.any_running()` keeps a restart from cutting a scan.
- `app/frontend/src/components/UpdateBanner.tsx`, at the foot of the sidebar.
- `app/packaging/launcher.py`: `velopack.App().run()` before anything else.
- `app/scripts/build_app.sh`: `vpk pack`, then the DMG from Velopack's app;
  `VPK_PREVIOUS_DIR` holds the last release, for the delta.
- `tests/app/test_update.py`, with Velopack faked; the real `codesign` check
  was run by hand against the CI-built package and an unsigned one.
