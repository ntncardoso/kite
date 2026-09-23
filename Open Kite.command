#!/bin/zsh
# Double-click to start the bridge. It lives in the menu bar; the window can be
# closed without stopping it.
cd "${0:A:h}"
nohup .venv/bin/python -u -m kite >> "${TMPDIR:-/tmp}/kite.log" 2>&1 &
