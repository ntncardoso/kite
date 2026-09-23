"""The rack host's 16 USER KEYS: what each one is, and how to fire it.

The remote-control protocol has no command for USER KEYS, so they are reached
over MIDI instead — see midi_link.py. What is left is telling the engineer
which key is which, on a console screen 16 characters wide. Everything in this
module is read-only: it copies files before reading them and writes nothing
back to the host.
"""

import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

# The USER KEY functions the host offers, by the code its session file stores.
# Collected for interoperability: without them a key number means nothing and
# the console screen can only say "KEY 7". 0 means the key is unassigned.
# Confirmed against a live session — 16, 17 and 20 are what the host's own log
# calls Toggle View, Last Rack and Tap Tempo.
UK_ACTIONS = {
    1: "Save Session", 2: "Load Session", 3: "Save Rack Preset",
    4: "Copy Rack Preset", 5: "Paste Rack Preset", 6: "Copy Plugin & Preset",
    7: "Paste Plugin & Preset", 8: "Snapshot Undo", 9: "Recall Hot Snapshot",
    10: "Recall Snapshot", 11: "Show Snapshot Menu", 12: "View Rack",
    13: "View Plugin", 14: "Previous Rack", 15: "Next Rack", 16: "Toggle View",
    17: "Last Rack", 18: "Show Preset Menu", 19: "Lock", 20: "Tap Tempo",
    21: "Mute Rack", 22: "Plugin Bypass", 23: "FlipAB Input Rack",
    26: "Mute ALL", 29: "Store Snapshot", 30: "Store New Snapshot",
    31: "Next Snapshot", 32: "Previous Snapshot", 33: "Custom Layer",
    35: "Bypass Rack", 36: "Go Back", 37: "Go Forward",
    38: "FlipAB Output Rack", 47: "KeyBoard", 48: "Next Mode",
    50: "Bypass All Racks",
}

# Where the host keeps these files. Both are read as evidence, never written.
# The first candidate that exists wins, and either can be overridden in the
# config (userKeysSessionFile / userKeysLogFile) — the install can be moved,
# and the Windows locations below have not been confirmed on a machine yet.
if os.name == "nt":
    _PUBLIC = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    _APPDATA = Path(os.environ.get("APPDATA", Path.home()))
    SESSION_CANDIDATES = [
        _PUBLIC / "Waves Audio/SuperRack Performer/Sessions/CurrentSPRKP.dat",
        _PUBLIC / "Waves/SuperRack Performer/Sessions/CurrentSPRKP.dat",
    ]
    LOG_CANDIDATES = [
        _APPDATA / "Waves Audio/Logs/SuperRack PerformerApplication.log",
        _PUBLIC / "Waves Audio/Logs/SuperRack PerformerApplication.log",
    ]
else:
    SESSION_CANDIDATES = [
        Path("/Users/Shared/Waves/SuperRack Performer/Sessions/CurrentSPRKP.dat"),
    ]
    LOG_CANDIDATES = [
        Path.home() / "Library/Logs/Waves Audio/SuperRack PerformerApplication.log",
    ]


def _pick(override, candidates):
    """The file to read: what was configured, else the first one that is there
    (and, when none is, the first candidate — so the caller reports a path a
    person can recognise)."""
    if override:
        return Path(override)
    return next((c for c in candidates if c.exists()), candidates[0])

_LOG_LINE = re.compile(r"Set UserKey (\d+) to (.+?)(?: @\[|\s*$)")

SCREEN_WIDTH = 16          # characters a console button name gets


def label(name, width=SCREEN_WIDTH):
    """Fit a key name onto a console button.

    "Toggle View: Overview1" is clearer cut after the colon than truncated to
    "Toggle View: Ove", so the qualifier wins when the whole thing will not fit.
    """
    name = str(name or "")
    if len(name) > width and ":" in name:
        name = name.split(":", 1)[1].strip()
    return name[:width]


def stamp(session_file=None, log_file=None):
    """What the two source files look like right now, cheaply.

    Reading the assignments copies a session file and opens a database; doing
    that every few seconds forever, on a machine also running a show, is rude.
    The caller polls this instead and only reads when it changes.
    """
    out = []
    for path in (_pick(session_file, SESSION_CANDIDATES), _pick(log_file, LOG_CANDIDATES)):
        try:
            st = path.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def read_assignments(session_file=None, log_file=None):
    """What each USER KEY is set to, as {key number: name}, or None.

    Two read-only sources, because neither is enough on its own:
      - the open session (SQLite, table user_keys) says which keys are
        assigned; key_action 0 means none, and its friendly name is empty;
      - the host's log writes the readable name each time a key is assigned:
        "Setup > Settings: Set UserKey 0 to Toggle View: Overview1" — the key
        numbers there are 0-based.
    The session is copied before reading, so the host's own file is untouched
    and never locked while it is playing.

    None means there is no session to read, which is not the same as a session
    with no keys assigned: the caller must not wipe what it already knows.
    """
    src = _pick(session_file, SESSION_CANDIDATES)
    if not src.exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / src.name
        for suffix in ("", "-wal"):                # -wal holds the newest writes
            f = Path(str(src) + suffix)
            if f.exists():
                shutil.copy2(f, str(dst) + suffix)
        con = sqlite3.connect(dst)
        try:
            rows = con.execute("select key_index, key_action from user_keys").fetchall()
        finally:
            con.close()
    actions = {int(i) + 1: int(a) for i, a in rows if a}

    names = _names_from_log(log_file)
    out = {}
    for n, action in sorted(actions.items()):
        base = UK_ACTIONS.get(action, f"Function {action}")
        logged = names.get(n, "")
        # The log line carries the target too ("Toggle View: Overview1"), so
        # prefer it when it is the same function spelled out further.
        out[n] = logged if logged.startswith(base) else base
    return out


def _names_from_log(log_file=None):
    path = _pick(log_file, LOG_CANDIDATES)
    names = {}
    if not path.exists():
        return names
    try:
        with path.open(errors="ignore") as fh:
            for line in fh:
                m = _LOG_LINE.search(line)
                if m:                    # later lines win: the last one is current
                    names[int(m.group(1)) + 1] = m.group(2).strip()
    except OSError:
        pass
    return names


def build_mrrc(commands, channel, host_version):
    """The host's MIDI map file, so its keys are mapped in one import instead
    of learnt one by one.

    `commands` is a list of (command name, CC number). The layout follows a
    file the host exported itself; the version string is kept because a file
    without it was refused, taking the whole existing map with it.
    """
    body = "".join(
        f"""  <Command>
   <Name>{name}</Name>
   <RelativeMode>0</RelativeMode>
   <MIDI>
    <MessageType>Control Change</MessageType>
    <Channel>0x{channel - 1:02X}</Channel>
    <Number>0x{cc:02X}</Number>
    <Param>-2</Param>
    <BigNumber>0x00</BigNumber>
   </MIDI>
  </Command>
""" for name, cc in commands)
    return f"""<MultiRackRemoteControl>
 <DisplayMTC>false</DisplayMTC>
 <FollowProgramChange>false</FollowProgramChange>
 <UseCCForScenesControl>false</UseCCForScenesControl>
 <GenerateProgramChange>false</GenerateProgramChange>
 <FollowMixer1>true</FollowMixer1>
 <MIDITakeover>false</MIDITakeover>
 <ScenesInputChannel>-1</ScenesInputChannel>
 <FileVersion>1.0.0.0</FileVersion>
 <MultiRackVersion>{host_version}</MultiRackVersion>
 <Commands>
  <NumberOfCommands>{len(commands)}</NumberOfCommands>
{body} </Commands>
</MultiRackRemoteControl>
"""
