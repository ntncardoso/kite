# Kite

[![tests](https://github.com/ntncardoso/kite/actions/workflows/tests.yml/badge.svg)](https://github.com/ntncardoso/kite/actions/workflows/tests.yml)

Links the strips of a mixing console to the racks of a plugin host: select the
strip on the console and its rack opens on screen. No reaching for the mouse
in the middle of a show.

Works with the Behringer WING (over OSC) and Waves SuperRack Performer (over
its remote-console protocol and MIDI). See [Notice](#notice).

- macOS and Windows.
- Lives in the menu bar / tray. Closing the window does not stop the bridge;
  only **Quit** in the tray does.
- **It never writes audio routing.** It sends which rack to show and, if you
  ask for it, names.

## What it does

| | |
|---|---|
| **Patch** | The strip ↔ rack grid. A strip links to exactly one rack, and the link remembers the rack's name: if racks are reordered, the bridge holds the link and says so instead of opening the wrong rack. |
| **Names** | Reads names from both sides and copies them across. Writing is always explicit. |
| **USER keys** | The host's 16 USER KEYS, fired over MIDI, and the console's 16 USER buttons that can fire them. Exports the host's MIDI map file so they are mapped in one import. |
| **Sessions** | A show is a file. It saves when you say so — editing the grid saves nothing on its own. Machine settings (network, ports, identity) stay out of the session. |
| **Activity** | What the bridge did, in order. The first place to look when something does not open. |

## Tested against

Nothing here is guesswork, and nothing here is a guarantee: this is the exact
equipment it has been run on.

| | Verified | Notes |
|---|---|---|
| Behringer WING Compact | yes, live | Strip selection, names, all 16 USER buttons |
| Waves SuperRack Performer 15.15.12.13 | yes, live | Rack display, inventory, health, USER KEYS over MIDI |
| macOS 15 (Apple silicon) | yes, live | The bundle in Releases |
| Windows 11 (x64) | **partly** | Builds and runs, full test suite passes — but it has **never been connected to a console**. Treat the Windows build as untested in the field. |

Other WING models and other SuperRack versions are likely to work and have not
been tried. A protocol that changes with a manufacturer's update will take this
with it; test before a show.

## What it writes

Almost everything Kite does is read-only. Three things are not, and all three
are yours to trigger:

- **Console USER buttons.** Assigning one writes that button's mode and its
  screen name. Kite refuses any button that is not OFF unless you confirm, and
  puts back to OFF only the buttons it set up itself.
- **Names**, when you press Push — on the console, on the rack host, or both.
- **Which rack is on screen** in the rack host. That is the point of the thing.

It never writes audio routing, on either device.

## Install

Needs Python 3.11 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m kite
```

On macOS, `Open Kite.command` does the same with a double-click; on
Windows, `Open Kite.bat`.

### MIDI port

The host's USER KEYS are fired over MIDI, on a port named `WING Bridge`.
Create it **once** and leave it there:

- macOS — Audio MIDI Setup → IAC Driver → add a bus with that name;
- Windows — loopMIDI, a port with that name.

If there is none, macOS gets a temporary port that dies with the app, and the
host stops finding it on every restart. The app says so when that happens.

### First run on Windows

Windows Firewall asks whether to allow the app on private and public networks.
It has to be allowed on the network the console and the rack host are on, or
the host will never find the console: it is the host that opens the connection.

### Console and host

1. In the app, pick the network interface and connect to the console by IP
   (there is a scan).
2. In the plugin host's remote-console window, tick **Assign** on the console
   that appears. Once is enough: the machine's identity is stable, so it
   reconnects on its own from then on.

## Building

```sh
.venv/bin/pip install pyinstaller
.venv/bin/python packaging/icon.py            # only after changing the icon
.venv/bin/pyinstaller --noconfirm packaging/Kite.spec
```

One spec builds both platforms: `dist/Kite.app` on macOS, `dist/Kite/Kite.exe`
on Windows. Windows is built on Windows — PyInstaller does not cross-compile —
and needs the Microsoft Visual C++ runtime present, or the MIDI extension will
not load. Neither build is code-signed, so the first run asks for confirmation:
on macOS, right-click → Open; on Windows, More info → Run anyway.

Nothing from the config directory goes into a build. Settings, sessions and
logs belong to the machine the app runs on.

## Development

```sh
.venv/bin/pytest        # 61 tests, none of which opens a socket
.venv/bin/ruff check .
```

Layout:

```
kite/
  __init__.py   name and version, in one place
  paths.py      where config and sessions live; the machine identity
  runtime.py    the rotating log file and supervised threads
  prolink.py    the remote-console endpoint the host connects to
  wing_link.py  the console's OSC client (selection, names, USER buttons)
  midi_link.py  the MIDI output that fires the host's USER KEYS
  sessions.py   session commands over the config dictionary
  userkeys.py   USER KEY names and the host's MIDI map file
  tray.py       the menu-bar icon
  app.py        the wiring, and the API the page calls
  web/          index.html, app.css, app.js
```

Why each protocol decision is what it is lives in the comments next to the
code that depends on it. `CHANGELOG.md` records the releases.

## Notice

Kite is an independent tool, written for interoperability: so that
equipment somebody already owns works together. It contains, distributes and
modifies no third-party software, and circumvents no copy protection or
licensing mechanism.

Behringer and WING are trademarks of Music Tribe. Waves, SuperRack and ProLink
are trademarks of Waves Audio Ltd. Those names appear here only to identify the
equipment this tool works with. Kite is not affiliated with, authorised by
or endorsed by either company.

Protocol behaviour was observed from the normal operation of the equipment
itself and may change with any update. Test before using it on a show. The
software comes with no warranty — see [LICENSE](LICENSE).
