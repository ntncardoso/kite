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
