"""App instances for tests: real code, but never touching the real machine.

Config and sessions go to a temp directory, and nothing opens a socket.
"""

import pytest

from kite import app as appmod
from kite import paths
from kite.sessions import SessionStore


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(paths, "SESSIONS", tmp_path / "Sessions")
    a = appmod.App.__new__(appmod.App)          # no sockets, no window
    a.cfg = paths.load_config()
    a.wing = None
    a.midi = type("NoMidi", (), {"out": None, "error": None, "name": "test",
                                 "port": None, "persistent": False,
                                 "press": lambda s, cc: False})()
    a.uk_names = {}
    a.logs = []
    a._log = a.logs.append
    a._push = lambda kind, payload: None
    a.waves = type("NoWaves", (), {"connected": False, "racks": [], "health": {}})()
    a.sessions = SessionStore(a.cfg, save=a._save_config, log=a._log,
                              rack_count=lambda: len(a.waves.racks))
    return a
