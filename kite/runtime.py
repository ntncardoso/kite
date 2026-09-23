"""Two things a tool used in a show cannot do without: a log that survives the
app, and threads that say so when they die.

Both are deliberately small. Nothing here may raise on its own account — a
failure to log is not a reason to stop bridging.
"""

import logging
import logging.handlers
import threading

from . import APP_NAME, __version__

LOG_NAME = "kite.log"
MAX_BYTES = 1_000_000          # about a fortnight of ordinary use
BACKUPS = 3

_log = logging.getLogger("kite")


def setup_logging(directory, level=logging.INFO):
    """A rotating file log next to the config, plus the console.

    Kept next to the config so "open the config folder" also hands over the
    log: after a show, that is the one thing worth having.
    """
    _log.setLevel(level)
    _log.propagate = False
    if _log.handlers:
        return _log
    fmt = logging.Formatter("%(asctime)s %(levelname).1s %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            directory / LOG_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        fh.setFormatter(fmt)
        _log.addHandler(fh)
    except OSError:
        pass                   # a read-only home is not a reason to refuse to start
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    _log.addHandler(sh)
    _log.info("%s %s starting", APP_NAME, __version__)
    return _log


def log_line(msg):
    """Record one of the app's own status lines."""
    try:
        _log.info("%s", msg)
    except Exception:
        pass


def spawn(target, *args, name=None, on_error=None, **kwargs):
    """Start a daemon thread that cannot disappear quietly.

    A thread that dies on an unhandled exception takes its job with it — the
    console stops being polled, or presses stop being applied — and by default
    Python prints the traceback where nobody is looking. Here it is logged and
    handed to `on_error`, so the app can put it on screen.
    """
    def run():
        try:
            target(*args, **kwargs)
        except Exception as e:
            _log.exception("thread %s stopped: %s", name or getattr(target, "__name__", "?"), e)
            if on_error:
                try:
                    on_error(e)
                except Exception:
                    pass

    t = threading.Thread(target=run, name=name or getattr(target, "__name__", None), daemon=True)
    t.start()
    return t
