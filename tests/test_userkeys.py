"""USER KEY names for the console screens, and the MIDI map the host imports."""

import sqlite3

from kite import APP_NAME, userkeys


def a_session_with(tmp_path, keys):
    """A stand-in for the rack host's open session file."""
    path = tmp_path / "CurrentSPRKP.dat"
    con = sqlite3.connect(path)
    con.execute("create table user_keys (id integer primary key, key_index integer,"
                " key_action integer, selection_index integer, obj_type integer,"
                " obj_index integer, uk_friendly_name text)")
    for i in range(16):
        con.execute("insert into user_keys values (?,?,?,-1,-1,-1,'')",
                    (i + 1, i, keys.get(i + 1, 0)))
    con.commit()
    con.close()
    return path


def test_action_codes_become_names(bridge, tmp_path, monkeypatch):
    # Codes read from SuperRack's own menu code; 16/17/20 were confirmed live.
    monkeypatch.setattr(userkeys, "SESSION_CANDIDATES", [a_session_with(tmp_path, {1: 16, 2: 17, 16: 20})])
    monkeypatch.setattr(userkeys, "LOG_CANDIDATES", [tmp_path / "missing.log"])
    assert bridge._read_user_keys() == {1: "Toggle View", 2: "Last Rack", 16: "Tap Tempo"}


def test_unassigned_keys_are_left_out(bridge, tmp_path, monkeypatch):
    monkeypatch.setattr(userkeys, "SESSION_CANDIDATES", [a_session_with(tmp_path, {5: 19})])
    monkeypatch.setattr(userkeys, "LOG_CANDIDATES", [tmp_path / "missing.log"])
    assert bridge._read_user_keys() == {5: "Lock"}


def test_the_log_adds_the_target(bridge, tmp_path, monkeypatch):
    # "Toggle View" alone does not say which view; SuperRack's log does.
    log = tmp_path / "sr.log"
    log.write_text("Setup > Settings: Set UserKey 0 to Toggle View: Overview1 @[lib]\n")
    monkeypatch.setattr(userkeys, "SESSION_CANDIDATES", [a_session_with(tmp_path, {1: 16})])
    monkeypatch.setattr(userkeys, "LOG_CANDIDATES", [log])
    assert bridge._read_user_keys() == {1: "Toggle View: Overview1"}


def test_a_stale_log_line_never_wins_over_the_session(bridge, tmp_path, monkeypatch):
    log = tmp_path / "sr.log"
    log.write_text("Setup > Settings: Set UserKey 0 to Tap Tempo @[lib]\n")
    monkeypatch.setattr(userkeys, "SESSION_CANDIDATES", [a_session_with(tmp_path, {1: 17})])
    monkeypatch.setattr(userkeys, "LOG_CANDIDATES", [log])
    assert bridge._read_user_keys() == {1: "Last Rack"}


def test_console_labels_fit_sixteen_characters(bridge):
    bridge.uk_names = {1: "Toggle View: Overview1", 2: "Last Rack"}
    assert bridge._label("uk1") == "Overview1"          # cut at the colon, not mid-word
    assert bridge._label("uk2") == "Last Rack"
    assert bridge._label("uk7") == "SR KEY 7"           # not set in SuperRack
    assert len(bridge._label("uk1")) <= 16


def test_mrrc_maps_every_key_to_its_own_cc(bridge, tmp_path):
    r = bridge.export_midi_map(out_dir=tmp_path)
    assert r["ok"] and r["count"] == 16
    xml = (tmp_path / f"{APP_NAME}.mrrc").read_text()
    assert xml.count("<Command>") == 16
    assert "<Name>User Key #1</Name>" in xml and "<Name>User Key #16</Name>" in xml
    assert xml.count("<Channel>0x0F</Channel>") == 16   # channel 16, as midi_link sends
    assert "<Number>0x10</Number>" in xml               # key 16 on CC 16
    assert "<MultiRackVersion>" in xml                  # a file without it was refused
