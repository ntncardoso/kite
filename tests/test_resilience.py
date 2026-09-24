"""Two ways the app used to make a bad moment worse."""

import time

from kite.midi_link import MidiLink
from kite.wing_link import WingLink


def test_a_midi_client_is_tried_in_a_child_first(monkeypatch):
    """rtmidi's CoreMIDI failure aborts the process before Python sees it, so
    the attempt happens somewhere that can afford to die."""
    ran = {}

    class Result:
        returncode = 1

    def fake_run(cmd, **kw):
        ran["cmd"] = cmd
        ran["env"] = kw.get("env", {})
        return Result()

    monkeypatch.setattr("kite.midi_link.subprocess.run", fake_run)
    link = MidiLink(log=lambda m: None)
    assert link.open() is False
    assert "not available" in link.error
    assert ran["env"][MidiLink.PROBE_ENV] == "1"


def test_a_probe_that_cannot_run_does_not_block_midi(monkeypatch):
    def refuse(cmd, **kw):
        raise OSError("no such thing")

    monkeypatch.setattr("kite.midi_link.subprocess.run", refuse)
    assert MidiLink.probe() is True, "an unusable probe must not veto MIDI"


def test_an_unreachable_console_is_reported_once_a_minute():
    """Selection is polled three times a second; a desk switched off used to
    write three identical lines a second until the log rotated away."""
    said = []
    w = WingLink("192.0.2.1", log=said.append)
    w.sock = type("Dead", (), {"sendto": lambda *a: (_ for _ in ()).throw(OSError("down"))})()

    for _ in range(300):
        w.send("/$ctl/$stat/selidx")
    assert len(said) == 1, said

    w._gripes["OSError"] = (time.time() - 61, 299)
    w.send("/$ctl/$stat/selidx")
    assert len(said) == 2
    assert "300 times in the last minute" in said[1]
