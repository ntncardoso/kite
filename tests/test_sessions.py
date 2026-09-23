"""Sessions are the show. They save when asked, not as you type."""

import json

from kite import paths


def test_new_session_starts_empty_and_writes_a_file(bridge):
    bridge.cfg["map"] = {"ch/1": 3}
    r = bridge.new_session("Gala")
    assert r["ok"] is True
    assert bridge.cfg["map"] == {}
    assert (paths.SESSIONS / "Gala.json").exists()


def test_editing_does_not_reach_the_file_until_save(bridge):
    bridge.save_session_as("Show")
    bridge.cfg["map"] = {"ch/1": 3}
    paths.save_config(bridge.cfg)
    saved = json.loads((paths.SESSIONS / "Show.json").read_text())
    assert saved["map"] == {}                     # still the saved show
    assert bridge.session_dirty() is True
    bridge.save_session()
    assert bridge.session_dirty() is False
    assert json.loads((paths.SESSIONS / "Show.json").read_text())["map"] == {"ch/1": 3}


def test_loading_brings_back_what_was_saved(bridge):
    bridge.cfg["map"] = {"ch/1": 3}
    bridge.save_session_as("A")
    bridge.new_session("B")
    assert bridge.cfg["map"] == {}
    bridge.load_session("A")
    assert bridge.cfg["map"] == {"ch/1": 3}
    assert bridge.cfg["session"] == "A"


def test_the_machine_settings_never_travel_with_a_session(bridge):
    bridge.cfg["wingHost"] = "192.0.2.10"        # documentation range, never a real console
    bridge.cfg["prolinkPort"] = 57999
    bridge.save_session_as("A")
    saved = json.loads((paths.SESSIONS / "A.json").read_text())
    assert "wingHost" not in saved and "prolinkPort" not in saved


def test_names_are_kept_file_safe(bridge):
    bridge.save_session_as("Gala/../etc 2026")
    assert bridge.cfg["session"] == "Gala..etc 2026"    # slashes dropped, not turned into paths


def test_a_session_cannot_be_overwritten_by_accident(bridge):
    bridge.save_session_as("A")
    bridge.new_session("B")
    assert bridge.save_session_as("A")["ok"] is False
    assert bridge.new_session("A")["ok"] is False


def test_delete_leaves_what_is_on_screen(bridge):
    bridge.cfg["map"] = {"ch/1": 3}
    bridge.save_session_as("A")
    assert bridge.delete_session("A")["ok"] is True
    assert bridge.cfg["map"] == {"ch/1": 3}
    assert bridge.cfg["session"] == ""


def test_rename_moves_the_file(bridge):
    bridge.save_session_as("A")
    bridge.rename_session("B")
    assert (paths.SESSIONS / "B.json").exists()
    assert not (paths.SESSIONS / "A.json").exists()
    assert bridge.cfg["session"] == "B"
