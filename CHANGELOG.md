# Changelog

Based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
