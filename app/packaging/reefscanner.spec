# PyInstaller spec for the ReefScanner desktop app (macOS).
#
# Built by app/scripts/build_app.sh, which sets REEFSCANNER_BUNDLE_WEIGHTS and runs
# this from a clean standalone Python. Don't run it from the dev venv: that one
# is based on Anaconda, and its libraries would leak into the bundle.
#
# One-folder mode inside a .app, not one-file: a one-file app unpacks itself to
# a temp directory on every launch, which makes each start slow.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
WEIGHTS = Path(os.environ["REEFSCANNER_BUNDLE_WEIGHTS"])
# A Developer ID identity signs every binary with hardened runtime. Unset, the
# app is ad-hoc signed and runs only where it was built (or after "Open Anyway").
SIGN_IDENTITY = os.environ.get("REEFSCANNER_SIGN_IDENTITY") or None
# Compiled from AppIcon.icon by packaging/icon/make_icon.sh (committed outputs).
ICON_DIR = ROOT / "packaging" / "icon"
ENTITLEMENTS = str(ROOT / "packaging" / "entitlements.plist") if SIGN_IDENTITY else None

import imageio_ffmpeg  # noqa: E402  (resolved at build time, from the build venv)

datas = [
    # The built React UI. Missing it gives a window with an API error in it.
    *collect_data_files("reefscanner.app", includes=["static/**/*"]),
    # The Camtrap DP table schemas the package writer and reader work from.
    *collect_data_files("reefscanner.core", includes=["camtrap/schemas/**/*"]),
    # Alembic reads its scripts (env.py, versions/*.py) from disk at startup,
    # so they ship as files, not only as compiled modules in the archive.
    *collect_data_files(
        "reefscanner.app", includes=["migrations/**/*"], include_py_files=True
    ),
    # pywebview's JavaScript bridge.
    *collect_data_files("webview"),
    # SharkTrack as ONNX, found by core/weights.py via sys._MEIPASS/weights.
    (str(WEIGHTS), "weights"),
    # The layered app icon (default, dark, clear, tinted) for macOS 26+. Lands
    # in Contents/Resources, where CFBundleIconName points macOS at it.
    (str(ICON_DIR / "Assets.car"), "."),
]

binaries = [
    # ffmpeg for clip extraction. A Finder-launched app gets a PATH without
    # Homebrew, so this bundled copy is what actually runs.
    (imageio_ffmpeg.get_ffmpeg_exe(), "imageio_ffmpeg/binaries"),
]

hiddenimports = [
    # Detectors, routers and the app are imported lazily or by string.
    *collect_submodules("reefscanner"),
    # uvicorn picks its protocol/loop implementations by import string.
    *collect_submodules("uvicorn"),
    "webview.platforms.cocoa",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src"), str(ROOT.parent / "core" / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "jupyter", "pytest", "notebook"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ReefScanner",
    console=False,
    target_arch="arm64",
    codesign_identity=SIGN_IDENTITY,
    entitlements_file=ENTITLEMENTS,
)

coll = COLLECT(exe, a.binaries, a.datas, name="ReefScanner")

app = BUNDLE(
    coll,
    name="ReefScanner.app",
    # Signs with the EXE's codesign_identity and entitlements.
    bundle_identifier="io.github.simonicarlo.reefscanner",
    # The flat fallback for macOS 12-15; newer macOS uses Assets.car instead.
    icon=str(ICON_DIR / "AppIcon.icns"),
    info_plist={
        "CFBundleName": "ReefScanner",
        "CFBundleDisplayName": "ReefScanner",
        "CFBundleIconName": "AppIcon",
        "CFBundleShortVersionString": os.environ.get("REEFSCANNER_VERSION", "0.0.0"),
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
