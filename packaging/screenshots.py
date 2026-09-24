"""Regenerate the screenshots in docs/.

    python packaging/screenshots.py

Screenshots go stale the first time the interface changes, and nobody wants to
stage a show by hand to take them again. This loads the real page, fills it
with a show that never happened, and renders it with a headless browser — so
refreshing the images after a change is one command.

The data is invented on purpose. A real session's rack names belong to the
customer who paid for the show, and a screenshot in a public repository lasts
forever.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WEB = ROOT / "kite" / "web"
DOCS = ROOT / "docs"

BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "chromium", "google-chrome",
]

# A band that does not exist, on a console nobody owns.
STAGE = """
<script>
  const DEMO = [
    "KICK IN","KICK OUT","SNARE TOP","SNARE BOT","HI-HAT","TOM 1","TOM 2","FLOOR",
    "OH L","OH R","BASS DI","BASS AMP","GTR L","GTR R","AC GTR","KEYS L","KEYS R",
    "PIANO","SYNTH","PERC","SAX","TRUMPET","TROMBONE","LEAD VOX","VOX 2","BV 1",
    "BV 2","BV 3","TALKBACK","CLICK","PLAYBACK L","PLAYBACK R"
  ];
  function stage(){
    const racks = DEMO.map((n, i) => ({ index: i, name: n, stereo: i > 25, input: i }));
    for (let i = DEMO.length; i < 64; i++)
      racks.push({ index: i, name: "Rack " + (i + 1), stereo: false, input: -1 });
    replaceRacks(racks);

    DEMO.forEach((n, i) => { state.names["ch/" + (i + 1)] = n; });
    state.names["bus/1"] = "DRUM BUS";
    state.names["bus/2"] = "VOX BUS";
    state.names["main/1"] = "MAIN L/R";
    for (let i = 0; i < DEMO.length; i++) setLink("ch/" + (i + 1), i);

    for (const f of FAMS) state.openFams[f.k] = true;
    state.openGrps[0] = true;
    state.openGrps[1] = true;
    state.locked = true;
    applyLock();

    applyStatus({
      waves: { connected: true, peer: "[fe80::1]:57999", racks: 64,
               health: { sampleRate: 48000, cpu: 12, ioBox: true, sgs: true,
                         snapshot: 3, sessionDirty: false } },
      wing: { connected: true, probing: false, host: "192.0.2.24" },
      follow: true
    });
    document.getElementById("winghost").value = "192.0.2.24";
    const sel = document.getElementById("iface");
    sel.innerHTML = '<option value="en0">en0 &mdash; 192.0.2.9</option>';
    sel.disabled = false;
    for (const id of ["btn-scan", "btn-connect", "btn-adv", "btn-auto", "btn-clear"])
      document.getElementById(id).disabled = false;
    render();
    say("said", DEMO.length + " strips linked.");
  }

  function stageKeys(){
    ukNames = {
      1: "Toggle View: Overview1", 2: "Last Rack", 3: "Tap Tempo", 4: "Lock",
      5: "Next Snapshot", 6: "Previous Snapshot", 7: "Mute ALL", 8: "Bypass Rack",
    };
    consoleBtns = [];
    for (let b = 1; b <= 4; b++) for (let n = 1; n <= 4; n++)
      consoleBtns.push({ key: `U${b}/${n}/bu`, mode: b <= 3 ? "MIDICCP" : "OFF",
                         name: "", fname: "" });
    btnState = {
      buttons: { "uk1": "U1/1/bu", "uk2": "U1/2/bu", "uk3": "U1/3/bu", "uk4": "U1/4/bu",
                 "uk5": "U2/1/bu", "uk6": "U2/2/bu", "uk7": "U2/3/bu", "uk8": "U2/4/bu",
                 "rack-prev": "U3/1/bu", "rack-next": "U3/2/bu",
                 "plugin-prev": "U3/3/bu", "plugin-next": "U3/4/bu" },
      pending: [], learning: null,
    };
    renderButtons();
    showTab("keys");
  }

  window.addEventListener("load", () => setTimeout(() => {
    stage();
    if (window.SHOW_KEYS) stageKeys();
  }, 400));
</script>
"""

# name, extra script, window size
SHOTS = [
    ("patch-sheet", "", (1280, 1000)),
    ("user-keys", "<script>window.SHOW_KEYS = true;</script>", (1280, 780)),
    ("dark-theme", "", (1280, 1000)),
]


def browser():
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    sys.exit("no Chromium-based browser found — install Chrome or Edge")


def build(tmp, name, extra, dark):
    page = (WEB / "index.html").read_text()
    if dark:
        page = page.replace('localStorage.getItem("kite-theme") === "dark" ? "dark" : "light"',
                            '"dark"')
    # The flag has to be set before the page's own load handler runs.
    out = Path(tmp) / f"{name}.html"
    out.write_text(extra + page + STAGE)
    return out


def main():
    DOCS.mkdir(exist_ok=True)
    chrome = browser()
    with tempfile.TemporaryDirectory() as tmp:
        for f in ("app.css", "app.js"):
            shutil.copy(WEB / f, Path(tmp) / f)
        for name, extra, (w, h) in SHOTS:
            page = build(tmp, name, extra, dark=name.startswith("dark"))
            target = DOCS / f"{name}.png"
            subprocess.run([
                chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                "--force-device-scale-factor=2", f"--window-size={w},{h}",
                "--virtual-time-budget=6000", f"--screenshot={target}",
                page.as_uri(),
            ], check=True, capture_output=True)
            print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
