#!/usr/bin/env python3
"""Virtual ProLink console — library.

Impersonates a console so that Waves SuperRack discovers it and connects to it.
Every byte of this protocol was verified live against SuperRack Performer
15.15.12.13 — see PROTOCOLO.md.

The four rules that are not obvious and that break everything if ignored:
  1. WE speak first: the hello goes out as soon as the connection is accepted,
     otherwise SuperRack drops it after exactly 1 s with ACK Timeout.
  2. Keepalive is re-sending the hello every ~400 ms. The type 3 frame is
     server-to-us only; sending it back kills the session.
  3. The `format` field must be 0.
  4. Socket writes must be serialised with a lock.

Also: an OSC command with no arguments drops the session — always send the
transaction id.

Scope of what this writes: display only — ShowRackByID, NavigateRack,
NavigatePlugin — plus rack names if the caller explicitly asks. It never
touches audio routing, and the mapping never reads it: a strip links to a rack,
and what is patched into that rack is none of the bridge's business, in either
direction.
"""
import random
import re
import socket
import struct
import threading
import time

MC_GRP = "ff12::7776"
MC_PORT = 40123
DEFAULT_TCP_PORT = 57999
HELLO_EVERY = 0.4
PLACEHOLDER = re.compile(r"^Rack\s+\d+$", re.I)


# ----------------------------------------------------------------- OSC

def _pad(s):
    s = s.encode() if isinstance(s, str) else s
    s += b"\x00"
    while len(s) % 4:
        s += b"\x00"
    return s


def osc_build(addr, typetags="", args=b""):
    return _pad(addr) + _pad("," + typetags) + args


def osc_decode(blob):
    """(address, typetags, [values]). Tolerant: never raises."""
    def take(b):
        s = b.split(b"\x00", 1)[0]
        return s.decode(errors="replace"), b[(len(s) // 4 + 1) * 4:]
    try:
        addr, rest = take(blob)
        if not rest:
            return addr, "", []
        tags, rest = take(rest)
        vals = []
        for t in tags[1:]:
            if t == "i":
                vals.append(struct.unpack(">i", rest[:4])[0])
                rest = rest[4:]
            elif t == "f":
                vals.append(struct.unpack(">f", rest[:4])[0])
                rest = rest[4:]
            elif t == "s":
                s, rest = take(rest)
                vals.append(s)
            elif t == "T":
                vals.append(True)
            elif t == "F":
                vals.append(False)
            elif t in "[]":
                vals.append(t)
        return addr, tags, vals
    except Exception as e:
        return "<undecodable>", "", [str(e)]


def parse_racks(vals):
    """NotifyRacksConfigChanged args -> list of dicts.

    [n, '[', idx, name, ch, ch, type, type, in, out, b, b, i, ']', ...]
    type 100 = mono, 101 = stereo; in/out of -1 = rack with no input assigned.
    """
    racks, i = [], 0
    while i < len(vals):
        if vals[i] == "[":
            j, grp = i + 1, []
            while j < len(vals) and vals[j] != "]":
                grp.append(vals[j])
                j += 1
            if len(grp) >= 8:
                racks.append({
                    "index": grp[0], "name": grp[1],
                    "stereo": grp[4] == 101,
                    "input": grp[6], "output": grp[7],
                    "assigned": grp[6] != -1,
                    # A slot SuperRack has not named itself. Deliberately NOT
                    # about the input: whether audio is patched to a rack has
                    # no bearing on a strip linking to it.
                    "empty": bool(PLACEHOLDER.match(str(grp[1]))),
                })
            i = j + 1
        else:
            i += 1
    return racks


# ----------------------------------------------------------------- console

class ProLinkConsole:
    """Virtual console. `on_event(kind, payload)` receives:

        ("status", {"connected": bool, "peer": str|None, "reason": str|None})
        ("racks",  [ {index,name,stereo,input,...}, ... ])
        ("osc",    {"addr": str, "args": [...]})
        ("log",    str)
    """

    def __init__(self, name="Midas", tcp_port=DEFAULT_TCP_PORT, on_event=None, iface=None, uid=None):
        self.name = name.encode() if isinstance(name, str) else name
        self.tcp_port = int(tcp_port)
        # Interface to answer discovery on, by NAME ("en0"), never by IP or MAC —
        # those change between networks (macOS private Wi-Fi addresses). None
        # means every interface.
        self.iface = iface or None
        self._disc_sock = None
        self._srv_sock = None
        self.on_event = on_event or (lambda k, p: None)
        # SuperRack remembers an assigned console BY THIS ID. A fresh random one
        # per launch made every restart look like a new, unknown console, so the
        # assignment had to be cleared and redone each time. Callers should pass
        # a persisted id; a random one is only the fallback.
        self.uid = uid if (isinstance(uid, bytes) and len(uid) == 16) \
            else bytes(random.randint(0, 255) for _ in range(16))

        self._sock = None          # active TCP session
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._session_stop = None
        self._txn = 1000
        self._pending = {}         # txn -> (Event, [result])
        self.racks = []
        self.connected = False
        self.peer = None
        self.health = {}

    # -- lifecycle -------------------------------------------------------

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._discovery_loop, daemon=True).start()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self._log(f"listening on [::]:{self.tcp_port} as {self.name.decode()}")

    def stop(self):
        self._stop.set()
        if self._session_stop:
            self._session_stop.set()
        # Close the listening sockets now, so a restart can bind the same ports
        # straight away instead of waiting for the loops to time out.
        for sk in (self._disc_sock, self._srv_sock):
            try:
                if sk:
                    sk.close()
            except Exception:
                pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def _log(self, msg):
        self.on_event("log", msg)

    def _status(self, connected, reason=None):
        self.connected = connected
        if not connected:
            self.peer = None
        self.on_event("status", {"connected": connected, "peer": self.peer, "reason": reason})

    # -- frames ----------------------------------------------------------

    def _frame(self, typ, body=b""):
        return struct.pack(">I", 1) + b"Wave" + struct.pack(">I", typ) + body

    def _hello(self):
        body = struct.pack(">I", 500)      # keepalive ms
        body += struct.pack(">I", 0)       # format: MUST be 0
        body += struct.pack(">H", 1) + struct.pack(">H", 0)
        body += self.uid
        body += struct.pack(">I", len(self.name)) + self.name
        return self._frame(1, body)

    def _disc_reply(self):
        h = struct.pack(">I", 1) + b"Wave" + struct.pack(">I", 2)
        h += struct.pack(">I", 0)
        h += struct.pack(">H", 1) + struct.pack(">H", 0) + struct.pack(">H", 0)
        h += b"\x00" * 16
        h += struct.pack(">H", self.tcp_port)      # != 0
        h += struct.pack(">I", 0)
        h += self.uid
        h += struct.pack(">I", len(self.name))
        return h + self.name

    def _send(self, data):
        if not self._sock:
            raise ConnectionError("no session with SuperRack")
        with self._send_lock:
            self._sock.sendall(data)

    # -- discovery -------------------------------------------------------

    def _discovery_loop(self):
        """Answers the multicast probes.

        Joins the group on ALL interfaces: names differ between macOS (en0) and
        Windows, so this needs no configuration.
        """
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass                              # Windows has no SO_REUSEPORT
        try:
            s.bind(("::", MC_PORT))
        except OSError as e:
            self._log(f"could not open discovery port {MC_PORT}: {e}")
            return

        self._disc_sock = s
        joined = 0
        wanted = [(socket.if_nametoindex(self.iface), self.iface)] if self.iface else socket.if_nameindex()
        for idx, _name in wanted:
            try:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP,
                             socket.inet_pton(socket.AF_INET6, MC_GRP) + struct.pack("@I", idx))
                joined += 1
            except OSError:
                pass                          # interface without IPv6 or multicast
        self._log(f"discovery active on {self.iface or 'all interfaces'} ({joined} joined)")

        s.settimeout(1)
        reply = self._disc_reply()
        while not self._stop.is_set():
            try:
                _, addr = s.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                s.sendto(reply, addr)
            except OSError:
                pass

    # -- session ---------------------------------------------------------

    def _accept_loop(self):
        srv = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv_sock = srv
        try:
            srv.bind(("::", self.tcp_port))
        except OSError as e:
            self._log(f"port {self.tcp_port} already in use: {e}")
            return
        srv.listen(5)
        srv.settimeout(1)
        while not self._stop.is_set():
            try:
                c, a = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._session, args=(c, a), daemon=True).start()
        try:
            srv.close()
        except Exception:
            pass

    def _session(self, c, addr):
        if self._sock:                        # a session exists; refuse the new one
            try:
                c.close()
            except Exception:
                pass
            return

        self._sock = c
        self._session_stop = stop = threading.Event()
        self.peer = f"{addr[0]}:{addr[1]}"
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        c.settimeout(0.05)

        try:
            self._send(self._hello())          # always speak first
        except Exception as e:
            self._log(f"hello failed: {e}")
            self._end_session(stop)
            return
        self._status(True)

        def keepalive():
            time.sleep(HELLO_EVERY)
            while not stop.is_set():
                try:
                    self._send(self._hello())
                except Exception:
                    return
                time.sleep(HELLO_EVERY)
        threading.Thread(target=keepalive, daemon=True).start()

        buf = b""
        try:
            while not stop.is_set() and not self._stop.is_set():
                try:
                    d = c.recv(65536)
                except TimeoutError:
                    continue
                except OSError:
                    break
                if not d:
                    break
                buf += d
                events, buf = self._parse(buf)
                for kind, payload in events:
                    self._dispatch(kind, payload)
        finally:
            self._end_session(stop)

    def _end_session(self, stop):
        stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        for ev, _box in self._pending.values():
            ev.set()
        self._pending.clear()
        self._status(False)

    def _parse(self, buf):
        """Frames: magic(1) + "Wave" + type + body."""
        i, out = 0, []
        while True:
            if len(buf) - i < 12:
                break
            if buf[i + 4:i + 8] != b"Wave":
                out.append(("desync", buf[i:i + 48]))
                return out, b""
            typ = struct.unpack(">I", buf[i + 8:i + 12])[0]
            if typ == 1:
                if len(buf) - i < 44:
                    break
                dlen = struct.unpack(">I", buf[i + 40:i + 44])[0]
                if len(buf) - i < 44 + dlen:
                    break
                i += 44 + dlen
            elif typ == 3:
                if len(buf) - i < 16:
                    break
                i += 16
            elif typ in (2, 4, 5):
                if len(buf) - i < 16:
                    break
                ln = struct.unpack(">I", buf[i + 12:i + 16])[0]
                if len(buf) - i < 16 + ln:
                    break
                if typ == 5:
                    out.append(("osc", buf[i + 16:i + 16 + ln]))
                i += 16 + ln
            else:
                out.append(("unknown", buf[i:i + 48]))
                return out, b""
        return out, buf[i:]

    def _dispatch(self, kind, payload):
        if kind != "osc":
            return
        addr, tags, vals = osc_decode(payload)
        short = addr.rsplit("/", 1)[-1]

        # Health notifications SuperRack sends on its own (all read only).
        # Shapes captured live 2026-09-22: SyncStatus [44100], IOBoxStatus [True],
        # SGSStatus [True], SnapshotDirty [False]. AudioStatus / SessionDirty
        # have not been seen yet, so their raw first argument is kept as is.
        field = {"NotifySyncStatus": "sampleRate", "NotifyIOBoxStatus": "ioBox",
                 "NotifySGSStatus": "sgs", "NotifyAudioStatus": "audio",
                 "NotifySnapshotDirty": "snapshotDirty",
                 "NotifySessionDirty": "sessionDirty"}.get(short)
        if field:
            self.health[field] = vals[0] if vals else None
            self.on_event("health", dict(self.health))
            return

        if short == "NotifyRacksConfigChanged":
            self.racks = parse_racks(vals)
            self.on_event("racks", self.racks)
            return

        if short == "NotifySingleRackConfigChanged":
            # Sent when one rack changes — assigning an input, for instance.
            # Its payload has never been captured, so the shape below is a
            # guess: try the same [...] grouping and merge by index. If that
            # yields nothing, log the raw args (so the format gets learnt the
            # first time it happens) and re-read every rack instead.
            one = parse_racks(vals)
            if one:
                by_index = {r["index"]: r for r in self.racks}
                for r in one:
                    by_index[r["index"]] = r
                self.racks = [by_index[i] for i in sorted(by_index)]
                self.on_event("racks", self.racks)
            else:
                self._log(f"NotifySingleRackConfigChanged in an unknown shape, "
                          f"re-reading the inventory. args={vals!r}")
                threading.Thread(target=self.refresh_racks, daemon=True).start()
            return

        # replies to our requests: the first int is the transaction id
        if vals and isinstance(vals[0], int) and vals[0] in self._pending:
            ev, box = self._pending.pop(vals[0])
            box.append((addr, vals))
            ev.set()
            return

        self.on_event("osc", {"addr": addr, "args": vals})

    # -- commands --------------------------------------------------------

    def _next_txn(self):
        self._txn += 1
        return self._txn

    def _request(self, addr, typetags, args, timeout=2.0):
        """Send and wait for the reply carrying the same id. (addr, vals) or None."""
        if not self._sock:
            return None                    # no session: a normal state, not an error
        txn = self._next_txn()
        ev, box = threading.Event(), []
        self._pending[txn] = (ev, box)
        payload = struct.pack(">i", txn) + args
        msg = osc_build(addr, typetags, payload)
        try:
            self._send(self._frame(5, struct.pack(">I", len(msg)) + msg))
        except Exception as e:
            self._pending.pop(txn, None)
            self._log(f"send failed: {e}")
            return None
        if not ev.wait(timeout):
            self._pending.pop(txn, None)
            return None
        return box[0] if box else None

    @staticmethod
    def _ok(reply):
        """ResultCommand: (id, code, message). Code 0 = success."""
        if not reply:
            return False, "no reply — is SuperRack connected?"
        addr, vals = reply
        if addr.endswith("ResultCommand"):
            code = vals[1] if len(vals) > 1 else -1
            return code == 0, (vals[2] if len(vals) > 2 else "")
        return True, ""

    def show_rack(self, index):
        """Open a rack BY RACK INDEX.

        Careful: ShowRack takes the INPUT index, not the rack index — VOX is
        rack 22 but sits on input 30. Mapping from an inventory is always
        ShowRackByID.
        """
        return self._ok(self._request("/waves.com/remote/ShowRackByID", "ii",
                                      struct.pack(">i", int(index))))

    def navigate_rack(self, direction):
        """0 or 1. Needs a rack already open, otherwise it times out."""
        return self._ok(self._request("/waves.com/remote/NavigateRack", "ii",
                                      struct.pack(">i", 1 if direction else 0)))

    def navigate_plugin(self, direction):
        return self._ok(self._request("/waves.com/remote/NavigatePlugin", "ii",
                                      struct.pack(">i", 1 if direction else 0)))

    def refresh_racks(self):
        """Re-read every rack with GetRacksInfo(id, index).

        There is no "give me all racks" request — GetRacksInfo answers for one
        index at a time — so this walks them. Used as the fallback when a
        single-rack notification cannot be parsed.
        """
        total = self.num_racks() or len(self.racks)
        if not total:
            return
        fresh = []
        for i in range(total):
            r = self._request("/waves.com/remote/GetRacksInfo", "ii", struct.pack(">i", i))
            if not r:
                continue
            got = parse_racks(r[1])
            if got:
                fresh.append(got[0])
        if fresh:
            self.racks = fresh
            self.on_event("racks", self.racks)
            self._log(f"inventory re-read: {len(fresh)} racks")

    def poll_health(self):
        """Read-only state SuperRack does not push: CPU, unsaved changes, snapshot.

        Reply shapes verified live 2026-09-22: GiveCPUUsage [id, 10] (percent),
        GiveSessionDirtyState [id, True], GiveCurrentSnapshotNumber [id, -1]
        (-1 = none recalled).
        """
        for cmd, field in (("GetCPUUsage", "cpu"),
                           ("GetSessionDirtyState", "sessionDirty"),
                           ("GetCurrentSnapshotNumber", "snapshot")):
            r = self._request(f"/waves.com/remote/{cmd}", "i", b"")
            if r and len(r[1]) > 1 and not r[0].endswith("ResultCommand"):
                self.health[field] = r[1][1]
        self.on_event("health", dict(self.health))
        return dict(self.health)

    def num_racks(self):
        r = self._request("/waves.com/remote/GetNumRacks", "i", b"")
        return r[1][1] if r and len(r[1]) > 1 else None

    def rack_name(self, index):
        r = self._request("/waves.com/remote/GetRackName", "ii", struct.pack(">i", int(index)))
        return r[1][1] if r and len(r[1]) > 1 else None

    def set_rack_name(self, index, name):
        """NOT VERIFIED — changes the SuperRack session. Signature is a guess."""
        return self._ok(self._request("/waves.com/remote/SetRackName", "iis",
                                      struct.pack(">i", int(index)) + _pad(str(name))))
