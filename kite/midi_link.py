"""A MIDI output the bridge owns, for SuperRack's USER KEYS.

SuperRack's "MIDI Controller" surface can MIDI-learn each USER KEY (Note On
or Control Change — strings in PhMIDI_Control.bundle: "User Key #", "Learnt").
ProLink has no command for USER KEYS, so the bridge fires them over MIDI:
USER KEY n is CC n on channel 16, value 127 — one message per press.

Port. The bridge first looks for an EXISTING port with "WING Bridge" in its
name and uses it. That port belongs to the system, so it survives the bridge
restarting, and SuperRack stays connected to it:
  - macOS: an IAC Driver bus named "WING Bridge" (Audio MIDI Setup, once);
  - Windows: a loopMIDI port named "WING Bridge".
Only if there is none, on macOS, does the bridge make a virtual port of that
name. A virtual port dies with the bridge, and SuperRack does not pick up the
new one by itself: after every restart it must be reselected in SuperRack
(seen 2026-09-22). So the virtual port is a fallback, reported as such.
"""

import os
import subprocess
import sys

CHANNEL = 16                 # 1-16; kept away from channel 1, which most gear uses


class MidiLink:
    def __init__(self, name="WING Bridge", log=print):
        self.name = name
        self.log = log
        self.out = None
        self.error = None
        self.persistent = False
        self.port = None

    # Creating the MIDI client is the one call here that can take the whole
    # application with it. On macOS, rtmidi's CoreMIDI client creation throws a
    # C++ exception that escapes as an unexpected-handler call: the process
    # aborts before Python sees anything to catch. Seen on 2026-09-24, starting
    # a new copy two seconds after killing the old one — the dying instance
    # still held the client.
    #
    # So it is tried in a child first. A child that dies takes nothing with it,
    # and the bridge carries on without MIDI, saying so.
    PROBE_ENV = "KITE_MIDI_PROBE"
    PROBE_TIMEOUT = 15

    @classmethod
    def probe(cls):
        """Can a MIDI client be created on this machine right now?"""
        env = dict(os.environ, **{cls.PROBE_ENV: "1"})
        cmd = ([sys.executable] if getattr(sys, "frozen", False)
               else [sys.executable, "-c", "import rtmidi; rtmidi.MidiOut()"])
        try:
            r = subprocess.run(cmd, env=env, timeout=cls.PROBE_TIMEOUT,
                               capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return True          # cannot check: do not stand in the way
        return r.returncode == 0

    def open(self):
        try:
            import rtmidi
        except Exception as e:
            self.error = f"MIDI unavailable ({e})"
            return False
        if not self.probe():
            self.error = ("MIDI is not available on this machine at the moment — "
                          "the system refused a MIDI client. The bridge works "
                          "without it; USER KEYS will not.")
            self.log(self.error)
            return False
        try:
            out = rtmidi.MidiOut()
            ports = out.get_ports()
            idx = next((i for i, p in enumerate(ports) if self.name.lower() in p.lower()), None)
            if idx is not None:
                out.open_port(idx)
                self.persistent = True
                self.port = ports[idx]
                self.error = None
                self.log(f'MIDI port "{ports[idx]}" open')
            elif sys.platform == "darwin" or sys.platform.startswith("linux"):
                out.open_virtual_port(self.name)
                self.persistent = False
                self.port = self.name
                self.error = (f'Using a temporary MIDI port. It is replaced every time the app '
                              f'restarts, and SuperRack must then be pointed at it again. For a '
                              f'port that stays, create an IAC Driver bus named "{self.name}" in '
                              f'Audio MIDI Setup and restart the app.')
                self.log(self.error)
            else:
                self.error = (f'no MIDI port named "{self.name}" — create one '
                              f'with loopMIDI and restart the app')
                self.log(self.error)      # and in the log, not only on screen
                return False
            self.out = out
            return True
        except Exception as e:
            self.error = f"MIDI port failed ({e})"
            return False

    def press(self, cc):
        """One press on CC `cc`: a single message, value 127.

        No release message: SuperRack counts every CC it has learnt as a press,
        whatever the value, so 127-then-0 fired each USER KEY twice — and a
        toggle such as Lock undid itself (seen in its log, 2026-09-22).
        """
        if not self.out:
            return False
        self.out.send_message([0xB0 | (CHANNEL - 1), cc & 0x7F, 127])
        return True

    def close(self):
        try:
            if self.out:
                self.out.close_port()
        except Exception:
            pass
        self.out = None
