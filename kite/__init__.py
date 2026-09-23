"""Kite — a bridge between a mixing console and a plugin rack host.

Selecting a strip on the console opens the rack you linked it to, so the
engineer's hands stay on the console. The bridge reads and displays; it never
writes audio routing.

One name, one version, in one place: everything else imports them from here.
"""

__version__ = "0.1.2"

APP_NAME = "Kite"

# Where config, sessions and logs live. Kept separate from APP_NAME so the
# product can be renamed without orphaning anybody's saved sessions.
DATA_DIR_NAME = "Kite"
