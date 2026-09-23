"""Events reach the page without any caller ever waiting for it.

evaluate_js blocks until the page answers, and the page answers on the UI
thread. Anything that pushed from that thread — the window close handler, for
one — waited for itself and froze the whole application. Nothing may push
directly again.
"""

import queue
import threading

from kite import app as appmod


class FakeWindow:
    """A window that records, and shouts if it is called synchronously."""

    def __init__(self):
        self.calls = []
        self.allowed = False

    def evaluate_js(self, script):
        assert self.allowed, "the page was called from the pushing caller's thread"
        self.calls.append(script)


def pusher(bridge, maxsize=appmod.App.PUSH_QUEUE_MAX):
    """The real _push/_push_loop, on a bridge built by the fixture."""
    bridge.window = FakeWindow()
    bridge._pushq = queue.Queue(maxsize=maxsize)
    bridge._push = appmod.App._push.__get__(bridge)
    bridge._page_ready = True
    return bridge.window


def test_pushing_does_not_call_the_page(bridge):
    win = pusher(bridge)
    bridge._push("log", "hello")
    assert win.calls == []                       # queued, not delivered here
    assert bridge._pushq.qsize() == 1


def test_a_page_that_stopped_listening_cannot_grow_the_queue(bridge):
    pusher(bridge, maxsize=3)
    for i in range(6):
        bridge._push("log", i)
    assert bridge._pushq.qsize() == 3
    kept = [bridge._pushq.get()[1] for _ in range(3)]
    assert kept == [3, 4, 5]                     # the newest survive, the oldest go


def test_nothing_is_queued_once_the_app_is_closing(bridge):
    pusher(bridge)
    bridge._closing = True
    try:
        bridge._push("log", "too late")
        assert bridge._pushq.qsize() == 0
    finally:
        bridge._closing = False


def test_the_pusher_thread_delivers(bridge):
    win = pusher(bridge)
    win.allowed = True
    delivered = threading.Event()
    bridge._pushq.put(("log", "on its way"))

    t = threading.Thread(target=appmod.App._push_loop.__get__(bridge), daemon=True)
    t.start()
    for _ in range(200):                         # up to ~2 s, without a fixed sleep
        if win.calls:
            delivered.set()
            break
        threading.Event().wait(0.01)
    bridge._closing = True
    bridge._pushq.put(("log", "wake up and stop"))
    t.join(timeout=2)
    bridge._closing = False

    assert delivered.is_set()
    assert "on its way" in win.calls[0]
    assert win.calls[0].startswith("window.onBridgeEvent && window.onBridgeEvent(")
