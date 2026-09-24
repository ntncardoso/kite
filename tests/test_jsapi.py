"""The page's API is a door, not an open plan.

The toolkit builds its bridge by walking whatever object it is given, into
every object that one holds. Given the application it walked the device
clients, their threads and the tray's images, and on Windows the window waited
for that walk and never opened. These tests hold the door shut.
"""

import inspect
import re
from pathlib import Path

from kite.app import App
from kite.jsapi import JsApi

WEB = Path(__file__).resolve().parent.parent / "kite" / "web" / "app.js"


def exposed():
    return {n for n in dir(JsApi) if not n.startswith("_")}


def test_everything_the_page_calls_exists():
    called = set(re.findall(r"API\.([a-z_]+)", WEB.read_text()))
    missing = called - exposed()
    assert not missing, f"the page calls {missing}, which the API does not offer"


def test_nothing_is_offered_that_the_page_never_calls():
    """An API surface grows by accident. Every door here is one somebody opens."""
    called = set(re.findall(r"API\.([a-z_]+)", WEB.read_text()))
    assert not exposed() - called


def test_every_method_reaches_the_application():
    for name in exposed():
        assert hasattr(App, name), f"JsApi.{name} has nothing behind it"


def test_the_application_itself_is_not_reachable():
    """What the toolkit walks must end here: a public attribute holding the app,
    a client or a socket is how the window came to hang."""
    api = JsApi(object())
    for name in exposed():
        assert inspect.isfunction(getattr(JsApi, name)), f"{name} must be a plain method"
    assert all(n.startswith("_") for n in vars(api)), vars(api)
