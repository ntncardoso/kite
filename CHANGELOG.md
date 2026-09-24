# Changelog

Based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.6] — 2026-09-24

Two faults that only a Windows machine with a console attached could show.

### Fixed
- **The app hung on Windows as soon as a console was connected.** The window
  toolkit builds its JavaScript bridge by walking the object it is handed, and
  walks into whatever that object holds, with no depth limit: handed the whole
  application it went through the live device clients, their threads and
  sockets, and the tray's images. On Windows the window waits for that walk,
  and with a console connected it never finished. The page now gets a small
  object holding only the methods it may call.
- The remote-control endpoint listened on IPv6 only on Windows, so a rack host
  arriving over IPv4 was refused. One socket now serves both stacks.

### Verified
- A real console, a Windows build: four selections on the desk produced four
  correct rack commands, in order. The console half of this app had never run
  on Windows before.

## [0.1.5] — 2026-09-24

### Fixed
- One press on a console button fired two actions. The app set a button's mode
  but never gave it a MIDI assignment of its own, so buttons sat on the
  console's default — channel 1, CC 0 — and the console mirrors controls that
  share an assignment: one press reported on both addresses a millisecond
  apart, and the bridge obeyed both. Buttons it sets up now get channel 16 and
  a CC of their own, and a console configured by an earlier version is
  repaired the moment it starts answering.

## [0.1.4] — 2026-09-24

Found with a console on the desk and the rack host running — three ways the
app stayed quiet while nothing happened.

### Fixed
- Taking over a console button that was already in a MIDI mode wrote nothing
  to it, so the button's screen kept its old label and the app looked as if it
  had ignored the request. It now renames the button for the action it fires,
  leaves its function alone, and remembers the old name to put back when the
  button is released.
- The button beside a USER KEY row said **Send**, which reads as "send this to
  the console". It fires the key in the rack host and changes nothing on the
  console, so it says **Test**.

### Added
- A warning, in the USER keys tab and in the log, when the rack host has no
  USER KEYS assigned. A press reaches it and does nothing, because there is
  nothing behind the key — which looks exactly like a broken bridge.

## [0.1.3] — 2026-09-23

### Added
- **Help → Save diagnostics**: one zip on the Desktop with the log, the
  rotated logs behind it, and the facts that make them readable — versions,
  what was connected, the MIDI port, the network interfaces. It sends nothing
  anywhere, and it leaves out the patch sheet, the names and the session
  names; those appear only as counts. The issue form points at it.

## [0.1.2] — 2026-09-23

One fix, and it is the reason to replace 0.1.1 on Windows.

### Fixed
- Closing the window hung the app on Windows. Windows recorded it as
  AppHangB1 and ended the process; nothing appeared in the app's own log,
  because the freeze happens before the line is written. The window is now
  hidden from a thread that is not the one drawing it: the toolkit runs a
  closing handler inline on the drawing thread, and hiding from there hands
  the work back to a thread that is busy running the handler. Verified on
  Windows: close, still running, and the window comes back when asked.

## [0.1.1] — 2026-09-23

Interface and packaging. Nothing here changes what the bridge does.

### Added
- A light/dark switch at the right of the header. The app opens light on every
  machine now instead of following the system, so it looks the same wherever it
  is opened; the choice is remembered per machine.
- Session files carry the format they were written in, and a file from a newer
  version is refused out loud rather than loaded half way.
- A whole protocol session is tested over a real socket against a stand-in for
  the rack host, on every platform — the part that had only ever run on one
  machine.

### Changed
- The header no longer rearranges itself as the window is resized: two fixed
  rows at every size, and text gives way before layout does.
- The window opens at its minimum size, 1000x620.
- The zoom buttons and the percentage are gone; the wheel with ctrl (or the
  trackpad) does it, and zoom starts at 100% every launch instead of being
  remembered.

### Fixed
- Closing the window froze the app: the close handler pushed a log line to the
  page and waited for the page, which waits on the same thread. Page events now
  go through a queue drained by one thread.
- The theme icon was a text character the page's fonts do not carry — clipped
  on macOS, missing on Windows. It is drawn now.
- A missing MIDI port on Windows said so on screen but not in the log.
- The scan results landed on top of the buttons beside them.

## [0.1.0] — 2026-09-23

The first release with a name, a version and tests of its own. It gathers the
work done so far, already in real use.

### Added
- The strip ↔ rack patch grid: selecting a strip on the console opens the rack
  it is linked to.
- Name anchors: if racks are reordered, the link is held and flagged instead of
  opening the wrong rack.
- Rack and plugin navigation, starting from the last rack opened and skipping
  empty racks.
- Reading and writing names between console and host, always explicitly. When
  writing to the console, the name also goes to the source when the strip is
  set to "source name", which is where its screen reads it from.
- The host's 16 USER KEYS over MIDI (one CC per key, channel 16, a single
  message per press) and an export of the host's MIDI map file.
- USER KEY names read from the open session and the host's log, shown on the
  console's USER buttons.
- Remote setup of the console's USER buttons, queued while the console is off
  and put back to OFF when released.
- Host health (racks, sample rate, CPU, snapshot, unsaved session) in the
  window and in the tray menu, updating live.
- A console identity derived from the machine: **Assign** once, and only once.
- One instance at a time; starting again brings the window forward.

### Changed
- The app carries its own name, Kite, and its own data directory, adopting
  the previous version's config and sessions on first run.
- `config.json` is written through a temporary file and an atomic replace.
- Closing the window no longer stops the bridge; only Quit in the tray does.
- The code is a package (`kite/`) and the page is split into HTML, CSS and
  JS.
- Threads are supervised and the app keeps a rotating log file next to the
  config, so a show can be looked into afterwards.

### Fixed
- Hangs on start and on close, caused by events pushed to a page that had not
  loaded yet or had already closed.
- Mangled text: the page declares UTF-8 and is loaded by plain file path.
- USER KEY presses undoing themselves: a single MIDI message per press.
