"""One file a tester can attach to a bug report.

Someone testing this is doing us a favour on their own gear, in their own
room, usually the evening before a show. Asking them to find a log, work out
which lines matter and remember their versions is a good way to get no report
at all. One button writes a zip with the log and the facts that explain it.

Two rules, and the report says both out loud so the person can check:
  - nothing leaves this machine. The file is written to disk and it is theirs
    to send, or not;
  - the show does not go in it. The patch sheet, the names and the session
    names are the customer's work, so the report carries counts and never
    content.
"""

import json
import platform
import socket
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from . import APP_NAME, __version__, paths, runtime

# Machine settings worth having in a report. Anything not listed is left out,
# which is the safe way round: a key added later is private until someone
# decides otherwise.
CONFIG_KEYS = ("iface", "prolinkPort", "consoleName", "wingHost", "wingEnabled",
               "follow", "rackCount", "navigateOverMidi",
               "buttons", "buttonsOwned", "buttonsPending", "buttonsToFree")

# Counted, never quoted: this is the customer's show.
COUNTED_KEYS = ("map", "anchors", "names", "rackNames")


def _redact(text):
    """Take the person's name out of any path that got in."""
    home = str(Path.home())
    return str(text).replace(home, "~")


def _section(title, body):
    return f"--- {title} ---\n{body}\n\n"


def _safe(fn, default="(could not be read)"):
    try:
        return fn()
    except Exception as e:
        return f"{default}: {e}"


def report(app):
    """The facts that make a log readable, as text."""
    out = f"{APP_NAME} {__version__} — diagnostics\n"
    out += f"written {datetime.now().isoformat(timespec='seconds')}\n\n"
    out += ("This file is yours. Nothing was sent anywhere; attach it to a report if\n"
            "you want to. It deliberately leaves out your patch sheet, your names and\n"
            "your session names — only counts of those appear below.\n\n")

    out += _section("machine", _safe(lambda: "\n".join([
        f"system: {platform.system()} {platform.release()} ({platform.machine()})",
        f"python: {platform.python_version()}",
        f"packaged: {'yes' if getattr(sys, 'frozen', False) else 'no, running from source'}",
        f"hostname set: {'yes' if socket.gethostname() else 'no'}",
    ])))

    out += _section("rack host", _safe(lambda: "\n".join([
        f"connected: {app.waves.connected}",
        f"peer: {app.waves.peer}",
        f"racks: {len(app.waves.racks)}",
        f"health: {app.waves.health}",
    ])))

    out += _section("console", _safe(lambda: "\n".join([
        f"configured: {bool(app.cfg.get('wingHost'))}",
        f"answering: {bool(app.wing and app.wing.alive)}",
        f"follow selection: {app.cfg.get('follow', True)}",
    ])))

    out += _section("midi", _safe(lambda: "\n".join([
        f"port open: {bool(app.midi.out)}",
        f"port: {app.midi.port}",
        f"survives a restart: {app.midi.persistent}",
        f"error: {app.midi.error}",
    ])))

    out += _section("network interfaces", _safe(lambda: "\n".join(
        f"{i['name']}: {i['ip']}/{i['netmask']} {'up' if i['up'] else 'down'}"
        for i in app.list_interfaces())))

    out += _section("settings", _safe(lambda: json.dumps(
        {k: app.cfg[k] for k in CONFIG_KEYS if k in app.cfg}, indent=2, ensure_ascii=False)))

    out += _section("the show, counted only", _safe(lambda: "\n".join(
        [f"{k}: {len(app.cfg.get(k) or {})} entries" for k in COUNTED_KEYS]
        + [f"sessions saved: {len(list(paths.SESSIONS.glob('*.json')))}",
           f"a session is open: {'yes' if app.cfg.get('session') else 'no'}"])))

    out += _section("recent activity", _safe(lambda: "\n".join(app.logs[-40:])))
    return _redact(out)


def bundle(app, out_dir=None):
    """Write the report and the log files into one zip. Returns its path."""
    stamp = datetime.now().strftime("%Y-%m-%d %H%M")
    out = Path(out_dir or paths.desktop_dir()) / f"{APP_NAME} diagnostics {stamp}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)

    log = paths.config_dir() / runtime.LOG_NAME
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.txt", report(app))
        # The rotated files as well: a problem from last night is in one of them.
        for name in [runtime.LOG_NAME] + [f"{runtime.LOG_NAME}.{n}"
                                          for n in range(1, runtime.BACKUPS + 1)]:
            f = log.with_name(name)
            if f.exists():
                z.write(f, name)
    return out
