"""Stepping SuperRack's view: next/previous rack and plugin.

Racks are stepped with ShowRackByID rather than NavigateRack, so the stepping
rules — skip empty racks, wrap around, start from the rack last opened — live
in the bridge and are pinned here.
"""

import pytest

from .test_selection import FakeWaves, rack


class NavWaves(FakeWaves):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.plugin_steps = []

    def navigate_plugin(self, arg):
        self.plugin_steps.append(arg)
        return True, ""


@pytest.fixture
def nav(bridge):
    bridge.waves = NavWaves([rack(0, "KICK"), rack(1, "", empty=True),
                             rack(2, "VOX"), rack(3, "GTR")])
    bridge._current_rack = None
    return bridge


def test_next_rack_skips_empty_slots(nav):
    nav._current_rack = 0
    assert nav.navigate("rack", 1)["ok"]
    assert nav.waves.shown == [2]


def test_previous_rack_skips_empty_slots(nav):
    nav._current_rack = 2
    nav.navigate("rack", 0)
    assert nav.waves.shown == [0]


def test_next_wraps_at_the_end(nav):
    nav._current_rack = 3
    nav.navigate("rack", 1)
    assert nav.waves.shown == [0]


def test_previous_wraps_at_the_start(nav):
    nav._current_rack = 0
    nav.navigate("rack", 0)
    assert nav.waves.shown == [3]


def test_first_step_without_a_current_rack_takes_an_end(nav):
    nav.navigate("rack", 1)
    nav._current_rack = None
    nav.navigate("rack", 0)
    assert nav.waves.shown == [0, 3]


def test_a_session_of_empty_racks_is_reported(nav):
    nav.waves.racks = [rack(0, "", empty=True)]
    out = nav.navigate("rack", 1)
    assert not out["ok"] and "no racks" in out["msg"]


def test_navigation_needs_a_connected_superrack(nav):
    nav.waves.connected = False
    out = nav.navigate("rack", 1)
    assert not out["ok"] and "not connected" in out["msg"]


def test_plugin_direction_is_inverted_for_prolink(nav):
    """NavigatePlugin's 0/1 run opposite to next/previous on screen."""
    nav.navigate("plugin", 1)
    nav.navigate("plugin", 0)
    assert nav.waves.plugin_steps == [0, 1]
