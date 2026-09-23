# PyInstaller build, for macOS and Windows from one file.
#
#   pyinstaller --noconfirm packaging/Kite.spec
#
# What goes in: the package, the page in kite/web, and the libraries the app
# imports. What does NOT go in: anything from the config directory. Settings,
# sessions and logs belong to the machine the app runs on, never to the build.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).parent))          # noqa: F821 — PyInstaller global
from kite import APP_NAME, __version__                  # noqa: E402

HERE = Path(SPECPATH)                                   # noqa: F821
ROOT = HERE.parent
WINDOWS = sys.platform == "win32"

a = Analysis(
    [str(HERE / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "kite" / "web"), "kite/web")],
    # Each of these is loaded by name at runtime, so the analysis cannot see it.
    hiddenimports=[
        "rtmidi",                       # the MIDI output
        "pystray._win32" if WINDOWS else "pystray._darwin",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    excludes=["tkinter", "pytest", "ruff", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)                                       # noqa: F821

exe = EXE(                                              # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,                    # compressed sections are what antivirus dislikes
    console=False,                # it has a window and a tray icon; no terminal
    icon=str(HERE / ("icon.ico" if WINDOWS else "icon.icns")),
)

coll = COLLECT(                                         # noqa: F821
    exe, a.binaries, a.datas,
    strip=False, upx=False, name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(                                       # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=str(HERE / "icon.icns"),
        # Reverse-DNS of where the project lives, not of whoever built it:
        # a machine account name has no business inside a shipped bundle.
        bundle_identifier="com.github.ntncardoso.kite",
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # It listens on the local network for the console and the rack host,
            # which macOS asks the user to allow. Say why, in their words.
            "NSLocalNetworkUsageDescription":
                "Kite talks to the mixing console and the plugin host on this network.",
        },
    )
