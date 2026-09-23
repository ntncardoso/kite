"""Selecting a strip on the console opens the mapped rack.

This is the whole point of the bridge, so the rules it must keep are pinned
here: only when following, only when connected, never twice for the same rack,
and never when the rack under the link has changed name.
"""

import pytest


class FakeWaves:
    def __init__(self, racks=(), connected=True):
        self.connected = connected
        self.racks = list(racks)
        self.shown = []
        self.health = {}

    def show_rack(self, idx):
        self.shown.append(idx)
        return True, ""


def rack(index, name, empty=False):
    return {"index": index, "name": name, "empty": empty}


@pytest.fixture
def linked(bridge):
    bridge.waves = FakeWaves([rack(0, "KICK"), rack(4, "VOX"), rack(7, "GTR")])
    bridge.cfg["map"] = {"ch/1": 4}
    bridge.cfg["follow"] = True
    bridge.last_rack = None
    bridge._current_rack = None
    return bridge


def test_selection_opens_mapped_rack(linked):
    linked._on_wing_selection("ch", 1, "Lead Vox")
    assert linked.waves.shown == [4]
    # rack navigation continues from where selection left off
    assert linked._current_rack == 4


def test_unmapped_strip_opens_nothing(linked):
    linked._on_wing_selection("ch", 2, "Snare")
    assert linked.waves.shown == []


def test_follow_off_opens_nothing(linked):
    linked.cfg["follow"] = False
    linked._on_wing_selection("ch", 1, "Lead Vox")
    assert linked.waves.shown == []


def test_same_rack_is_not_sent_twice(linked):
    linked._on_wing_selection("ch", 1, "Lead Vox")
    linked._on_wing_selection("ch", 1, "Lead Vox")
    assert linked.waves.shown == [4]


def test_disconnected_superrack_is_reported_not_raised(linked):
    linked.waves.connected = False
    linked._on_wing_selection("ch", 1, "Lead Vox")
    assert linked.waves.shown == []
    assert any("not connected" in line for line in linked.logs)


def test_anchor_mismatch_holds_the_link(linked):
    """A reordered session must not silently open somebody else's rack."""
    linked.cfg["anchors"] = {"ch/1": "VOX"}
    linked.waves.racks = [rack(0, "KICK"), rack(4, "DRUM BUS"), rack(7, "GTR")]
    linked._on_wing_selection("ch", 1, "Lead Vox")
    assert linked.waves.shown == []
    assert any("held" in line for line in linked.logs)


def test_matching_anchor_opens_normally(linked):
    linked.cfg["anchors"] = {"ch/1": "VOX"}
    linked._on_wing_selection("ch", 1, "Lead Vox")
    assert linked.waves.shown == [4]


def test_anchor_is_ignored_until_the_inventory_is_known(linked):
    """No rack list yet is not evidence of a mismatch — open and let it be."""
    linked.cfg["anchors"] = {"ch/1": "VOX"}
    linked.waves.racks = []
    linked._on_wing_selection("ch", 1, "Lead Vox")
    assert linked.waves.shown == [4]
