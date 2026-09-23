"""Entry point for the packaged application.

A frozen build needs a script to start from; everything it does is in the
package. Kept apart from the package so `python -m kite` stays the way the app
is started from source.
"""

import multiprocessing
import sys

from kite.app import main

if __name__ == "__main__":
    # A frozen app that ever spawns a process would otherwise re-run the whole
    # application in the child instead of the worker.
    multiprocessing.freeze_support()
    sys.exit(main())
