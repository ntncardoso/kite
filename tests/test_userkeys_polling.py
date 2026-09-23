"""The USER KEY names are re-read only when the host's files change.

Copying a session database every five seconds, for the length of a show, on
the machine running that show, is a cost worth not paying.
"""

from kite import userkeys


def test_stamp_changes_when_the_session_is_written(tmp_path, monkeypatch):
    session = tmp_path / "CurrentSPRKP.dat"
    log = tmp_path / "host.log"
    session.write_bytes(b"one")
    log.write_text("")
    monkeypatch.setattr(userkeys, "SESSION_CANDIDATES", [session])
    monkeypatch.setattr(userkeys, "LOG_CANDIDATES", [log])

    before = userkeys.stamp()
    assert userkeys.stamp() == before          # nothing happened, nothing to re-read
    session.write_bytes(b"one and a half")
    assert userkeys.stamp() != before


def test_stamp_survives_files_that_are_not_there(tmp_path, monkeypatch):
    monkeypatch.setattr(userkeys, "SESSION_CANDIDATES", [tmp_path / "gone.dat"])
    monkeypatch.setattr(userkeys, "LOG_CANDIDATES", [tmp_path / "gone.log"])
    assert userkeys.stamp() == (None, None)


def test_a_refresh_reads_once_while_nothing_changes(bridge, monkeypatch):
    reads = []
    monkeypatch.setattr(userkeys, "stamp", lambda: ("same",))
    bridge._read_user_keys = lambda: reads.append(1) or {1: "Lock"}
    bridge._rename_uk_buttons = lambda: None

    assert bridge._refresh_user_keys() is True        # first pass: the names arrive
    assert bridge._refresh_user_keys() is False
    assert bridge._refresh_user_keys() is False
    assert len(reads) == 1
    assert bridge.uk_names == {1: "Lock"}


def test_a_changed_file_is_read_again(bridge, monkeypatch):
    stamps = iter([("a",), ("b",), ("b",)])
    monkeypatch.setattr(userkeys, "stamp", lambda: next(stamps))
    reads = []
    bridge._read_user_keys = lambda: reads.append(1) or {1: "Lock"}
    bridge._rename_uk_buttons = lambda: None

    bridge._refresh_user_keys()
    bridge._refresh_user_keys()
    bridge._refresh_user_keys()
    assert len(reads) == 2
