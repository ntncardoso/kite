"""The application: devices in, window and tray out.

Ties the pieces together — the remote-control endpoint the rack host talks to
(prolink.py), the console's OSC client (wing_link.py), the MIDI output for the
host's USER KEYS (midi_link.py) — and exposes them to the page in web/ as the
JS API.

Main thread: on macOS both the window toolkit and the tray want it. The window
keeps it (`webview.start()`) and the tray runs detached. If the tray fails on
some system the app still works — it just loses the icon.
"""

import json
import os
import queue
import socket
import sys
import time
import webbrowser
from pathlib import Path

from . import APP_NAME, __version__, diagnostics, paths, runtime, userkeys
from .midi_link import CHANNEL as MIDI_CHANNEL
from .midi_link import MidiLink
from .prolink import ProLinkConsole
from .sessions import SessionStore
from .tray import Tray
from .wing_link import WingLink

HERE = Path(__file__).resolve().parent
PAGE = HERE / "web" / "index.html"

# One instance at a time. Two would fight over the remote-control port and the
# MIDI port, and which one is driving would be anyone's guess.
SINGLE_INSTANCE_PORT = 57998


class App:
    """Everything the page can call is a public method here."""

    PUSH_QUEUE_MAX = 500          # about a minute of the busiest traffic there is

    def __init__(self):
        self.cfg = paths.load_config()
        self._pushq = queue.Queue(maxsize=self.PUSH_QUEUE_MAX)
        self.window = None
        self.tray = None
        self.last_rack = None
        self.logs = []

        self.waves = self._make_waves()
        self.wing = None
        self.midi = MidiLink(log=self._log)
        self.uk_names = {}                 # host USER KEY number -> its name
        self.sessions = SessionStore(
            self.cfg, save=self._save_config, log=self._log,
            rack_count=lambda: len(self.waves.racks),
            on_load=lambda: runtime.spawn(self._apply_session_buttons,
                                          name="session-buttons"))

    def _save_config(self):
        return paths.save_config(self.cfg)

    def _console_uid(self):
        """The id the rack host knows this console by.

        The host stores its assignment against this id, so it must be stable.
        It is derived from the MACHINE rather than kept in config.json: copying
        the config to another computer then does not clone the identity, and
        wiping the config does not force a new Assign. Never derived from a MAC
        address — macOS rotates Wi-Fi MACs. The raw machine id is hashed with an
        app salt, so what goes on the wire says nothing outside this app.

        Changing the salt below invalidates every existing assignment. Don't.
        """
        import hashlib
        mid = paths.machine_id()
        if mid:
            return hashlib.sha256(b"wing-superrack/console-uid/" + mid.encode()).digest()[:16]
        # No machine id available: fall back to one random id, kept in config.
        try:
            uid = bytes.fromhex(self.cfg.get("consoleUidFallback", ""))
            if len(uid) == 16:
                return uid
        except ValueError:
            pass
        uid = os.urandom(16)
        self.cfg["consoleUidFallback"] = uid.hex()
        self._save_config()
        return uid

    def _make_waves(self):
        return ProLinkConsole(name=self.cfg.get("consoleName") or APP_NAME,
                              uid=self._console_uid(),
                              tcp_port=int(self.cfg.get("prolinkPort") or 57999),
                              iface=self.cfg.get("iface") or None,
                              on_event=self._on_waves)

    def _iface_ip(self, name):
        """Current IPv4 of an interface, looked up now — never stored, since it
        changes when the machine joins another network."""
        if not name:
            return None
        import psutil
        for a in psutil.net_if_addrs().get(name, []):
            if a.family == socket.AF_INET:
                return a.address
        return None

    # ---------------------------------------------------------- events

    _closing = False
    _quitting = False
    _page_ready = False

    def _push(self, kind, payload):
        """Hand an event to the page. Never waits, and never fails.

        evaluate_js schedules the call on the UI thread and blocks until the
        page answers. Called FROM that thread it waits for itself: closing the
        window logged a line, the log pushed it, and the whole application
        deadlocked inside the close handler — the window would not go away and
        macOS reported it as not responding (seen 2026-09-23).

        So nothing pushes directly. Events go on a queue that one thread
        drains, and no caller can block on the page no matter which thread it
        runs on. The queue is bounded: if the page ever stopped answering, the
        bridge keeps bridging and drops the oldest chatter instead of growing
        until the machine complains.
        """
        if not self.window or self._closing:
            return
        try:
            self._pushq.put_nowait((kind, payload))
        except queue.Full:
            try:
                self._pushq.get_nowait()          # drop the oldest, keep the newest
                self._pushq.put_nowait((kind, payload))
            except (queue.Empty, queue.Full):
                pass

    def _push_loop(self):
        """The one thread allowed to talk to the page."""
        while not self._closing:
            kind, payload = self._pushq.get()
            if self._closing or not self._page_ready or not self.window:
                continue
            try:
                self.window.evaluate_js(
                    "window.onBridgeEvent && window.onBridgeEvent("
                    f"{json.dumps(kind)}, {json.dumps(payload, ensure_ascii=False)})")
            except Exception:
                pass                              # a page that will not listen is not fatal

    def _log(self, msg):
        runtime.log_line(msg)              # and to the file, which outlives the window
        self.logs.append(msg)
        del self.logs[:-300]
        self._push("log", msg)

    def _on_waves(self, kind, payload):
        if kind == "log":
            self._log(f"rack host: {payload}")
        elif kind == "status":
            self._log("rack host connected" if payload["connected"]
                      else f"rack host disconnected ({payload.get('reason') or 'session ended'})")
            self._push("status", self.status())
            self._refresh_tray()
        elif kind == "racks":
            self._log(f"inventory: {len(payload)} racks")
            self._push("racks", payload)
        elif kind == "health":
            self._push("health", payload)
            self._refresh_tray()

    # ------------------------------------------------- console USER buttons

    # cfg["buttons"] maps an action to a button key ("U2/1/bu"). Assigned by
    # Learn: the next press is taken. The rack host's own navigation commands
    # were mapped over MIDI and moved nothing, so navigation goes over the
    # remote-control protocol instead — see navigate().
    ACTIONS = {"plugin-next": ("plugin", 1, 17), "plugin-prev": ("plugin", 0, 18),
               "rack-next": ("rack", 1, 19), "rack-prev": ("rack", 0, 20)}
    LABELS = {"plugin-next": "SR PLG >", "plugin-prev": "SR PLG <",
              "rack-next": "SR RACK >", "rack-prev": "SR RACK <"}

    # The 16 physical USER buttons: banks U1-U4, four each, so USER n is
    # bank (n-1)//4 + 1, button (n-1)%4 + 1. The custom-control pages (layers
    # 1-16) are left out on purpose — they are the same eight controls with
    # sixteen sets of settings, and only answer while their page is selected.
    # GPIO is left out until its addressing is confirmed on the console.
    BUTTON_KEYS = [f"U{b}/{n}/bu" for b in range(1, 5) for n in range(1, 5)]

    # A button set to a MIDI mode also needs an assignment of its OWN. Two
    # buttons left on the same channel and CC are mirrored by the console: one
    # press reports on both addresses, a millisecond apart, and the bridge
    # dutifully fires both actions. Found live on 2026-09-24, with U1/1 and
    # U1/3 both sitting on the factory default (channel 1, CC 0).
    #
    # Channel 16 and CC 100 upwards: clear of the 1-16 this app sends to the
    # rack host, and clear of anything an engineer is likely to have set by
    # hand on a console's lower channels.
    BUTTON_MIDI_CHANNEL = 16

    @classmethod
    def _button_cc(cls, key):
        """A CC number that belongs to this button and no other."""
        return 100 + cls.BUTTON_KEYS.index(key)

    def _write_button_midi(self, key):
        """Give a button we own an assignment nothing else shares."""
        base = f"/$ctl/user/{key}"
        self.wing.send(f"{base}/ch", [("i", self.BUTTON_MIDI_CHANNEL)])
        self.wing.send(f"{base}/cc", [("i", self._button_cc(key))])

    def _repair_button_midi(self):
        """Re-check the buttons this app set up, and fix any that collide.

        Runs when the console starts answering: a console configured by an
        earlier version has buttons sharing channel 1 / CC 0, and until they
        are separated every press fires two actions.
        """
        if not (self.wing and self.wing.alive):
            return
        owned = list(self.cfg.get("buttonsOwned", []))
        if not owned:
            return
        addrs = [f"/$ctl/user/{k}/{leaf}" for k in owned for leaf in ("ch", "cc")]
        got = self._wing_query(addrs)
        for key in owned:
            ch = (got.get(f"/$ctl/user/{key}/ch") or [None])[0]
            cc = (got.get(f"/$ctl/user/{key}/cc") or [None])[0]
            want_cc = self._button_cc(key)
            if int(ch or 0) != self.BUTTON_MIDI_CHANNEL or int(cc or 0) != want_cc:
                self._write_button_midi(key)
                self._log(f"button {key}: MIDI assignment was channel {ch} CC {cc} — "
                          f"moved to channel {self.BUTTON_MIDI_CHANNEL} CC {want_cc}, "
                          f"so the console stops mirroring it onto another button")

    _learning = None

    def _on_wing_button(self, key):
        if self._learning:
            action, self._learning = self._learning, None
            self._bind(action, key)
            self._save_config()
            self._log(f"button {key} -> {action}")
            self._push("buttons", {"buttons": self.cfg["buttons"], "learning": None})
            return
        for action, k in self.cfg.get("buttons", {}).items():
            if k != key:
                continue
            if action in self.ACTIONS:
                what, direction, _ = self.ACTIONS[action]
                self._nav_bg(what, direction)
            elif self._uk(action):
                self.press_user_key(self._uk(action))

    def _wing_query(self, addrs, wait=0.6, batch=48):
        """Ask the console for many addresses; return {addr: [args]} for those answered."""
        w = self.wing
        for a in addrs:
            w.raw.pop(a, None)
        for i in range(0, len(addrs), batch):
            for a in addrs[i:i + batch]:
                w.get(a)
            time.sleep(0.08)                   # do not flood the console over Wi-Fi
        time.sleep(wait)
        return {a: w.raw[a] for a in addrs if a in w.raw}

    def scan_buttons(self):
        """Every USER button on the console with what it does now. Read only.

        A button that does not answer does not exist on this model.
        """
        if not (self.wing and self.wing.alive):
            return {"ok": False, "msg": "the console is not answering"}
        keys = list(self.BUTTON_KEYS)
        addrs = [f"/$ctl/user/{k}/{leaf}" for k in keys for leaf in ("mode", "name", "$fname")]
        got = self._wing_query(addrs)

        def first(a):
            return (got.get(a) or [""])[0]

        out = []
        for k in keys:
            if f"/$ctl/user/{k}/mode" not in got:
                continue
            layer, n, row = k.split("/")
            out.append({"key": k, "layer": layer, "n": int(n), "row": row,
                        "mode": first(f"/$ctl/user/{k}/mode"),
                        "name": first(f"/$ctl/user/{k}/name"),
                        "fname": first(f"/$ctl/user/{k}/$fname")})
        return {"ok": True, "buttons": out}

    def _apply_pending(self):
        """Write to the console what was chosen while it was offline.

        Choices are kept in config as buttonsPending (to set up) and
        buttonsToFree (to put back to OFF), and applied the first moment the
        console answers. A button that turns out to be in use is left alone and
        said so in the log — replacing it needs a confirmation this cannot ask
        for on its own.
        """
        if not (self.wing and self.wing.alive):
            return
        for key in list(self.cfg.get("buttonsToFree", [])):
            self._free_button(key)
            self.cfg["buttonsToFree"].remove(key)
        self._repair_button_midi()
        for key in list(self.cfg.get("buttonsPending", [])):
            action = next((a for a, k in self.cfg.get("buttons", {}).items() if k == key), None)
            self.cfg["buttonsPending"].remove(key)
            if not action:
                continue
            r = self.assign_button(action, key)
            if not r.get("ok"):
                self._log(f"{key} not set up: {r.get('msg')}")
        self._save_config()

    def assign_button(self, action, key, replace=False):
        """Configure a FREE button on the console for an action.

        Writes the button's mode (MIDI CC push, so it reports presses) and a
        name for the console screen. Refuses any button that is not OFF right
        now, so nothing already set up on the console is overwritten.
        """
        if not self._valid_action(action):
            return {"ok": False, "msg": "unknown action"}
        if not (self.wing and self.wing.alive):
            # Offline: remember the choice and write it to the console later.
            self._bind(action, key)
            pending = self.cfg.setdefault("buttonsPending", [])
            if key not in pending:
                pending.append(key)
            self._save_config()
            return {"ok": True, "pending": True, "buttons": self.cfg["buttons"]}
        base = f"/$ctl/user/{key}"
        mode = (self._wing_query([f"{base}/mode"]).get(f"{base}/mode") or [None])[0]
        if mode in ("MIDICCP", "MIDICCT", "MIDINP", "MIDINT"):
            # Already in a mode that reports presses — set up by hand, or left
            # that way by an earlier session. Its function is not touched, but
            # its NAME is: a button that now fires a rack key must say so on
            # the console's screen, or the desk shows one thing and does
            # another. Taking it over silently is how this looked broken: the
            # app said yes, and nothing on the console changed (2026-09-24).
            # The old name is kept so releasing the button can put it back.
            ours = key in self.cfg.get("buttonsOwned", [])
            if ours:
                self._write_button_midi(key)      # ours: keep it separated
            else:
                self.cfg.setdefault("buttonsAdopted", {}).setdefault(
                    key, (self._wing_query([f"{base}/name"]).get(f"{base}/name") or [""])[0])
            self.wing.send(f"{base}/name", [("s", self._label(action))])
            self._bind(action, key)
            self._save_config()
            self._log(f"button {key} now fires {action}" if ours else
                      f"button {key} was already in {mode} — kept as it is, renamed for {action}")
            return {"ok": True, "adopted": not ours, "buttons": self.cfg["buttons"]}
        if mode != "OFF" and not replace:
            # In use for something else: only on explicit confirmation, since
            # the button's old function is lost (only mode and name could be
            # read back, not every parameter behind it).
            return {"ok": False, "inUse": mode,
                    "msg": f"That button is in use ({mode}). Replacing it loses what it does now."}
        if mode != "OFF":
            self._log(f"button {key} was {mode} — replaced for {action}")
        self.wing.send(f"{base}/mode", [("s", "MIDICCP")])
        self._write_button_midi(key)
        self.wing.send(f"{base}/name", [("s", self._label(action))])
        got = self._wing_query([f"{base}/mode", f"{base}/name"])
        if (got.get(f"{base}/mode") or [None])[0] != "MIDICCP":
            return {"ok": False, "msg": "the console did not take the setting"}
        old = self.cfg.setdefault("buttons", {}).get(action)
        if old and old != key and old in self.cfg.get("buttonsOwned", []):
            self._free_button(old)
        self._bind(action, key)
        owned = self.cfg.setdefault("buttonsOwned", [])
        if key not in owned:
            owned.append(key)
        self._save_config()
        self._log(f"button {key} set up on the console for {action}")
        return {"ok": True, "buttons": self.cfg["buttons"]}

    def _bind(self, action, key):
        btns = self.cfg.setdefault("buttons", {})
        for a in [a for a, k in btns.items() if k == key]:
            del btns[a]                        # one button, one action
        btns[action] = key

    def _free_button(self, key):
        """Put a button this app set up back to OFF, without a name."""
        if self.wing and self.wing.alive:
            self.wing.send(f"/$ctl/user/{key}/name", [("s", "")])
            self.wing.send(f"/$ctl/user/{key}/mode", [("s", "OFF")])
        owned = self.cfg.setdefault("buttonsOwned", [])
        if key in owned:
            owned.remove(key)

    def release_button(self, action):
        """Unlink an action. If this app set the button up, turn it back OFF on
        the console; a button configured by hand (Learn) is left as it is."""
        key = self.cfg.setdefault("buttons", {}).pop(action, None)
        freed = False
        adopted = self.cfg.setdefault("buttonsAdopted", {})
        if key and key in adopted:
            # Never ours to turn off; give back the name it had and let go.
            if self.wing and self.wing.alive:
                self.wing.send(f"/$ctl/user/{key}/name", [("s", adopted[key])])
            del adopted[key]
            self._save_config()
            return {"ok": True, "freed": False, "buttons": self.cfg["buttons"]}
        if key:
            pending = self.cfg.setdefault("buttonsPending", [])
            if key in pending:
                pending.remove(key)                    # never written, nothing to undo
            elif key in self.cfg.get("buttonsOwned", []):
                if self.wing and self.wing.alive:
                    self._free_button(key)
                    freed = True
                else:
                    # Put it back to OFF the next time the console answers.
                    self.cfg.setdefault("buttonsToFree", []).append(key)
                    self.cfg.setdefault("buttonsOwned", []).remove(key)
        self._save_config()
        return {"ok": True, "freed": freed, "buttons": self.cfg["buttons"]}

    def learn_button(self, action):
        """Take the next USER button press on the console for this action."""
        if not self._valid_action(action):
            return {"ok": False, "msg": "unknown action"}
        if not (self.wing and self.wing.alive):
            return {"ok": False, "msg": "the console is not answering"}
        self._learning = action
        return {"ok": True}

    def cancel_learn(self):
        self._learning = None
        return {"ok": True}

    def clear_button(self, action):
        self.cfg.setdefault("buttons", {}).pop(action, None)
        self._save_config()
        return {"buttons": self.cfg["buttons"]}

    # ------------------------------------------------------- USER KEYS

    # Actions are "uk1".."uk16"; the console button shows the key's name.
    @staticmethod
    def _uk(action):
        if isinstance(action, str) and action.startswith("uk") and action[2:].isdigit():
            n = int(action[2:])
            return n if 1 <= n <= 16 else None
        return None

    def _valid_action(self, action):
        return action in self.ACTIONS or self._uk(action) is not None

    def _label(self, action):
        n = self._uk(action)
        if n is None:
            return self.LABELS[action]
        return userkeys.label(self.uk_names.get(n) or f"SR KEY {n}")

    def press_user_key(self, n):
        """Fire USER KEY n (CC n, channel 16). Also what the host's MIDI Learn
        listens to while a key is being assigned."""
        n = int(n)
        if not self.midi.out:
            return {"ok": False, "msg": self.midi.error or "MIDI port not open"}
        self.midi.press(n)
        self._log(f"USER KEY {n} pressed")
        return {"ok": True}

    # The version string the host wrote into the file it exported here; kept
    # because an import without one was refused, taking the map with it.
    SR_VERSION = "15.15.12.13 Build 288878"

    # Only the USER KEYS go in the file. The host's own navigation commands
    # were tried there on CC 17-20: imported without complaint, but they moved
    # nothing (2026-09-22), so navigation stays on the remote-control protocol.
    MIDI_NAV = []

    def export_midi_map(self, out_dir=None):
        """Write the host's MIDI map file, so its 16 USER KEYS are mapped in one
        go instead of learnt one by one."""
        cmds = [(f"User Key #{n}", n) for n in range(1, 17)] + self.MIDI_NAV
        out = Path(out_dir or paths.desktop_dir()) / f"{APP_NAME}.mrrc"
        try:
            out.write_text(userkeys.build_mrrc(cmds, MIDI_CHANNEL, self.SR_VERSION))
        except OSError as e:
            return {"ok": False, "msg": f"could not write the file ({e})"}
        self._log(f"MIDI map written: {out}")
        return {"ok": True, "path": str(out), "count": len(cmds)}

    _uk_stamp = None
    _uk_warned = False

    def _refresh_user_keys(self):
        """One pass: re-read the host's USER KEYS if its files have moved on.

        Reading copies a session database, so it happens on a change and not on
        a timer — the host is running a show on the same machine.
        """
        stamp = userkeys.stamp()
        if stamp == self._uk_stamp:
            return False
        self._uk_stamp = stamp
        names = self._read_user_keys()
        # An empty table is not the same as no session: the host is open and
        # every key is unassigned, so every press we send lands on nothing.
        # Worth saying once — it looks exactly like a broken bridge.
        if names == {} and self.waves.connected and not self._uk_warned:
            self._uk_warned = True
            self._log("the rack host has no USER KEYS assigned — presses reach it "
                      "and do nothing until they are assigned in its settings")
        elif names:
            self._uk_warned = False
        if names is None or names == self.uk_names:
            return False
        self.uk_names = names
        self._push("userkeys", {str(k): v for k, v in names.items()})
        self._rename_uk_buttons()
        return True

    def _user_keys_loop(self):
        while not self._closing:
            try:
                self._refresh_user_keys()
            except Exception as e:
                self._log(f"reading USER KEYS failed: {e}")
            time.sleep(5)

    def _read_user_keys(self):
        return userkeys.read_assignments()

    def _rename_uk_buttons(self):
        """Show each USER KEY's name on the console button set up for it."""
        if not (self.wing and self.wing.alive):
            return
        owned = self.cfg.get("buttonsOwned", [])
        for action, key in self.cfg.get("buttons", {}).items():
            if self._uk(action) and key in owned:
                self.wing.send(f"/$ctl/user/{key}/name", [("s", self._label(action))])

    # ------------------------------------------------- strip -> rack

    _current_rack = None                       # last rack index this app opened

    def _on_wing_selection(self, fam, n, name):
        """Strip selected on the console -> open the rack it is linked to.

        Everything here runs on the console's receive thread, so it must never
        raise: an exception would kill that thread and the bridge would go
        quietly deaf.
        """
        self._push("selection", {"fam": fam, "n": n, "name": name})
        if not self.cfg.get("follow", True):
            return
        idx = self.cfg.get("map", {}).get(f"{fam}/{n}")
        if idx is None:
            self._log(f"{fam}/{n} has no rack mapped")
            return
        if idx == self.last_rack:
            return
        if not self.waves.connected:
            self._log(f"{fam}/{n} -> rack {idx + 1} skipped: the rack host is not connected")
            return
        # Opening by index alone would follow a reordered rack to the wrong
        # place without a word. The link remembers the name it was made against;
        # if the rack at that index no longer carries it, hold and say so.
        anchor = self.cfg.get("anchors", {}).get(f"{fam}/{n}")
        if anchor is not None and self.waves.racks:
            now = next((r["name"] for r in self.waves.racks if r["index"] == idx), None)
            if now != anchor:
                self._log(f"{fam}/{n} held: rack {idx + 1} is now {now!r}, was linked to "
                          f"{anchor!r} — check the patch sheet")
                return
        self.last_rack = idx
        ok, msg = self.waves.show_rack(idx)
        if ok:
            self._current_rack = idx       # rack next/previous start from here
        self._log(f"{fam}/{n} -> rack {idx + 1}" + ("" if ok else f" — failed: {msg}"))

    # -------------------------------------------------------------- JS API

    def status(self):
        return {
            "waves": {"connected": self.waves.connected, "peer": self.waves.peer,
                      "racks": len(self.waves.racks),
                      "health": self.waves.health if self.waves.connected else {}},
            "wing": {"connected": bool(self.wing and self.wing.alive),
                     "probing": bool(self.wing and not self.wing.alive),
                     "host": self.cfg.get("wingHost", "")},
            "follow": self.cfg.get("follow", True),
        }

    def get_state(self):
        return {"cfg": self.cfg, "status": self.status(), "version": __version__,
                "userKeys": {str(k): v for k, v in self.uk_names.items()},
                "midi": {"open": bool(self.midi.out), "error": self.midi.error,
                         "name": self.midi.name, "port": self.midi.port,
                         "persistent": self.midi.persistent},
                "racks": self.waves.racks, "logs": self.logs[-60:]}

    def save_mapping(self, data):
        for k in ("map", "anchors", "names", "rackNames", "rackCount"):
            if k in data:
                self.cfg[k] = data[k]
        return {"saved": self._save_config(), "path": str(paths.CONFIG)}

    def set_follow(self, on):
        self.cfg["follow"] = bool(on)
        self._save_config()
        self._refresh_tray()
        return self.status()

    def connect_wing(self, host):
        """Connect to the console, or disconnect when host is empty.

        Disconnecting keeps the address: it used to be wiped, and the app then
        came back with an empty field and nothing to reconnect to. What is
        remembered instead is whether to connect on start (wingEnabled).
        """
        host = (host or "").strip()
        if host:
            self.cfg["wingHost"] = host
        self.cfg["wingEnabled"] = bool(host)
        self._save_config()
        if self.wing:
            self.wing.stop()
            self.wing = None
        if not host:
            self._push("status", self.status())
            return self.status()
        bind_ip = self._iface_ip(self.cfg.get("iface"))
        self.wing = WingLink(host, log=lambda m: self._log(f"console: {m}"), bind_ip=bind_ip)
        self.wing.on_selection = self._on_wing_selection
        self.wing.on_button = self._on_wing_button

        def on_alive(alive):
            self._push("status", self.status())
            self._refresh_tray()
            if alive:
                runtime.spawn(self._apply_pending, name="apply-pending")

        self.wing.on_alive_change = on_alive
        try:
            self.wing.start()
        except OSError as e:
            self._log(f"console: failed to connect to {host}: {e}")
            self.wing = None
        self._push("status", self.status())
        return self.status()

    def show_rack(self, index):
        """Try one link without touching the console."""
        if not self.waves.connected:
            return {"ok": False, "msg": "the rack host is not connected"}
        ok, msg = self.waves.show_rack(int(index))
        if ok:
            self._current_rack = int(index)
        return {"ok": ok, "msg": msg}

    def navigate(self, what, direction):
        """Step the host's view: what = "rack" or "plugin", direction 1 = next.

        Display only — never touches audio.

        Plugins: the host's plugin navigation runs 0/1 opposite to next/previous
        as seen on screen (reported from use, 2026-09-22), so the value is
        inverted here.

        Racks: its rack navigation answers "succeeded" but stays on the current
        rack (also from use), so racks are stepped by opening them — the same
        command strip selection uses — skipping empty racks and starting from
        the last rack this app opened.
        """
        nxt = bool(direction)
        # The navigation commands in the exported MIDI map were imported but do
        # nothing (tested 2026-09-22: CC 17-20 leave the host unmoved, while the
        # USER KEY CCs work). Until their exact name or shape is known,
        # navigation goes over the remote-control protocol. Set navigateOverMidi
        # in config to try MIDI anyway.
        cc = next((c for w, d, c in self.ACTIONS.values() if w == what and bool(d) == nxt), None)
        if self.midi.out and cc and self.cfg.get("navigateOverMidi"):
            self.midi.press(cc)
            self._log(f"navigate {what} {'next' if nxt else 'previous'}: MIDI CC {cc}")
            return {"ok": True, "msg": "", "via": "midi"}
        if not self.waves.connected:
            return {"ok": False, "msg": "the rack host is not connected"}
        if what == "plugin":
            ok, msg = self.waves.navigate_plugin(0 if nxt else 1)
        else:
            racks = [r["index"] for r in self.waves.racks if not r.get("empty")]
            if not racks:
                return {"ok": False, "msg": "no racks in the host's session"}
            cur = self._current_rack
            if cur is None:
                target = racks[0] if nxt else racks[-1]
            else:
                later = [i for i in racks if i > cur]
                earlier = [i for i in racks if i < cur]
                target = ((later or racks)[0] if nxt else (earlier or racks)[-1])
            ok, msg = self.waves.show_rack(target)
            if ok:
                self._current_rack = target
        self._log(f"navigate {what} {'next' if nxt else 'previous'}: " + ("ok" if ok else msg))
        return {"ok": ok, "msg": msg}

    def _nav_bg(self, what, direction):
        # Off the tray thread: a missing rack makes the host answer only after ~10 s.
        runtime.spawn(self.navigate, what, direction, name="navigate")

    # ------------------------------------------------------------- names

    def pull_names(self, source="both"):
        """Read names from a device. Read only — writes nothing.

        source: "wing", "waves" or "both". Kept separate because the two are
        rarely both worth overwriting at the same moment.
        """
        out = {"names": {}, "rackNames": {}, "errors": []}

        if source in ("waves", "both") and self.waves.connected:
            for r in self.waves.racks:
                out["rackNames"][str(r["index"])] = r["name"]
        elif source in ("waves", "both"):
            out["errors"].append("the rack host is not connected")

        if source in ("wing", "both") and self.wing and self.wing.alive:
            fams = [("ch", 40), ("aux", 8), ("bus", 16), ("main", 4), ("mtx", 8)]
            for fam, cnt in fams:
                for n in range(1, cnt + 1):
                    self.wing.get(f"/{fam}/{n}/$name")
            time.sleep(1.2)                       # let the replies arrive
            for fam, cnt in fams:
                for n in range(1, cnt + 1):
                    v = self.wing.state.get(f"/{fam}/{n}/$name")
                    if isinstance(v, str) and v.strip():
                        out["names"][f"{fam}/{n}"] = v
        elif source in ("wing", "both"):
            out["errors"].append("the console is not answering")

        self._log(f"pulled names: {len(out['names'])} strips, {len(out['rackNames'])} racks")
        return out

    def push_names(self, data, target="both"):
        """Write names to a device. CHANGES the console and the host session.

        target: "wing", "waves" or "both".
        """
        names = (data or {}).get("names") or {}
        rack_names = (data or {}).get("rackNames") or {}
        done = {"wing": 0, "waves": 0, "errors": []}

        if target in ("wing", "both") and self.wing and self.wing.alive:
            # A strip set to "use source name" (in/set/srcauto) shows the name of
            # the input feeding it, and hides its own /name. Write the name where
            # the console actually takes it from, or the push changes nothing
            # visible. Verified live 2026-09-22 on ch 1 (source AES50 A 1).
            w = self.wing
            for k in names:
                fam, n = k.split("/")
                for leaf in ("in/set/srcauto", "in/conn/grp", "in/conn/in"):
                    w.raw.pop(f"/{fam}/{n}/{leaf}", None)
                    w.get(f"/{fam}/{n}/{leaf}")
            time.sleep(1.2)                       # let the replies arrive

            def first(addr):
                v = w.raw.get(addr)
                return v[0] if v else None

            for k, v in names.items():
                try:
                    fam, n = k.split("/")
                    w.send(f"/{fam}/{n}/name", [("s", v)])
                    auto = first(f"/{fam}/{n}/in/set/srcauto")
                    grp = first(f"/{fam}/{n}/in/conn/grp")
                    src = first(f"/{fam}/{n}/in/conn/in")
                    if str(auto) in ("1", "1.0", "True") and grp and str(grp) != "OFF" and src:
                        w.send(f"/io/in/{grp}/{int(float(src))}/name", [("s", v)])
                        done["sources"] = done.get("sources", 0) + 1
                    done["wing"] += 1
                except Exception as e:
                    done["errors"].append(f"{k}: {e}")
        elif names and target in ("wing", "both"):
            done["errors"].append("the console is not answering")

        if target in ("waves", "both") and self.waves.connected:
            for k, v in rack_names.items():
                ok, msg = self.waves.set_rack_name(int(k), v)
                if ok:
                    done["waves"] += 1
                else:
                    done["errors"].append(f"rack {k}: {msg}")
        elif rack_names and target in ("waves", "both"):
            done["errors"].append("the rack host is not connected")

        self._log(f"pushed names: {done['wing']} strips, {done['waves']} racks")
        return done

    # ----------------------------------------------------------- network

    def list_interfaces(self):
        """Interfaces with IPv4, to choose which one the bridge speaks over.

        Identified by name. IPs and MACs are shown for recognition only.
        """
        import psutil
        stats = psutil.net_if_stats()
        out = []
        for name, addrs in psutil.net_if_addrs().items():
            v4 = [a for a in addrs if a.family == socket.AF_INET]
            if not v4:
                continue
            a = v4[0]
            st = stats.get(name)
            out.append({
                "name": name,
                "ip": a.address,
                "netmask": a.netmask,
                "up": bool(st and st.isup),
                "loopback": a.address.startswith("127."),
                "linklocal": a.address.startswith("169.254."),
            })
        out.sort(key=lambda x: (x["loopback"], x["name"]))
        return out

    def scan_wing(self, iface=None):
        """Look for consoles on the subnet.

        Asks `/$syscfg/consolename` over UDP 2223 at every address: only the
        console answers that, and the reply carries its name.
        """
        import ipaddress

        from .wing_link import osc_build, osc_parse

        ifaces = self.list_interfaces()
        iface = iface or self.cfg.get("iface")
        chosen = next((i for i in ifaces if i["name"] == iface), None) \
            or next((i for i in ifaces if not i["loopback"] and not i["linklocal"]), None)
        if not chosen:
            return {"found": [], "error": "no interface with IPv4"}

        try:
            net = ipaddress.IPv4Network(f"{chosen['ip']}/{chosen['netmask']}", strict=False)
        except ValueError as e:
            return {"found": [], "error": str(e)}
        if net.num_addresses > 1024:
            return {"found": [], "error": f"subnet too large ({net.num_addresses} addresses)"}

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((chosen["ip"], 0))
        s.settimeout(0.25)
        probe = osc_build("/$syscfg/consolename")

        found, seen = [], set()
        self._log(f"scanning for a console on {net} via {chosen['name']}…")
        for host in net.hosts():
            try:
                s.sendto(probe, (str(host), 2223))
            except OSError:
                pass
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                data, addr = s.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                break
            if addr[0] in seen:
                continue
            a, vals = osc_parse(data)
            if a and a.startswith("/$syscfg"):
                seen.add(addr[0])
                name = next((v for v in vals if isinstance(v, str) and v.strip()), "")
                found.append({"ip": addr[0], "name": name or "console"})
        s.close()
        self._log(f"found {len(found)} console(s)")
        return {"found": found, "iface": chosen["name"], "network": str(net)}

    def get_network(self):
        return {"iface": self.cfg.get("iface", ""),
                "prolinkPort": int(self.cfg.get("prolinkPort") or 57999),
                "consoleName": self.cfg.get("consoleName") or APP_NAME}

    def set_network(self, data):
        """Apply interface / port / console name, restarting what uses them.

        Changing any of these drops a live host session for a moment. The
        console keeps its identity, so the host reconnects by itself.
        """
        data = data or {}
        before = self.get_network()
        if "iface" in data:
            self.cfg["iface"] = data["iface"] or ""
        if "prolinkPort" in data:
            try:
                port = int(data["prolinkPort"])
                if not 1024 <= port <= 65535:
                    raise ValueError
                self.cfg["prolinkPort"] = port
            except (TypeError, ValueError):
                return {"ok": False, "error": "Port must be a number from 1024 to 65535",
                        "network": before}
        if "consoleName" in data:
            self.cfg["consoleName"] = (str(data["consoleName"]).strip() or APP_NAME)[:31]
        self._save_config()

        after = self.get_network()
        if after != before:
            self._log(f"network: {after['iface'] or 'all interfaces'}, "
                      f"port {after['prolinkPort']}, as {after['consoleName']}")
            self.waves.stop()
            time.sleep(0.3)
            self.waves = self._make_waves()
            self.waves.start()
            if self.cfg.get("wingHost") and self.cfg.get("wingEnabled", True):
                self.connect_wing(self.cfg["wingHost"])
            self._push("status", self.status())
        return {"ok": True, "network": after}

    def save_diagnostics(self, out_dir=None):
        """Write one file a tester can attach to a report. Sends nothing."""
        try:
            out = diagnostics.bundle(self, out_dir)
        except Exception as e:
            return {"ok": False, "msg": f"could not write it ({e})"}
        self._log(f"diagnostics written: {out.name}")
        return {"ok": True, "path": str(out), "name": out.name}

    def open_config_folder(self):
        webbrowser.open(paths.CONFIG.parent.as_uri())
        return str(paths.CONFIG.parent)

    # ---------------------------------------------------------- sessions

    # The page calls these; the work is in sessions.py.

    def session_dirty(self):
        return self.sessions.dirty()

    def list_sessions(self):
        return self.sessions.listing()

    def save_session(self):
        return self.sessions.save()

    def save_session_as(self, name):
        return self.sessions.save_as(name)

    def new_session(self, name):
        return self.sessions.new(name)

    def load_session(self, name):
        return self.sessions.load(name)

    def rename_session(self, name, target=None):
        return self.sessions.rename(name, target)

    def delete_session(self, name):
        return self.sessions.delete(name)

    def _apply_session_buttons(self):
        """Write the session's button setup to the console, or queue it."""
        pending = self.cfg.setdefault("buttonsPending", [])
        for key in self.cfg.get("buttons", {}).values():
            if key not in pending:
                pending.append(key)
        self._save_config()
        self._apply_pending()

    # -------------------------------------------------------------- tray

    def status_lines(self):
        """Three status lines for the tray menu — the same facts as the window."""
        w = self.waves
        if w.connected:
            host = f"rack host: connected · {len(w.racks)} racks"
            h, bits = w.health, []
            if isinstance(h.get("sampleRate"), int):
                bits.append(f"{h['sampleRate'] / 1000:g} kHz")
            if isinstance(h.get("cpu"), int):
                bits.append(f"CPU {h['cpu']}%")
            if h.get("ioBox") is False:
                bits.append("I/O down")
            if h.get("sgs") is False:
                bits.append("SGS down")
            snap = h.get("snapshot")
            if isinstance(snap, int):
                bits.append("no snapshot" if snap < 0 else f"snapshot {snap + 1}")
            if h.get("sessionDirty") is True:
                bits.append("unsaved")
            detail = " · ".join(bits) or "—"
        else:
            host, detail = "rack host: waiting for Assign", "—"
        wg = self.wing
        if wg and wg.alive:
            console = f"console: answering · {self.cfg.get('wingHost', '')}"
        elif wg:
            console = f"console: no answer · {self.cfg.get('wingHost', '')}"
        else:
            console = "console: not configured"
        return [host, detail, console]

    def _refresh_tray(self):
        if self.tray:
            self.tray.refresh(self.waves.connected)

    def show_window(self):
        try:
            if self.window:
                self.window.show()
                self.window.restore()
                self.window.on_top = True      # bring it forward, then let it go
                self.window.on_top = False
        except Exception:
            pass

    def quit(self):
        """Leave now.

        Every setting is saved the moment it changes, so nothing here needs a
        graceful close — and on macOS a graceful close hangs: stopping the tray
        icon or destroying the window while the icon lives blocks ~14 s, because
        both share AppKit's run loop. The process exit removes the tray icon and
        the window, and closes every socket.
        """
        self._quitting = True
        self._closing = True
        # Straight to the file: the queue that feeds the window is not going to
        # be drained, and the last line in the log is how you tell a deliberate
        # quit from something that fell over.
        runtime.log_line("bridge stopping")
        try:
            self.waves.stop()
            if self.wing:
                self.wing.stop()
        finally:
            os._exit(0)

    # --------------------------------------------------------------- run

    def _health_loop(self):
        """Poll the host's read-only state every 2 s while a session is open."""
        while not self._closing:
            try:
                if self.waves.connected:
                    self.waves.poll_health()
            except Exception as e:
                self._log(f"health poll failed: {e}")
            time.sleep(2)

    def _on_closing(self):
        """Closing the window hides it; the bridge keeps running in the tray.

        Returning False cancels the close. Quit, from the tray, sets _quitting
        first so the same handler lets it through.
        """
        if self._quitting:
            return True
        # The hide has to happen AFTER this handler returns. pywebview runs a
        # closing handler inline on the thread that draws the window, because
        # it needs the answer — and on Windows window.hide() marshals its work
        # back onto that same thread, which is busy running this. The app
        # stopped answering and Windows recorded it as hung: AppHangB1 for
        # Kite.exe, with nothing in our own log because the freeze comes first
        # (seen 2026-09-23). macOS survives the same call only because its hide
        # is posted rather than waited on.
        runtime.spawn(self._hide_window, name="hide-window")
        self._log("window closed — the bridge is still running (tray → Open window)")
        return False

    def _hide_window(self):
        """Hide the window from a thread that is not the one drawing it."""
        time.sleep(0.05)          # let the close be cancelled first
        try:
            self.window.hide()
        except Exception:
            pass

    def run(self):
        # Imported here, not at the top: everything above this method is the
        # bridge itself, and it stays testable — and portable — without a
        # window toolkit installed.
        import webview

        self.waves.start()
        if self.cfg.get("wingHost") and self.cfg.get("wingEnabled", True):
            runtime.spawn(self.connect_wing, self.cfg["wingHost"], name="connect-console")

        listen_for_second_start(self)
        runtime.spawn(self._push_loop, name="page-events")
        runtime.spawn(self._health_loop, name="health")
        self.midi.open()
        runtime.spawn(self._user_keys_loop, name="user-keys")
        # Plain file path: a ?v= query made the web view fall back to a non-UTF-8
        # reading of the page, and the text came out mangled.
        # It opens at its minimum, which is what the header needs to keep its
        # two rows. Below that the layout would have to rearrange itself, and a
        # control that moves while the window is dragged is a control you have
        # to find again. Above it, everything keeps its place and the grid gets
        # the room.
        self.window = webview.create_window(
            f"{APP_NAME} {__version__}", str(PAGE),
            js_api=self, width=1000, height=620, min_size=(1000, 620),
        )
        self.tray = Tray(lines=self.status_lines,
                         follow=lambda: self.cfg.get("follow", True),
                         set_follow=self.set_follow,
                         on_open=self.show_window,
                         on_quit=self.quit,
                         log=self._log)
        self.tray.start()
        self.window.events.closing += self._on_closing
        self.window.events.loaded += lambda: setattr(self, "_page_ready", True)
        webview.start()          # keeps the main thread
        # Reached when the window toolkit's own loop ends, which is not the same
        # as the user quitting: on some platforms hiding the last window ends it.
        runtime.log_line("window loop ended")
        self.quit()


def already_running_show():
    """One bridge at a time.

    The first to start holds a socket on 127.0.0.1; a second start sends "show"
    to it, so a double-click just brings the window back, and exits.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.6)
        probe.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
        probe.sendall(b"show")
        return True
    except OSError:
        return False
    finally:
        probe.close()


def listen_for_second_start(app, port=SINGLE_INSTANCE_PORT):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", port))
        srv.listen(2)
    except OSError:
        return

    def loop():
        while not app._closing:
            try:
                c, _ = srv.accept()
                c.recv(16)
                c.close()
                app.show_window()
            except OSError:
                return

    runtime.spawn(loop, name="single-instance")


def main():
    runtime.setup_logging(paths.config_dir())
    if already_running_show():
        print("already running — asked the running one to show its window", flush=True)
        return 0
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
