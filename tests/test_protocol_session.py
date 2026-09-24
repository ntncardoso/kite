"""A whole session over a real socket, against a stand-in for the rack host.

The unit tests cover the framing and the parsing; this one covers the thing
they cannot: that the endpoint accepts a connection, speaks first, is
understood, and that a command sent from here comes back answered. It is the
part of the product that only ever ran against one machine on one operating
system, so it runs on every platform the app ships to.

Nothing real is contacted: the stand-in is a socket in this process.
"""

import socket
import struct
import threading
import time

import pytest

from kite.prolink import ProLinkConsole, osc_build, osc_decode

MAGIC = struct.pack(">I", 1) + b"Wave"
HEADER = 16                         # magic, tag, type, length


def free_port():
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.bind(("::", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def osc_frame(addr, typetags="", args=b""):
    msg = osc_build(addr, typetags, args)
    return MAGIC + struct.pack(">I", 5) + struct.pack(">I", len(msg)) + msg


def rack_args(racks):
    """The argument list NotifyRacksConfigChanged carries, as the host sends it."""
    vals = [len(racks)]
    for index, name in racks:
        vals += ["[", index, name, 1, 1, 100, 100, index, index, 0, 0, 0, "]"]
    tags, args = "", b""
    for v in vals:
        if isinstance(v, int):
            tags += "i"
            args += struct.pack(">i", v)
        else:
            tags += "s"
            args += v.encode() + b"\0" * (4 - len(v) % 4)
    return tags, args


class FakeHost:
    """A rack host, as far as the endpoint can tell: connects, then talks OSC."""

    def __init__(self, port):
        # The endpoint binds its socket on a thread of its own, so a connection
        # attempted in the same breath as start() can be refused before it is
        # listening. Keep knocking rather than failing a test over a race that
        # no rack host would ever lose (a CI runner did, 2026-09-24).
        deadline = time.time() + 10
        last = None
        while time.time() < deadline:
            for host in ("::1", "127.0.0.1"):
                try:
                    self.sock = socket.create_connection((host, port), timeout=5)
                    self.sock.settimeout(5)
                    self.buf = b""
                    return
                except OSError as e:
                    last = e
            time.sleep(0.05)
        raise AssertionError(f"the endpoint never started listening on {port}: {last}")

    def read_frame(self):
        """The next whole frame, as (type, body).

        Two shapes on this wire: the hello (type 1), whose body ends in a name
        of its own length, and an OSC frame (type 5), whose length is declared.
        Anything else would be a frame this test does not know about.
        """
        while True:
            size = self._frame_size()
            if size:
                frame, self.buf = self.buf[:size], self.buf[size:]
                typ = struct.unpack(">I", frame[8:12])[0]
                # An OSC frame declares its length in the four bytes after the
                # type; the message itself starts past them.
                return typ, frame[HEADER:] if typ == 5 else frame[12:]
            chunk = self.sock.recv(65536)
            if not chunk:
                raise AssertionError("the endpoint closed the connection")
            self.buf += chunk

    def _frame_size(self):
        """How long the frame at the front is, or 0 while it is incomplete."""
        if len(self.buf) < 12:
            return 0
        assert self.buf[:8] == MAGIC, "frame does not start with the magic"
        typ = struct.unpack(">I", self.buf[8:12])[0]
        if typ == 5:
            if len(self.buf) < HEADER:
                return 0
            ln = struct.unpack(">I", self.buf[12:16])[0]
            return HEADER + ln if len(self.buf) >= HEADER + ln else 0
        if typ == 1:
            # keepalive ms, format, two shorts, the 16-byte id, then the name
            fixed = 12 + 4 + 4 + 2 + 2 + 16
            if len(self.buf) < fixed + 4:
                return 0
            name_len = struct.unpack(">I", self.buf[fixed:fixed + 4])[0]
            end = fixed + 4 + name_len
            return end if len(self.buf) >= end else 0
        raise AssertionError(f"unexpected frame type {typ}")

    def read_command(self):
        """Skip keepalives; return the next command as (address, values)."""
        for _ in range(50):
            typ, payload = self.read_frame()
            if typ == 5:
                addr, _tags, vals = osc_decode(payload)
                return addr, vals
        raise AssertionError("no command arrived")

    def send(self, addr, typetags="", args=b""):
        self.sock.sendall(osc_frame(addr, typetags, args))

    def close(self):
        self.sock.close()


@pytest.fixture
def session():
    events = []
    console = ProLinkConsole(name="Kite test", uid=bytes(range(16)),
                             tcp_port=free_port(), iface=None,
                             on_event=lambda kind, payload: events.append((kind, payload)))
    console.events = events
    console.start()
    host = FakeHost(console.tcp_port)
    yield console, host
    host.close()
    console.stop()


def test_the_endpoint_speaks_first(session):
    """The host connects and says nothing; anything that waits is dropped in a
    second. The hello has to be on the wire straight away."""
    console, host = session
    typ, body = host.read_frame()
    assert typ == 1, "the first frame must be the hello"
    assert struct.unpack(">I", body[4:8])[0] == 0, "format must be 0 or the host refuses it"
    assert bytes(range(16)) in body, "the hello carries the console identity"
    assert body.endswith(b"Kite test"), "and the name the host will show"


def test_the_connection_is_reported_as_a_session(session):
    console, host = session
    host.read_frame()
    for _ in range(50):
        if console.connected:
            break
        threading.Event().wait(0.02)
    assert console.connected is True
    assert any(kind == "status" and payload["connected"] for kind, payload in console.events)


def test_an_inventory_arrives_and_is_understood(session):
    console, host = session
    host.read_frame()
    tags, args = rack_args([(0, "KICK"), (1, "SNARE"), (2, "VOX")])
    host.send("/waves.com/remote/NotifyRacksConfigChanged", tags, args)
    for _ in range(100):
        if len(console.racks) == 3:
            break
        threading.Event().wait(0.02)
    assert [r["name"] for r in console.racks] == ["KICK", "SNARE", "VOX"]


def test_a_rack_is_opened_by_rack_index_and_the_answer_is_read(session):
    """The command this whole application exists to send."""
    console, host = session
    host.read_frame()
    out = {}
    caller = threading.Thread(target=lambda: out.update(zip(("ok", "msg"), console.show_rack(7), strict=True)))
    caller.start()

    addr, vals = host.read_command()
    assert addr.endswith("ShowRackByID"), "mapping must never go through ShowRack"
    txn, index = vals[0], vals[1]
    assert index == 7

    host.send("/waves.com/remote/ResultCommand", "iis",
              struct.pack(">i", txn) + struct.pack(">i", 0) + b"\0\0\0\0")
    caller.join(timeout=5)
    assert out["ok"] is True


def test_a_refused_command_is_reported_rather_than_swallowed(session):
    console, host = session
    host.read_frame()
    out = {}
    caller = threading.Thread(target=lambda: out.update(zip(("ok", "msg"), console.show_rack(99), strict=True)))
    caller.start()

    _addr, vals = host.read_command()
    host.send("/waves.com/remote/ResultCommand", "iis",
              struct.pack(">i", vals[0]) + struct.pack(">i", 1) + b"no such rack\0\0\0\0")
    caller.join(timeout=5)
    assert out["ok"] is False
    assert "no such rack" in out["msg"]


def test_health_notifications_are_collected(session):
    console, host = session
    host.read_frame()
    host.send("/waves.com/remote/NotifySyncStatus", "i", struct.pack(">i", 48000))
    for _ in range(100):
        if console.health.get("sampleRate") == 48000:
            break
        threading.Event().wait(0.02)
    assert console.health["sampleRate"] == 48000
