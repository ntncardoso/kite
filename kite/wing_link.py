#!/usr/bin/env python3
"""OSC client for the Behringer WING.

Conventions taken from the `wing-full` Companion module (itself verified against
"WING Remote Protocols V3.1.0", FW 3.1) — see PROTOCOLO.md section 5:

  * OSC over UDP (or TCP) on port 2223.
  * `/*S` turns on event push; the WING drops idle remotes after ~10 s, so it is
    renewed every 7 s.
  * Querying a value = send the address with NO arguments.
  * Replies come multi-tag (e.g. `fdr` -> ,sff ["-oo", 0.0, -144.0]); the value
    we want is the LAST numeric argument.
  * `/$ctl/$stat/...` never pushes — it has to be polled (300 ms).

Verified live on 2026-09-22 against a WING over Wi-Fi: selecting a strip on the
console opens the mapped rack in SuperRack, end to end.
"""
import socket
import struct
import threading
import time

WING_OSC_PORT = 2223
SELIDX = "/$ctl/$stat/selidx"

# selidx is 0-based and contiguous across families (doc, footnote 54).
SELIDX_RANGES = [
    ("ch",   0,  40),
    ("aux",  40, 8),
    ("bus",  48, 16),
    ("main", 64, 4),
    ("mtx",  68, 8),
]


def osc_pad(s):
    s = s.encode() if isinstance(s, str) else s
    s += b"\x00"
    while len(s) % 4:
        s += b"\x00"
    return s


def osc_build(addr, args=()):
    """args: list of (tag, value). No args = query (GET)."""
    tags = "," + "".join(t for t, _ in args)
    payload = b""
    for t, v in args:
        if t == "i":
            payload += struct.pack(">i", int(v))
        elif t == "f":
            payload += struct.pack(">f", float(v))
        elif t == "s":
            payload += osc_pad(str(v))
    return osc_pad(addr) + osc_pad(tags) + payload


def osc_parse(data):
    """Returns (address, [values]), or (None, []) if it will not decode."""
    try:
        addr = data.split(b"\x00", 1)[0].decode()
        rest = data[(len(addr) // 4 + 1) * 4:]
        tags = rest.split(b"\x00", 1)[0].decode()
        rest = rest[(len(tags) // 4 + 1) * 4:]
        vals = []
        for t in tags[1:]:
            if t == "i":
                vals.append(struct.unpack(">i", rest[:4])[0])
                rest = rest[4:]
            elif t == "f":
                vals.append(struct.unpack(">f", rest[:4])[0])
                rest = rest[4:]
            elif t == "s":
                s = rest.split(b"\x00", 1)[0].decode(errors="replace")
                vals.append(s)
                rest = rest[(len(s) // 4 + 1) * 4:]
        return addr, vals
    except Exception:
        return None, []


def last_numeric(vals):
    """The WING replies multi-tag; the value we want is the last numeric one."""
    for v in reversed(vals):
        if isinstance(v, (int, float)):
            return v
    return vals[0] if vals else None


def selidx_to_strip(idx0):
    """0-based selidx -> ('ch', 5) 1-based, or None."""
    if idx0 is None:
        return None
    for fam, base, count in SELIDX_RANGES:
        if base <= idx0 < base + count:
            return fam, idx0 - base + 1
    return None


class WingLink:
    """WING OSC client.

    On being "connected": the transport is UDP, which has no connection. Opening
    the socket never fails, not even against an address with no console on it —
    so the only proof of life is the WING **answering**. We poll selidx every
    300 ms; `alive` is true while a recent reply has been seen.
    """

    ALIVE_WINDOW = 2.5     # seconds without a reply before calling it dead

    def __init__(self, host, port=WING_OSC_PORT, log=print, bind_ip=None):
        self.host, self.port, self.log = host, port, log
        self.bind_ip = bind_ip or "0.0.0.0"     # the chosen interface, if any
        self.sock = None
        self.raw = {}
        self.state = {}
        self.on_selection = None       # callback(fam, n, name)
        self.on_alive_change = None    # callback(bool)
        self.on_button = None          # callback(key) on press, key like "U2/1/bu"
        self.last_rx = 0.0
        self._alive = False
        self._last_selidx = None
        self._gripes = {}
        self._stop = threading.Event()

    @property
    def alive(self):
        return bool(self.sock) and (time.time() - self.last_rx) < self.ALIVE_WINDOW

    def _check_alive(self):
        now = self.alive
        if now != self._alive:
            self._alive = now
            self.log("answering" if now else "no answer")
            if self.on_alive_change:
                self.on_alive_change(now)

    # -- transport -------------------------------------------------------

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.2)
        self.sock.bind((self.bind_ip, 0))
        self.send("/*S")                      # turn on event push
        threading.Thread(target=self._rx_loop, daemon=True).start()
        threading.Thread(target=self._keepalive_loop, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.log(f"probing {self.host}:{self.port} (UDP) — waiting for a reply")

    def stop(self):
        self._stop.set()
        self.last_rx = 0.0
        self._check_alive()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    # Selection is polled three times a second, so a console that is switched
    # off writes three identical failures a second for as long as it is off —
    # a log that rotates away the very history it was kept for (seen when a
    # desk was powered down mid-session, 2026-09-24). The same complaint is
    # made once a minute, and says how many times it happened.
    _gripe_every = 60

    def _gripe(self, kind, detail):
        now = time.time()
        first, count = self._gripes.get(kind, (0.0, 0))
        if now - first < self._gripe_every:
            self._gripes[kind] = (first, count + 1)
            return
        self._gripes[kind] = (now, 0)
        again = f" ({count + 1} times in the last minute)" if count else ""
        self.log(f"{detail}{again}")

    def send(self, addr, args=()):
        if not self.sock:
            return
        try:
            self.sock.sendto(osc_build(addr, args), (self.host, self.port))
        except Exception as e:
            self._gripe(type(e).__name__, f"WING: cannot reach {self.host}: {e}")

    def get(self, addr):
        """Query: the reply arrives asynchronously in _rx_loop."""
        self.send(addr)

    # -- loops -----------------------------------------------------------

    def _keepalive_loop(self):
        # The WING drops idle remotes after ~10 s.
        while not self._stop.is_set():
            time.sleep(7)
            self.send("/*S")

    def _poll_loop(self):
        # /$ctl/$stat/... never pushes.
        while not self._stop.is_set():
            self.get(SELIDX)
            time.sleep(0.3)
            self._check_alive()

    def _rx_loop(self):
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except TimeoutError:
                continue
            except Exception:
                return
            self.last_rx = time.time()
            self._check_alive()
            addr, vals = osc_parse(data)
            if not addr:
                continue
            val = last_numeric(vals)
            self.state[addr] = val
            self.raw[addr] = vals          # every argument, for multi-tag replies
            # USER buttons: the console pushes /$ctl/user/<layer>/<n>/<bu|bd>/val,
            # 127 on press and 0 on release (verified live 2026-09-22 with a
            # button in MIDICCP mode). Only presses count.
            if addr.startswith("/$ctl/user/") and addr.endswith("/val"):
                parts = addr.split("/")        # ['', '$ctl', 'user', L, n, row, 'val']
                if len(parts) == 7 and parts[5] in ("bu", "bd") and self.on_button \
                        and isinstance(val, (int, float)) and val > 0:
                    try:
                        self.on_button("/".join(parts[3:6]))
                    except Exception as e:
                        self.log(f"button handler failed: {e}")
                continue
            if addr == SELIDX:
                # A callback blowing up must not take this thread down with it,
                # or the bridge stops following the console without saying so.
                try:
                    self._handle_selidx(val)
                except Exception as e:
                    self.log(f"selection handler failed: {e}")

    def _handle_selidx(self, idx0):
        if idx0 == self._last_selidx:
            return
        self._last_selidx = idx0
        strip = selidx_to_strip(int(idx0) if idx0 is not None else None)
        if not strip:
            return
        fam, n = strip
        name = self.state.get(f"/{fam}/{n}/$name")
        self.get(f"/{fam}/{n}/$name")         # refresh for next time
        if self.on_selection:
            self.on_selection(fam, n, name)
