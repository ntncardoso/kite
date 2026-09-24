"""What the page is allowed to call, and nothing else.

The window toolkit builds its JavaScript bridge by walking the object it is
handed — and it walks into whatever that object holds, with no depth limit and
no cycle detection. Handed the application itself it went through the live
device clients, their threads and sockets, the tray icon and its images. On
Windows the window waits for that walk to finish, and with a console connected
it never did: the app opened and hung before it drew anything (found on a desk
with the console plugged in, 2026-09-24). macOS survived the same walk, which
is why it took a second machine to see it.

So the page gets this instead: one object whose every public name is a method
it is meant to call. The application it delegates to is private, so the walk
stops here.

Adding a method here is what makes it callable from the page; that is the
point. Each one is a plain pass-through — no logic lives in this file.
"""


class JsApi:
    def __init__(self, app):
        self._app = app                 # leading underscore: not walked, not exposed

    # -- state ---------------------------------------------------------
    def get_state(self):
        return self._app.get_state()

    def save_mapping(self, data):
        return self._app.save_mapping(data)

    def set_follow(self, on):
        return self._app.set_follow(on)

    # -- devices -------------------------------------------------------
    def connect_wing(self, host):
        return self._app.connect_wing(host)

    def list_interfaces(self):
        return self._app.list_interfaces()

    def scan_wing(self, iface=None):
        return self._app.scan_wing(iface)

    def get_network(self):
        return self._app.get_network()

    def set_network(self, data):
        return self._app.set_network(data)

    # -- names ---------------------------------------------------------
    def pull_names(self, source="both"):
        return self._app.pull_names(source)

    def push_names(self, data, target="both"):
        return self._app.push_names(data, target)

    # -- console buttons and the host's USER KEYS -----------------------
    def scan_buttons(self):
        return self._app.scan_buttons()

    def assign_button(self, action, key, replace=False):
        return self._app.assign_button(action, key, replace)

    def release_button(self, action):
        return self._app.release_button(action)

    def press_user_key(self, n):
        return self._app.press_user_key(n)

    def export_midi_map(self, out_dir=None):
        return self._app.export_midi_map(out_dir)

    # -- sessions ------------------------------------------------------
    def list_sessions(self):
        return self._app.list_sessions()

    def save_session(self):
        return self._app.save_session()

    def save_session_as(self, name):
        return self._app.save_session_as(name)

    def new_session(self, name):
        return self._app.new_session(name)

    def load_session(self, name):
        return self._app.load_session(name)

    def rename_session(self, name, target=None):
        return self._app.rename_session(name, target)

    def delete_session(self, name):
        return self._app.delete_session(name)

    # -- support -------------------------------------------------------
    def save_diagnostics(self, out_dir=None):
        return self._app.save_diagnostics(out_dir)
