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
)

coll = COLLECT(exe, a.binaries, a.datas, name="ReefScanner")

app = BUNDLE(
    coll,
    name="ReefScanner.app",
    bundle_identifier="io.github.simonicarlo.reefscanner",
    info_plist={
        "CFBundleName": "ReefScanner",
        "CFBundleDisplayName": "ReefScanner",
        "CFBundleShortVersionString": os.environ.get("REEFSCANNER_VERSION", "0.0.0"),
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
