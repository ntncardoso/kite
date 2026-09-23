"""USER KEYS are fired over MIDI: one CC per key, channel 16."""

from kite import midi_link


class FakeOut:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg)


def test_one_message_per_press():
    # 127 then 0 counted as two presses in SuperRack, and a toggle such as Lock
    # undid itself. One message per press is the whole point.
    link = midi_link.MidiLink()
    link.out = FakeOut()
    assert link.press(3) is True
    assert link.out.sent == [[0xB0 | (midi_link.CHANNEL - 1), 3, 127]]


def test_key_number_is_the_cc_number():
    link = midi_link.MidiLink()
    link.out = FakeOut()
    for n in (1, 16):
        link.press(n)
    assert [m[1] for m in link.out.sent] == [1, 16]


def test_press_without_a_port_is_harmless():
    assert midi_link.MidiLink().press(1) is False
