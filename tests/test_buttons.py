"""WING USER buttons: what they fire, and what happens with the console away."""


def test_a_press_fires_the_action_bound_to_that_button(bridge):
    fired = []
    bridge._nav_bg = lambda what, d: fired.append((what, d))
    bridge.midi.press = lambda cc: fired.append(("midi", cc)) or True
    bridge.midi.out = True
    bridge.cfg["buttons"] = {"uk3": "U1/2/bu", "plugin-next": "U1/1/bu"}

    bridge._on_wing_button("U1/2/bu")
    bridge._on_wing_button("U1/1/bu")
    bridge._on_wing_button("U4/4/bu")            # bound to nothing
    assert fired == [("midi", 3), ("plugin", 1)]


def test_offline_choices_are_queued_for_the_console(bridge):
    r = bridge.assign_button("uk1", "U1/1/bu")   # no WING in this fixture
    assert r["ok"] and r["pending"] is True
    assert bridge.cfg["buttons"] == {"uk1": "U1/1/bu"}
    assert bridge.cfg["buttonsPending"] == ["U1/1/bu"]


def test_taking_the_choice_back_clears_the_queue(bridge):
    bridge.assign_button("uk1", "U1/1/bu")
    assert bridge.release_button("uk1")["ok"] is True
    assert bridge.cfg["buttons"] == {}
    assert bridge.cfg["buttonsPending"] == []


def test_a_button_set_up_on_the_console_is_put_back_when_freed(bridge):
    bridge.cfg["buttons"] = {"uk1": "U1/1/bu"}
    bridge.cfg["buttonsOwned"] = ["U1/1/bu"]
    bridge.release_button("uk1")
    assert bridge.cfg["buttonsToFree"] == ["U1/1/bu"]   # done when it answers again
    assert bridge.cfg["buttonsOwned"] == []


def test_one_button_carries_one_action(bridge):
    bridge.assign_button("uk1", "U1/1/bu")
    bridge.assign_button("uk2", "U1/1/bu")
    assert bridge.cfg["buttons"] == {"uk2": "U1/1/bu"}


def test_unknown_actions_are_refused(bridge):
    assert bridge.assign_button("uk17", "U1/1/bu")["ok"] is False
    assert bridge.assign_button("nonsense", "U1/1/bu")["ok"] is False


class FakeWing:
    """A console that answers, and records what was written to it."""

    def __init__(self, mode="OFF", name=""):
        self.alive = True
        self.sent = []
        self.raw = {}
        self._mode, self._name = mode, name

    def send(self, addr, args):
        self.sent.append((addr, args[0][1]))
        if addr.endswith("/name"):
            self._name = args[0][1]

    def get(self, addr):
        if addr.endswith("/mode"):
            self.raw[addr] = [self._mode]
        elif addr.endswith("/name"):
            self.raw[addr] = [self._name]


def test_taking_over_a_midi_button_renames_it_on_the_console(bridge, monkeypatch):
    """A button that now fires a rack key has to say so on the desk. Adopting
    one silently is how this looked broken: the app said yes and the console
    showed the same old label."""
    monkeypatch.setattr(type(bridge), "_wing_query",
                        lambda self, addrs, **kw: {a: [bridge.wing._mode if a.endswith("mode")
                                                       else bridge.wing._name] for a in addrs})
    bridge.wing = FakeWing(mode="MIDICCP", name="SCENE UP")
    bridge.uk_names = {16: "Tap Tempo"}

    r = bridge.assign_button("uk16", "U4/4/bu")
    assert r["ok"] and r.get("adopted") is True
    assert ("/$ctl/user/U4/4/bu/name", "Tap Tempo") in bridge.wing.sent
    # Its function is untouched: no mode was written.
    assert not [a for a, _ in bridge.wing.sent if a.endswith("/mode")]
    assert bridge.cfg["buttonsAdopted"]["U4/4/bu"] == "SCENE UP"
    assert "U4/4/bu" not in bridge.cfg.get("buttonsOwned", [])


def test_releasing_an_adopted_button_gives_its_name_back(bridge, monkeypatch):
    monkeypatch.setattr(type(bridge), "_wing_query",
                        lambda self, addrs, **kw: {a: [bridge.wing._mode if a.endswith("mode")
                                                       else bridge.wing._name] for a in addrs})
    bridge.wing = FakeWing(mode="MIDICCP", name="SCENE UP")
    bridge.uk_names = {16: "Tap Tempo"}
    bridge.assign_button("uk16", "U4/4/bu")

    bridge.release_button("uk16")
    assert bridge.wing.sent[-1] == ("/$ctl/user/U4/4/bu/name", "SCENE UP")
    assert "U4/4/bu" not in bridge.cfg["buttonsAdopted"]
    assert "uk16" not in bridge.cfg["buttons"]
