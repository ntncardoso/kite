"""Where things are kept on disk, and the identity of this installation.

Two kinds of state, deliberately apart:
  - config.json  — this machine: network interface, ports, MIDI, which console;
  - Sessions/    — a show: the patch sheet, names, console buttons.
Copying a session between machines must never drag network settings with it.
"""

import json
import os
import shutil
import sys
from pathlib import Path

from . import DATA_DIR_NAME

# Directories earlier names of this app wrote to, newest first. Read once, on a
# machine that has no data of its own yet, so a rename keeps the user's sessions
# instead of silently starting them empty.
_LEGACY_DIR_NAMES = ("Patchway", "patchway", "WingSuperRack", "wing-superrack")


def _base_dir(name):
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / name
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / name.lower()


def config_dir():
    d = _base_dir(DATA_DIR_NAME)
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "config.json").exists():
        _adopt_legacy_data(d)
    return d


def _adopt_legacy_data(dest):
    """Take over the data an earlier name of this app left behind. Copy, never
    move: if this version is rolled back, the old one still finds its files."""
    for name in _LEGACY_DIR_NAMES:
        src = _base_dir(name)
        if not (src.exists() and src != dest):
            continue
        try:
            if (src / "config.json").exists():
                shutil.copy2(src / "config.json", dest / "config.json")
            if (src / "Sessions").is_dir():
                shutil.copytree(src / "Sessions", dest / "Sessions", dirs_exist_ok=True)
        except OSError:
            pass                            # nothing here is worth failing a launch
        return


CONFIG = config_dir() / "config.json"
SESSIONS = config_dir() / "Sessions"


def default_config():
    return {"wingHost": "", "consoleName": "", "iface": "", "prolinkPort": 57999,
            "map": {}, "anchors": {}, "names": {}, "rackNames": {}, "rackCount": 64,
            "follow": True, "buttons": {}}


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return default_config()


def save_config(cfg):
    """Write config.json whole, via a temporary file.

    A half-written config is worse than an old one: the app would come back
    with an empty patch sheet. The replace is atomic on both platforms.
    """
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        tmp.replace(CONFIG)
        return True
    except OSError:
        return False


def desktop_dir():
    """Where to put a file the person is meant to find.

    Not `~/Desktop`. On Windows the Desktop is a known folder that is routinely
    somewhere else: redirected into OneDrive on a managed machine, or — on a
    virtual machine sharing the host's profile — on the host altogether
    (C:\\Mac\\Home\\Desktop, seen 2026-09-23). Writing to `~/Desktop` there
    creates a folder nobody ever looks in, and the export appears to have done
    nothing. Ask the system where it is, and fall back to the home directory
    rather than inventing a Desktop.
    """
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                d = Path(winreg.QueryValueEx(k, "Desktop")[0])
                if d.is_dir():
                    return d
        except OSError:
            pass
    d = Path.home() / "Desktop"
    return d if d.is_dir() else Path.home()


def machine_id():
    """A stable per-installation id from the OS, or None.

    macOS: IOPlatformUUID. Windows: MachineGuid (set at OS install). Linux:
    /etc/machine-id. None of these is a network address.
    """
    try:
        if sys.platform == "darwin":
            import re
            import subprocess
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                 capture_output=True, text=True, timeout=3).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]+)"', out)
            return m.group(1) if m else None
        if os.name == "nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return winreg.QueryValueEx(k, "MachineGuid")[0]
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if Path(path).exists():
                v = Path(path).read_text().strip()
                if v:
                    return v
    except Exception:
        pass
    return None
