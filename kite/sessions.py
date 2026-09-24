"""Shows, saved as files: the patch sheet and everything that belongs to it.

Saving is explicit. Editing the sheet changes what is on screen and nothing
else — a show stays as it was saved until somebody says Save. That is the rule
a stage is run by, so it is the rule here.
"""

import json

from . import paths

# What belongs to a show rather than to this machine: the patch sheet and which
# console button does what. Network settings, the console identity and the MIDI
# port stay in config.json and are never carried by a session.
SESSION_KEYS = ("map", "anchors", "names", "rackNames", "rackCount",
                "buttons", "buttonsOwned", "buttonsPending", "buttonsToFree",
                "buttonsAdopted")

# The shape of a session file. It is written into every file so that a future
# version can tell what it is reading, and so that a file written by a NEWER
# version is refused out loud instead of loading half of itself — a patch sheet
# that is quietly wrong is worse than one that will not open.
#
# 1 — the original shape: the keys above, at the top level.
#     Files from before this field exists are that shape, so a file with no
#     version is read as 1 rather than rejected.
SESSION_FORMAT = 1


def session_path(name):
    """Sessions are files named after themselves; keep the name file-safe."""
    safe = "".join(c for c in str(name or "") if c.isalnum() or c in " ._-").strip()
    return (paths.SESSIONS / f"{safe}.json") if safe else None


class SessionStore:
    """The session commands, over a live config dictionary.

    It is given the app's config and the few things it cannot know on its own:
    how to persist the config, where to log, how many racks the host reports,
    and what to do after a load (the console buttons have to follow).
    """

    def __init__(self, cfg, save, log, rack_count=lambda: 0, on_load=lambda: None):
        self.cfg = cfg
        self._save = save
        self._log = log
        self._rack_count = rack_count
        self._on_load = on_load

    # ------------------------------------------------------------- state

    def data(self):
        return {k: self.cfg.get(k) for k in SESSION_KEYS}

    def dirty(self):
        """True when what is on screen differs from the saved session."""
        path = session_path(self.cfg.get("session"))
        if not path or not path.exists():
            return bool(self.cfg.get("session")) or any(self.cfg.get(k) for k in SESSION_KEYS)
        try:
            saved = json.loads(path.read_text())
        except (OSError, ValueError):
            return True
        return {k: saved.get(k) for k in SESSION_KEYS} != self.data()

    def listing(self):
        rows = []
        try:
            for p in sorted(paths.SESSIONS.glob("*.json")):
                rows.append({"name": p.stem, "saved": int(p.stat().st_mtime)})
        except OSError:
            pass
        current = self.cfg.get("session", "")
        if current and not any(r["name"] == current for r in rows):
            rows.insert(0, {"name": current, "saved": 0})
        return {"sessions": rows, "current": current, "dirty": self.dirty()}

    # ---------------------------------------------------------- commands

    def save(self):
        """Write the open session to its file."""
        path = session_path(self.cfg.get("session"))
        if not path:
            return {"ok": False, "msg": "no session open — use Save as"}
        try:
            paths.SESSIONS.mkdir(parents=True, exist_ok=True)
            body = {"version": SESSION_FORMAT, **self.data()}
            path.write_text(json.dumps(body, indent=2, ensure_ascii=False))
        except OSError as e:
            return {"ok": False, "msg": f"could not save ({e})"}
        self._log(f"session saved: {path.stem}")
        return {"ok": True, **self.listing()}

    def save_as(self, name):
        """Copy what is loaded now into a new session, and work in it."""
        path = session_path(name)
        if not path:
            return {"ok": False, "msg": "give the session a name"}
        if path.exists() and path.stem != self.cfg.get("session"):
            return {"ok": False, "msg": f'"{path.stem}" already exists'}
        self.cfg["session"] = path.stem
        self._save()
        self.save()
        self._log(f"session saved as {path.stem}")
        return {"ok": True, **self.listing()}

    def new(self, name):
        """Start an empty patch sheet under a new name."""
        path = session_path(name)
        if not path:
            return {"ok": False, "msg": "give the session a name"}
        if path.exists():
            return {"ok": False, "msg": f'"{path.stem}" already exists'}
        for k in SESSION_KEYS:
            self.cfg[k] = [] if k.startswith("buttons") and k != "buttons" else {}
        self.cfg["rackCount"] = self._rack_count() or 64
        self.cfg["session"] = path.stem
        self._save()
        self.save()
        self._log(f"new session {path.stem}")
        return {"ok": True, "cfg": self.cfg, **self.listing()}

    def load(self, name):
        path = session_path(name)
        if not path or not path.exists():
            return {"ok": False, "msg": "that session is gone"}
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            return {"ok": False, "msg": f"could not read it ({e})"}
        version = data.get("version", 1) if isinstance(data, dict) else None
        if not isinstance(version, int):
            return {"ok": False, "msg": "that file is not a session"}
        if version > SESSION_FORMAT:
            # Nothing is loaded: what is on screen is left exactly as it was.
            return {"ok": False,
                    "msg": f'"{path.stem}" was saved by a newer version of the app '
                           f"(format {version}; this one reads {SESSION_FORMAT}). "
                           f"Update, or save it again from the version that wrote it."}
        for k in SESSION_KEYS:
            if k in data:
                self.cfg[k] = data[k]
        self.cfg["session"] = path.stem
        self._save()
        self._log(f"session loaded: {path.stem}")
        self._on_load()            # the console buttons belong to the session too
        return {"ok": True, "cfg": self.cfg, **self.listing()}

    def rename(self, name, target=None):
        old = session_path(target or self.cfg.get("session"))
        new = session_path(name)
        if not new:
            return {"ok": False, "msg": "give the session a name"}
        if new.exists():
            return {"ok": False, "msg": f'"{new.stem}" already exists'}
        if target and target != self.cfg.get("session"):
            # Renaming another session: move its file, leave the open one alone.
            try:
                old.rename(new)
            except OSError as e:
                return {"ok": False, "msg": f"could not rename ({e})"}
            return {"ok": True, **self.listing()}
        self.cfg["session"] = new.stem
        self._save()
        self.save()
        if old and old.exists() and old != new:
            try:
                old.unlink()
            except OSError:
                pass
        return {"ok": True, **self.listing()}

    def delete(self, name):
        path = session_path(name)
        if not path or not path.exists():
            return {"ok": False, "msg": "that session is gone"}
        try:
            path.unlink()
        except OSError as e:
            return {"ok": False, "msg": f"could not delete it ({e})"}
        self._log(f"session deleted: {path.stem}")
        if self.cfg.get("session") == path.stem:
            # Keep what is on screen; it is simply no longer a saved session.
            self.cfg["session"] = ""
            self._save()
        return {"ok": True, **self.listing()}
