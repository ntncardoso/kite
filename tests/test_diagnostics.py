"""The file a tester attaches to a report.

Two things have to hold, and the second one matters more: it must carry enough
to debug with, and it must not carry the customer's show.
"""

import zipfile

from kite import diagnostics, paths, runtime


def prepared(bridge):
    """A bridge with a show loaded and a machine to describe."""
    bridge.cfg.update({
        "iface": "en0", "wingHost": "192.0.2.10", "consoleName": "Desk 1",
        "prolinkPort": 57999, "follow": True, "session": "Gala Vandenberg",
        "map": {"ch/1": 4, "ch/2": 9}, "anchors": {"ch/1": "VOX"},
        "names": {"ch/1": "Lead Vox"}, "rackNames": {"4": "VOX"},
        "buttons": {"uk1": "U1/1/bu"}, "consoleUidFallback": "deadbeef" * 4,
    })
    bridge.logs = ["console: answering", "ch/1 -> rack 5"]
    bridge.waves = type("W", (), {"connected": True, "peer": "[::1]:1",
                                  "racks": [{}, {}], "health": {"cpu": 4}})()
    bridge.list_interfaces = lambda: [
        {"name": "en0", "ip": "192.0.2.9", "netmask": "255.255.255.0", "up": True}]
    return bridge


def test_the_report_carries_what_a_problem_needs(bridge, tmp_path):
    text = diagnostics.report(prepared(bridge))
    for expected in ("Kite", "rack host", "connected: True", "midi",
                     "en0", "Desk 1", "192.0.2.10", "ch/1 -> rack 5"):
        assert expected in text, expected


def test_the_report_never_carries_the_show(bridge, tmp_path):
    text = diagnostics.report(prepared(bridge))
    for secret in ("Lead Vox", "Gala Vandenberg", "VOX", "deadbeef"):
        assert secret not in text, f"{secret} must not be in a diagnostics report"
    assert "map: 2 entries" in text          # counted instead
    assert "a session is open: yes" in text


def test_a_key_nobody_vetted_stays_out(bridge, tmp_path):
    """Settings are listed one by one on purpose: something added later is
    private until somebody decides it is not."""
    b = prepared(bridge)
    b.cfg["somethingNewAndPersonal"] = "whatever it turns out to be"
    assert "whatever it turns out to be" not in diagnostics.report(b)


def test_the_bundle_holds_the_report_and_the_log(bridge, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG", tmp_path / "config.json")
    log = tmp_path / runtime.LOG_NAME
    log.write_text("a line from last night\n")
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)

    out = diagnostics.bundle(prepared(bridge), tmp_path)
    assert out.exists() and out.suffix == ".zip"
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "report.txt" in names
        assert runtime.LOG_NAME in names
        assert "a line from last night" in z.read(runtime.LOG_NAME).decode()


def test_a_home_directory_is_not_a_person_s_name(bridge, tmp_path):
    from pathlib import Path
    b = prepared(bridge)
    b.logs = [f"wrote {Path.home()}/Desktop/map.mrrc"]
    text = diagnostics.report(b)
    assert str(Path.home()) not in text
    assert "~/Desktop/map.mrrc" in text


def test_writing_it_never_raises_on_a_half_built_app(bridge, tmp_path, monkeypatch):
    """It is asked for when things are already wrong; it cannot be the thing
    that fails next."""
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)
    bridge.waves = None                      # as broken as it gets
    bridge.list_interfaces = lambda: 1 / 0
    out = diagnostics.bundle(bridge, tmp_path)
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        assert "could not be read" in z.read("report.txt").decode()


def test_the_desktop_is_asked_for_rather_than_assumed(tmp_path, monkeypatch):
    """A machine whose Desktop is elsewhere — redirected, or shared from a
    host — must not get a new empty folder nobody looks in."""
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.desktop_dir() == tmp_path          # no Desktop here: use home
    (tmp_path / "Desktop").mkdir()
    assert paths.desktop_dir() == tmp_path / "Desktop"
