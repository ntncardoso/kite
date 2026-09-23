"""The menu-bar / system-tray icon.

The window can be closed; this is what stays. It shows the same three facts as
the window header and offers the only way to quit.

The icon is optional on purpose: if the platform will not give us one, the
bridge keeps running without it rather than refusing to start.
"""

import sys

from . import APP_NAME


def make_image(active):
    """Three faders — the vocabulary of the thing. Drawn rather than shipped as
    a file, so there is one less resource to lose in packaging."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fg = (223, 162, 68, 255) if active else (140, 140, 140, 255)
    for i, h in enumerate((34, 46, 26)):
        x = 14 + i * 18
        d.line([(x, 14), (x, 50)], fill=fg, width=3)
        d.rectangle([x - 7, 50 - h, x + 7, 56 - h], fill=fg)
    return img


class Tray:
    """Wraps pystray, and survives its absence.

    `lines` returns the status lines to show; `follow` and `set_follow` read
    and write the one setting worth having here; `on_open` and `on_quit` are
    the two actions.
    """

    N_LINES = 3

    def __init__(self, lines, follow, set_follow, on_open, on_quit, log=print):
        self._lines = lines
        self._follow = follow
        self._set_follow = set_follow
        self._on_open = on_open
        self._on_quit = on_quit
        self._log = log
        self.icon = None
        self._shown = None

    def start(self):
        try:
            import pystray
            from pystray import MenuItem as Item

            # Read-only status lines at the top; greyed out, as they are not actions.
            def info(i):
                return lambda item: self._lines()[i]

            menu = pystray.Menu(
                *[Item(info(i), None, enabled=False) for i in range(self.N_LINES)],
                pystray.Menu.SEPARATOR,
                Item("Open window", lambda: self._on_open(), default=True),
                Item("Open rack on strip select", lambda icon, item: self._set_follow(not self._follow()),
                     checked=lambda i: self._follow()),
                pystray.Menu.SEPARATOR,
                Item("Quit", lambda: self._on_quit()),
            )
            self.icon = pystray.Icon(APP_NAME.lower(), make_image(False), APP_NAME, menu)
            self.icon.run_detached()
            self._log("tray active")
        except Exception as e:
            # Without a tray the app is still usable — it just loses the shortcut.
            self.icon = None
            self._log(f"tray unavailable ({e}) — the app still works")

    def refresh(self, connected):
        if not self.icon:
            return
        try:
            self.icon.icon = make_image(connected)
            self.icon.title = f"{APP_NAME} — " + ("connected" if connected else "waiting")
            lines = self._lines()
            if lines == self._shown:           # redraw only when the text changes
                return
            self._shown = lines
            if sys.platform == "darwin":
                self._retitle_mac(lines)
            else:
                self.icon.update_menu()
        except Exception:
            pass                               # the tray is never worth an exception

    def _retitle_mac(self, lines):
        """Retitle the existing items instead of rebuilding the menu.

        A rebuilt menu is only seen the next time it is opened, while a
        retitled item updates as it is being looked at. This has to happen on
        the main thread, which callAfter reaches in every run-loop mode —
        including the one AppKit uses while a menu is open.
        """
        from PyObjCTools import AppHelper

        def retitle():
            try:
                nsmenu = self.icon._menu_handle[0]
                for i, text in enumerate(lines):
                    nsmenu.itemAtIndex_(i).setTitle_(text)
            except Exception:
                self.icon.update_menu()

        AppHelper.callAfter(retitle)
