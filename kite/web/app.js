  // Racks as last seen. Placeholders until the host sends its inventory
  // (onBridgeEvent 'racks'), which replaces this list wholesale.
  const RACKS = Array.from({length: 64}, (_, i) => ({ i, n: `Rack ${i+1}`, s: 0, in: -1 }));

  // WING families. No DCA: they carry no audio (no insert, no rack) and selidx
  // does not even cover them — 0..75 is ch/aux/bus/main/mtx.
  const FAMS = [
    { k:"ch",   label:"Channels", n:40, base:0  },
    { k:"aux",  label:"Aux",      n:8,  base:40 },
    { k:"bus",  label:"Buses",    n:16, base:48 },
    { k:"main", label:"Main",     n:4,  base:64 },
    { k:"mtx",  label:"Matrix",   n:8,  base:68 },
  ];
  const RACK_RANGE = { ch:[0,39], bus:[40,47] };   // ranges seen on this rig
  const GROUP = 16;                                // SuperRack groups, 16 max
  const STORE = "wing-patch-v3";
  const CELL_MIN = 14, CELL_MAX = 48, CELL_BASE = 30;

  let state = {
    map:{}, names:{}, rackNames:{}, anchors:{}, locked:true, cell:CELL_BASE,
    openFams: {},        // collapsed at rest, like the rack groups
    openGrps: {},
  };

  const norm = s => String(s||"").replace(/\s+/g," ").trim().toUpperCase();
  // A rack slot SuperRack has not named itself — its placeholder name is
  // "Rack 35" for index 34. Note this does NOT look at the input: whether
  // audio is patched to a rack has no bearing on whether a strip links to it.
  const isPlaceholder = r => /^Rack\s+\d+$/i.test(r.n);
  const key = (f,n) => `${f}/${n}`;
  const rackName = r => state.rackNames[r.i] ?? r.n;
  // SuperRack counts racks from 1 — its own placeholder for index 34 is
  // "Rack 35". Indices stay 0-based internally, which is what the protocol uses.
  const rackNo = r => r.i + 1;
  const rackCount = () => RACKS.length;

  /* Each link remembers the SuperRack name its rack had when the link was
     made. The map itself stores a rack INDEX, so if someone reorders racks in
     SuperRack the index still points at a rack — just not the one that was
     meant — and nothing about the protocol says so. Comparing names is the
     only way to notice. Real SuperRack names are compared, never the local
     labels typed here. */
  const rackAt = i => RACKS.find(r => r.i === i);
  function setLink(k, i){ state.map[k] = i; const r = rackAt(i); if (r) state.anchors[k] = r.n; }
  function clearLink(k){ delete state.map[k]; delete state.anchors[k]; }
  function ensureAnchors(){
    // Links from before anchoring existed take the current name as their anchor.
    for (const [k, i] of Object.entries(state.map))
      if (state.anchors[k] === undefined) { const r = rackAt(i); if (r) state.anchors[k] = r.n; }
  }
  function movedLinks(){
    const out = new Map();
    for (const [k, i] of Object.entries(state.map)) {
      const was = state.anchors[k];
      if (was === undefined) continue;
      const r = rackAt(i);
      if (!r || r.n !== was) out.set(k, { was, now: r ? r.n : null });
    }
    return out;
  }

  // What gets remembered between launches. openGrps/openFams are deliberately
  // left out: every launch starts from the collapsed resting state, while the
  // session keeps whatever you opened.
  // Zoom is deliberately absent: it lasts as long as the window is open and
  // every launch starts at 100%, so the grid is always the size it was left in
  // the manual, not the size somebody dragged it to at three in the morning.
  const PERSIST = ["map","names","rackNames","anchors"];
  let save = function(){
    try {
      const keep = {};
      for (const k of PERSIST) keep[k] = state[k];
      localStorage.setItem(STORE, JSON.stringify(keep));
    } catch(e){}
  };
  function restore(){
    try {
      const raw = localStorage.getItem(STORE);
      if (raw) {
        const p = JSON.parse(raw);
        if (p && typeof p === "object")
          for (const k of PERSIST) if (p[k] !== undefined) state[k] = p[k];
      }
    } catch(e){}
  }

  function groups(){
    const out = [], total = rackCount();
    for (let g = 0; g * GROUP < total; g++) {
      const lo = g*GROUP, hi = Math.min(lo+GROUP, total) - 1;
      out.push({ g, lo, hi, racks: RACKS.slice(lo, hi+1) });
    }
    return out;
  }
  // Collapsed is the resting state: the app opens compact, and the folded
  // columns still show a dot on any row that links inside them.
  function grpOpen(g){ return state.openGrps[g] === true; }
  function conflicts(){
    const seen = {}, bad = new Set();
    for (const [k,v] of Object.entries(state.map)) {
      if (v === undefined || v === null) continue;
      if (seen[v] !== undefined) { bad.add(k); bad.add(seen[v]); } else seen[v] = k;
    }
    return bad;
  }

  function render(){
    const gs = groups(), bad = conflicts(), moved = movedLinks();
    const wrap = document.getElementById("gridwrap");
    const keepX = wrap ? wrap.scrollLeft : 0, keepY = wrap ? wrap.scrollTop : 0;
    const t = document.getElementById("mx");
    t.innerHTML = "";

    // row 1 — rack group bands
    const r1 = t.insertRow();
    const corner = document.createElement("th");
    corner.className = "corner";
    corner.rowSpan = 2;                 // one cell across both header rows
    corner.innerHTML = `<div class="wrapc"><span class="rk">Racks</span><span class="st">Strips</span></div>`;
    r1.appendChild(corner);
    for (const gr of gs) {
      const th = document.createElement("th");
      const open = grpOpen(gr.g);
      th.className = "grp";
      th.colSpan = open ? gr.racks.length : 1;
      const real = gr.racks.filter(r => !isPlaceholder(r)).length;
      // Collapsed, the band carries only the [+]: the range goes vertically in
      // the name row below, so the column can stay as narrow as a cell instead
      // of being stretched by its own caption.
      th.innerHTML = open
        ? `<span class="exp">−</span>${gr.lo+1}–${gr.hi+1}<span class="tw">${real}</span>`
        : `<span class="exp">+</span>`;
      if (!open) th.classList.add("shutgrp");
      th.title = open ? `Collapse racks ${gr.lo+1}–${gr.hi+1}`
                      : `Expand racks ${gr.lo+1}–${gr.hi+1} — ${real} named`;
      th.addEventListener("click", () => { state.openGrps[gr.g] = !open; save(); render(); });
      r1.appendChild(th);
    }
    const f1 = document.createElement("th"); f1.className = "grp fill band"; r1.appendChild(f1);

    // row 2 — rack names. Its sticky `top` is measured after render.
    const r2 = t.insertRow(); r2.id = "row-names";
    for (const gr of gs) {
      if (!grpOpen(gr.g)) {
        const th = document.createElement("th");
        th.className = "rk folded";
        const real = gr.racks.filter(r => !isPlaceholder(r)).length;
        th.innerHTML = `<span class="vgrp">${gr.lo+1}–${gr.hi+1}<span class="n">${real}</span></span>`;
        th.title = `Racks ${gr.lo+1}–${gr.hi+1} — ${real} named. Click to expand.`;
        th.addEventListener("click", () => { state.openGrps[gr.g] = true; save(); render(); });
        r2.appendChild(th);
        continue;
      }
      gr.racks.forEach((r, j) => {
        const th = document.createElement("th");
        th.className = "rk" + (isPlaceholder(r) ? " empty" : "") + (j === 0 ? " gstart" : "");
        if (j === 0) th.dataset.g = gr.g;
        th.innerHTML = `<span class="col"><span class="ix">${rackNo(r)}</span>` +
                       `<span class="v">${rackName(r)}</span></span>`;
        th.title = `Rack ${rackNo(r)} · ${rackName(r)}` +
                   (r.in >= 0 ? ` · fed from input ${r.in + 1}` : " · no audio patched")
                   + " — the link follows the rack, not the audio patch";
        r2.appendChild(th);
      });
    }
    const f2 = document.createElement("th"); f2.className = "fill names"; r2.appendChild(f2);

    // body
    for (const f of FAMS) {
      const open = state.openFams[f.k] === true;
      const mapped = Array.from({length:f.n},(_,i)=>state.map[key(f.k,i+1)]).filter(v=>v!==undefined&&v!==null).length;
      const fr = t.insertRow(); fr.className = "fam";
      const fth = document.createElement("th");
      fth.innerHTML = `<span class="exp">${open ? "−" : "+"}</span>${f.label} <span class="mono" style="opacity:.7;font-weight:400;font-size:10px">${mapped}/${f.n}</span>`;
      fth.title = open ? `Collapse ${f.label}` : `Expand ${f.label} — ${mapped} of ${f.n} linked`;
      fth.addEventListener("click", () => { state.openFams[f.k] = !open; save(); render(); });
      fr.appendChild(fth);
      const ftd = document.createElement("td");
      ftd.colSpan = gs.reduce((a,gr)=>a + (grpOpen(gr.g) ? gr.racks.length : 1), 0) + 1;
      fr.appendChild(ftd);
      if (!open) continue;

      for (let n = 1; n <= f.n; n++) {
        const k = key(f.k, n), cur = state.map[k];
        const tr = t.insertRow();
        if (bad.has(k)) tr.className = "conflict";
        const mv = moved.get(k);
        if (mv) tr.classList.add("moved");
        const th = document.createElement("th");
        th.className = "strip";
        th.innerHTML = `<span class="sn">${f.k.toUpperCase()} ${n}</span>`;
        if (mv) th.title = `Linked to "${mv.was}", but rack ${cur + 1} is now ` +
          (mv.now === null ? "gone" : `"${mv.now}"`) + ". The app will not open it until you relink or accept.";
        const inp = document.createElement("input");
        inp.type = "text"; inp.id = `nm-${f.k}-${n}`;
        inp.value = state.names[k] || ""; inp.placeholder = "name";
        inp.setAttribute("aria-label", `Name of ${f.k} ${n}`);
        inp.addEventListener("input", e => { state.names[k] = e.target.value; save(); syncJson(); refreshNameLists(); });
        th.appendChild(inp);
        tr.appendChild(th);

        for (const gr of gs) {
          if (!grpOpen(gr.g)) {
            const td = document.createElement("td");
            td.className = "folded";
            const inside = cur !== undefined && cur !== null && cur >= gr.lo && cur <= gr.hi;
            if (inside) td.innerHTML = `<span class="dot${mv ? " warn" : ""}"></span>`;
            td.title = inside ? `Linked to rack ${cur + 1} (group collapsed)` : "Expand group";
            td.addEventListener("click", () => { state.openGrps[gr.g] = true; save(); render(); });
            tr.appendChild(td);
            continue;
          }
          gr.racks.forEach((r, j) => {
            const td = document.createElement("td");
            const on = cur === r.i;
            td.className = "cell" + (gr.g % 2 ? " alt" : "") + (j === 0 ? " gstart" : "")
                         + (isPlaceholder(r) ? " empty" : "") + (bad.has(k) ? " conflict" : "")
                         + (on && mv ? " moved" : "");
            td.setAttribute("role","button"); td.setAttribute("tabindex","0");
            td.setAttribute("aria-pressed", String(on));
            td.setAttribute("aria-label", `${f.k} ${n} to rack ${rackNo(r)} ${rackName(r)}`);
            td.title = `${f.k.toUpperCase()} ${n} → rack ${rackNo(r)} ${rackName(r)}`;
            td.innerHTML = `<span class="mk"></span>`;
            const toggle = () => {
              if (state.locked) { say("said", "Patch is locked — unlock to edit."); return; }
              if (state.map[k] === r.i) clearLink(k); else setLink(k, r.i);
              save(); render();
            };
            td.addEventListener("click", toggle);
            td.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
            td.addEventListener("mouseenter", () => moveCross(td));
            tr.appendChild(td);
          });
        }
        const fc = document.createElement("td"); fc.className = "fill field"; tr.appendChild(fc);
      }
    }

    placeStickyRows();
    // Rebuilding the table drops the container's scroll; restore it so opening
    // a group leaves everything to its left exactly where it was.
    if (wrap) { wrap.scrollLeft = keepX; wrap.scrollTop = keepY; }
    const mapped = Object.values(state.map).filter(v=>v!==undefined&&v!==null).length;
    document.getElementById("stat-mapped").textContent = mapped;
    document.getElementById("stat-conf").textContent = bad.size;
    document.getElementById("stat-conf-wrap").className = "stat" + (bad.size ? " bad" : "");
    document.getElementById("stat-moved").textContent = moved.size;
    for (const id of ["stat-moved-wrap","btn-relink","btn-accept"])
      document.getElementById(id).hidden = moved.size === 0;
    document.getElementById("rackinfo").textContent = `${rackCount()} racks`;
    refreshNameLists();
    syncJson();
  }

  /* The name row sticks right under the group row. That row's height depends on
     the font, so it is measured — hard-coding it made the name row sit on top
     of the grid. */
  function placeStickyRows(){
    const t = document.getElementById("mx");
    const r1 = t.rows[0], r2 = document.getElementById("row-names");
    if (!r1 || !r2) return;
    const h = r1.getBoundingClientRect().height || 26;
    for (const cell of r2.cells) cell.style.top = h + "px";
  }
  function placeBars(){
    const c = document.getElementById("bar-conn");
    if (c) document.documentElement.style.setProperty("--connh", c.offsetHeight + "px");
    const t = document.getElementById("tabs");
    if (t) document.documentElement.style.setProperty("--tabsh", t.offsetHeight + "px");
  }
  window.addEventListener("resize", () => { placeStickyRows(); placeBars(); });

  /* Tabs. The header stays; everything else is one tab at a time, so the top of
     the window holds the connection and nothing else. */
  function showTab(name){
    for (const b of document.querySelectorAll("#tabs button"))
      b.setAttribute("aria-selected", String(b.dataset.tab === name));
    for (const sec of document.querySelectorAll("section.tab"))
      sec.hidden = sec.id !== "tab-" + name;
    try { localStorage.setItem("wsr-tab", name); } catch(e){}
    if (name === "patch") { render(); placeBars(); }   // was hidden: sizes are stale
    if (name === "activity" && API) refillLog();
  }
  for (const b of document.querySelectorAll("#tabs button"))
    b.addEventListener("click", () => showTab(b.dataset.tab));

  /* ---------------- crosshair ---------------- */
  const crossH = document.getElementById("cross-h"), crossV = document.getElementById("cross-v");
  function moveCross(td){
    const inner = document.getElementById("gridinner");
    const ir = inner.getBoundingClientRect(), cr = td.getBoundingClientRect();
    crossH.style.top = (cr.top - ir.top) + "px";
    crossH.style.height = cr.height + "px";
    crossV.style.left = (cr.left - ir.left) + "px";
    crossV.style.width = cr.width + "px";
    crossH.hidden = crossV.hidden = false;
  }
  document.getElementById("gridwrap").addEventListener("mouseleave", () => {
    crossH.hidden = crossV.hidden = true;
  });

  /* ---------------- zoom ---------------- */
  /* Continuous, not stepped: a pinch should feel like a pinch. --cell carries
     a fractional pixel value and everything in the grid is derived from it. */
  function applyZoom(){
    const px = Math.max(CELL_MIN, Math.min(CELL_MAX, state.cell));
    state.cell = px;
    document.documentElement.style.setProperty("--cell", px.toFixed(2) + "px");
    placeStickyRows();
  }
  function zoomBy(factor, anchor){
    const next = Math.max(CELL_MIN, Math.min(CELL_MAX, state.cell * factor));
    if (Math.abs(next - state.cell) < 0.01) return;
    const wrap = document.getElementById("gridwrap");
    // Keep whatever sits under the pointer under the pointer: convert the
    // anchor to a fraction of the scrollable content, then restore it.
    let fx = 0, fy = 0;
    if (anchor) {
      const r = wrap.getBoundingClientRect();
      fx = (wrap.scrollLeft + (anchor.x - r.left)) / Math.max(1, wrap.scrollWidth);
      fy = (wrap.scrollTop  + (anchor.y - r.top )) / Math.max(1, wrap.scrollHeight);
    }
    state.cell = next; applyZoom();     // not saved: see PERSIST
    if (anchor) {
      const r = wrap.getBoundingClientRect();
      wrap.scrollLeft = fx * wrap.scrollWidth  - (anchor.x - r.left);
      wrap.scrollTop  = fy * wrap.scrollHeight - (anchor.y - r.top);
    }
  }
  /* There are no zoom buttons and no readout: the wheel and the trackpad do it.
     Two fewer things to hit by accident with the patch unlocked. */

  /* Trackpad pinch arrives as a wheel event with ctrlKey set; a mouse wheel
     needs a modifier so plain scrolling still scrolls. Deltas are accumulated
     because a trackpad emits many small ones per gesture. */
  /* WebKit — which is what the app window runs on — reports a trackpad pinch
     as gesturestart/gesturechange with an absolute `scale`, NOT as a wheel
     event with ctrlKey the way Chromium does. Listening only for the latter
     meant the pinch did nothing in the app. Both paths are handled. */
  (function pinchZoom(){
    const wrap = document.getElementById("gridwrap");
    let last = 1;
    wrap.addEventListener("gesturestart", e => { e.preventDefault(); last = e.scale || 1; });
    wrap.addEventListener("gesturechange", e => {
      e.preventDefault();
      const now = e.scale || 1;
      const f = last ? now / last : 1;
      last = now;
      if (f > 0 && Math.abs(f - 1) > 0.001)
        zoomBy(f, { x: e.clientX ?? 0, y: e.clientY ?? 0 });
    });
    wrap.addEventListener("gestureend", e => e.preventDefault());
  })();

  (function wheelZoom(){
    const wrap = document.getElementById("gridwrap");
    wrap.addEventListener("wheel", e => {
      if (!e.ctrlKey && !e.metaKey) return;      // plain scroll stays scroll
      e.preventDefault();
      // Applied on the event itself: each delta is small, so the result is
      // smooth without the indirection of coalescing to an animation frame.
      zoomBy(Math.exp(-e.deltaY * 0.0045), { x: e.clientX, y: e.clientY });
    }, { passive: false });
  })();

  /* ---------------- lock ---------------- */
  function applyLock(){
    const b = document.getElementById("btn-lock");
    b.setAttribute("aria-pressed", String(state.locked));
    b.title = state.locked ? "Patch is protected from edits" : "Patch can be edited — lock it when done";
    document.getElementById("gridwrap").classList.toggle("locked", state.locked);
    for (const id of ["btn-auto","btn-clear"]) document.getElementById(id).disabled = state.locked;
  }
  document.getElementById("btn-lock").addEventListener("click", () => {
    state.locked = !state.locked; save(); applyLock();
  });

  function refreshNameLists(){
    const ls = document.getElementById("nl-strips");
    if (!ls.dataset.built) {
      ls.innerHTML = "";
      for (const f of FAMS) for (let n = 1; n <= f.n; n++) {
        const k = key(f.k,n);
        const row = document.createElement("div"); row.className = "nr";
        row.innerHTML = `<span>${f.k.toUpperCase()} ${n}</span>`;
        const i = document.createElement("input");
        i.type = "text"; i.id = `ln-${f.k}-${n}`; i.value = state.names[k] || "";
        i.setAttribute("aria-label", `Name of ${f.k} ${n}`);
        i.addEventListener("input", e => { state.names[k] = e.target.value; save(); render(); });
        row.appendChild(i); ls.appendChild(row);
      }
      ls.dataset.built = "1";
    } else {
      for (const f of FAMS) for (let n = 1; n <= f.n; n++) {
        const el = document.getElementById(`ln-${f.k}-${n}`);
        const v = state.names[key(f.k,n)] || "";
        if (el && el.value !== v && document.activeElement !== el) el.value = v;
      }
    }
    const lr = document.getElementById("nl-racks");
    if (!lr.dataset.built) {
      lr.innerHTML = "";
      for (const r of RACKS) {
        const row = document.createElement("div"); row.className = "nr";
        row.innerHTML = `<span>${rackNo(r)}</span>`;
        const i = document.createElement("input");
        i.type = "text"; i.id = `rn-${r.i}`; i.value = rackName(r);
        i.setAttribute("aria-label", `Name of rack ${rackNo(r)}`);
        i.addEventListener("input", e => { state.rackNames[r.i] = e.target.value; save(); render(); });
        row.appendChild(i); lr.appendChild(row);
      }
      lr.dataset.built = "1";
    } else {
      for (const r of RACKS) {
        const el = document.getElementById(`rn-${r.i}`);
        if (el && el.value !== rackName(r) && document.activeElement !== el) el.value = rackName(r);
      }
    }
  }

  function syncJson(){}          // the JSON panel is gone; kept as a no-op hook

  function autoByName(){
    if (state.locked) { say("said","Patch is locked — unlock to edit."); return; }
    let hit = 0;
    for (const f of FAMS) {
      const rr = RACK_RANGE[f.k];
      for (let n = 1; n <= f.n; n++) {
        const k = key(f.k,n), want = norm(state.names[k]);
        if (!want) continue;
        let cands = RACKS.filter(r => !isPlaceholder(r) && norm(rackName(r)) === want);
        if (!cands.length) continue;
        // prefer a rack in this family's range: the same name is commonly used
        // for a channel insert and for the bus insert that follows it
        if (rr) { const inside = cands.filter(r => r.i >= rr[0] && r.i <= rr[1]); if (inside.length) cands = inside; }
        setLink(k, cands[0].i); hit++;
      }
    }
    save(); render();
    say("said", hit ? `${hit} strips matched by name.` : "No names matched — fill the names first.");
  }

  function say(id, msg){
    const el = document.getElementById(id); if (!el) return;
    el.textContent = msg;
    setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4500);
  }

  // Copy names across the patch: strip 12 linked to rack 7 takes that rack's
  // name, or gives it its own. The sheet only — Push is what writes to a device.
  function copyNames(dir){
    let n = 0;
    for (const [k, idx] of Object.entries(state.map)) {
      if (idx === undefined || idx === null) continue;
      const r = rackAt(idx);
      if (!r) continue;
      if (dir === "s2r") {
        const v = (state.names[k] || "").trim();
        if (!v || rackName(r) === v) continue;
        state.rackNames[r.i] = v; n++;
      } else {
        const v = (rackName(r) || "").trim();
        if (!v || isPlaceholder(r) || state.names[k] === v) continue;
        state.names[k] = v; n++;
      }
    }
    save(); render();
    say("said-names", n ? `${n} name${n === 1 ? "" : "s"} copied.` : "Nothing to copy.");
  }
  document.getElementById("copy-s2r").addEventListener("click", () => copyNames("s2r"));
  document.getElementById("copy-r2s").addEventListener("click", () => copyNames("r2s"));

  document.getElementById("btn-auto").addEventListener("click", autoByName);
  document.getElementById("btn-relink").addEventListener("click", () => {
    if (state.locked) { say("said","Patch is locked — unlock to edit."); return; }
    let fixed = 0, stuck = 0;
    for (const [k, mv] of movedLinks()) {
      const hits = RACKS.filter(r => r.n === mv.was);
      if (hits.length === 1) { setLink(k, hits[0].i); fixed++; } else stuck++;
    }
    save(); render();
    say("said", `${fixed} relinked` + (stuck ? `, ${stuck} left — no single rack carries the old name` : "") + ".");
  });
  document.getElementById("btn-accept").addEventListener("click", () => {
    if (state.locked) { say("said","Patch is locked — unlock to edit."); return; }
    let kept = 0;
    for (const [k, mv] of movedLinks()) {
      if (mv.now === null) continue;          // rack is gone: nothing to keep
      state.anchors[k] = mv.now; kept++;
    }
    save(); render();
    say("said", `${kept} kept on their current racks.`);
  });
  document.getElementById("btn-clear").addEventListener("click", () => {
    if (state.locked) return;
    state.map = {}; state.anchors = {}; save(); render(); say("said","Patch cleared.");
  });
  // Panels are tabs now, so their headings no longer collapse them.

  /* ---------------- sessions ----------------
     A session is the show: the patch sheet, the names and what each console
     button does. Network settings stay with the machine. Editing writes into
     the open session as it goes, so there is no save button. */
  // A dialog drawn in the page: the window's own prompt() and confirm() do not
  // work here (OK never came back), so everything asks in here.
  function askName(what, current, done, hint){
    const modal = document.getElementById("ask");
    const inp = document.getElementById("ask-name");
    const ok = document.getElementById("ask-ok"), cancel = document.getElementById("ask-cancel");
    document.getElementById("ask-what").textContent = what;
    document.getElementById("ask-hint").textContent = hint || "";
    inp.value = current || "";
    modal.hidden = false; inp.focus(); inp.select();
    const close = () => {
      modal.hidden = true; ok.onclick = null; cancel.onclick = null;
      inp.onkeydown = null; modal.onmousedown = null;
    };
    ok.onclick = () => { const v = inp.value.trim(); close(); if (v) done(v); };
    cancel.onclick = close;
    modal.onmousedown = e => { if (e.target === modal) close(); };   // click outside
    inp.onkeydown = e => {
      if (e.key === "Enter") ok.onclick();
      if (e.key === "Escape") { e.stopPropagation(); close(); }
    };
  }
  const saidSess = m => document.getElementById("said-sess").textContent = m || "";

  /* Anything that replaces what is on screen asks first, when the open session
     has changes that are not in its file. */
  function askUnsaved(what, onGo){
    if (!sessState.dirty) { onGo(); return; }
    const modal = document.getElementById("ask2");
    const save = document.getElementById("ask2-save"),
          discard = document.getElementById("ask2-discard"),
          cancel = document.getElementById("ask2-cancel");
    const named = !!sessState.current;
    document.getElementById("ask2-hint").textContent = named
      ? `"${sessState.current}" has changes that are not saved. ${what}`
      : `What is on screen is not saved in any session. ${what}`;
    save.textContent = named ? "Save" : "Save as…";
    modal.hidden = false;
    const close = () => {
      modal.hidden = true; save.onclick = null; discard.onclick = null;
      cancel.onclick = null; modal.onmousedown = null;
    };
    save.onclick = async () => {
      close();
      if (named) {
        const r = await API.save_session();
        if (!r.ok) { saidSess(r.msg); return; }
        fillSessions(r); onGo();
      } else {
        askName("Save this as", "", async name => {
          const r = await API.save_session_as(name);
          if (!r.ok) { saidSess(r.msg); return; }
          fillSessions(r); onGo();
        });
      }
    };
    discard.onclick = () => { close(); onGo(); };
    cancel.onclick = close;
    modal.onmousedown = e => { if (e.target === modal) close(); };
    save.focus();
  }
  let sessState = { sessions: [], current: "", dirty: false };
  let sessSel = "";                       // the row the buttons act on
  const when = t => t ? new Date(t * 1000).toLocaleString() : "not saved yet";
  function fillSessions(r){
    if (!r || !r.sessions) return;
    sessState = r;
    const box = document.getElementById("sesslist");
    box.innerHTML = "";
    if (!r.sessions.length) {
      box.innerHTML = `<p class="empty">No sessions yet. <b>Save as</b> keeps what is on screen as one.</p>`;
    }
    if (!r.sessions.some(x => x.name === sessSel)) sessSel = r.current || "";
    for (const it of r.sessions) {
      const on = it.name === r.current;
      const row = document.createElement("div");
      row.className = "sr" + (on ? " on" : "") + (it.name === sessSel ? " sel" : "");
      row.tabIndex = 0;
      const nm = document.createElement("span"); nm.className = "nm";
      nm.textContent = it.name + (on && r.dirty ? " •" : "");
      const tag = document.createElement("span"); tag.className = "open";
      tag.textContent = on ? "open" : "";
      const w = document.createElement("span"); w.className = "when"; w.textContent = when(it.saved);
      const pick = () => { sessSel = it.name; fillSessions(sessState); };
      row.addEventListener("click", pick);
      row.addEventListener("dblclick", () => loadSession(it.name));
      row.addEventListener("keydown", e => { if (e.key === "Enter") loadSession(it.name); });
      row.append(nm, tag, w);
      box.appendChild(row);
    }
    for (const id of ["sess-new","sess-saveas"]) document.getElementById(id).disabled = !API;
    // Load, Rename and Delete act on the selected row; Save on the open session.
    for (const id of ["sess-load","sess-rename","sess-del"])
      document.getElementById(id).disabled = !API || !sessSel;
    document.getElementById("sess-load").disabled = !API || !sessSel || sessSel === r.current;
    const sv = document.getElementById("sess-save");
    sv.disabled = !API || !r.current;
    sv.textContent = r.dirty ? "Save •" : "Save";
    const del = document.getElementById("sess-del");
    if (del.dataset.armed !== "1") del.textContent = "Delete";
  }
  function markDirty(){
    if (!sessState.current || sessState.dirty) return;
    sessState.dirty = true;
    fillSessions(sessState);
  }
  function loadSession(name){
    askUnsaved(`Loading "${name}" replaces what is on screen.`, async () => {
      const r = await API.load_session(name);
      if (!r.ok) { saidSess(r.msg); return; }
      sessSel = r.current; fillSessions(r); applyCfg(r.cfg);
      saidSess(`Session "${r.current}" loaded.`);
    });
  }

  function applyCfg(cfg){
    if (!cfg) return;
    state.map = cfg.map || {}; state.anchors = cfg.anchors || {};
    state.names = cfg.names || {}; state.rackNames = cfg.rackNames || {};
    btnState = { buttons: cfg.buttons || {}, pending: cfg.buttonsPending || [], learning: null };
    ensureAnchors(); save(); render(); renderButtons();
  }
  function wireSessions(){
    document.getElementById("sess-save").addEventListener("click", async () => {
      const r = await API.save_session();
      saidSess(r.ok ? `Session "${r.current}" saved.` : r.msg); if (r.ok) fillSessions(r);
    });
    document.getElementById("sess-new").addEventListener("click", () =>
      askUnsaved("A new session starts from an empty sheet.", () =>
        askName("New session", "", async name => {
          const r = await API.new_session(name);
          if (!r.ok) { saidSess(r.msg); return; }
          sessSel = r.current; fillSessions(r); applyCfg(r.cfg);
          saidSess(`Session "${r.current}" started — the sheet is empty.`);
        })));
    document.getElementById("sess-load").addEventListener("click", () => {
      if (sessSel) loadSession(sessSel);
    });
    document.getElementById("sess-rename").addEventListener("click", () => {
      if (!sessSel) return;
      askName("Rename to", sessSel, async name => {
        const r = await API.rename_session(name, sessSel);
        saidSess(r.ok ? `Renamed to "${name}".` : r.msg);
        if (r.ok) { sessSel = name; fillSessions(r); }
      });
    });
    document.getElementById("sess-del").addEventListener("click", () => {
      if (!sessSel) return;
      const b = document.getElementById("sess-del");
      if (b.dataset.armed !== "1") {                  // two steps, as with Push
        b.dataset.armed = "1"; b.textContent = "Delete?";
        saidSess(`This deletes "${sessSel}". Click again to confirm.`);
        clearTimeout(b._t);
        b._t = setTimeout(() => { b.dataset.armed = ""; b.textContent = "Delete"; saidSess(""); }, 5000);
        return;
      }
      clearTimeout(b._t); b.dataset.armed = "";
      const name = sessSel;
      API.delete_session(name).then(r => {
        saidSess(r.ok ? `"${name}" deleted — what is on screen is kept.` : r.msg);
        if (r.ok) { sessSel = ""; fillSessions(r); }
      });
    });
    document.getElementById("sess-saveas").addEventListener("click", () =>
      askName("Save this as", sessState.current, async name => {
        const r = await API.save_session_as(name);
        saidSess(r.ok ? `Saved as "${r.current}".` : r.msg); if (r.ok) fillSessions(r);
      }));
  }

  /* ---------------- app bridge ----------------
     The same page is the app window and a standalone page. Inside the app,
     window.pywebview.api reaches Python. Outside it everything else still works. */
  let API = null;

  function applyStatus(st){
    if (!st) return;
    if (typeof st.follow === "boolean") setFollowUI(st.follow);
    const w = document.getElementById("live-waves"), g = document.getElementById("live-wing");
    showHealth(st.waves.connected ? st.waves.health : null);
    w.className = "live" + (st.waves.connected ? " on" : "");
    w.title = st.waves.connected ? `connected to ${st.waves.peer}` : "waiting for Assign in SuperRack";
    w.lastChild.nodeValue = st.waves.connected ? `SuperRack ${st.waves.racks}` : "SuperRack";
    g.className = "live" + (st.wing.connected ? " on" : (st.wing.probing ? " probing" : ""));
    g.title = st.wing.connected ? `answering — ${st.wing.host}`
            : (st.wing.probing ? `probing ${st.wing.host} — no answer` : "WING not configured");
    // The button reflects what it will do next: with a session open (answering
    // or merely probing) the useful action is to drop it.
    const cb = document.getElementById("btn-connect");
    const live = st.wing.connected || st.wing.probing;
    cb.classList.toggle("tog", live);      // the label follows aria-pressed, in CSS
    cb.setAttribute("aria-pressed", String(live));
    cb.title = live ? "Stop talking to the WING" : "Start talking to the WING";
  }

  function setFollowUI(on){
    // The label itself is in the page, both states at once; the attribute picks
    // which one shows. See button.engine .swap in app.css.
    document.getElementById("follow").setAttribute("aria-pressed", String(on));
  }

  const BTN_ACTIONS = [["plugin-next","Next plugin"],["plugin-prev","Previous plugin"],
                       ["rack-next","Next rack"],["rack-prev","Previous rack"]];
  for (let n = 1; n <= 16; n++) BTN_ACTIONS.push([`uk${n}`, `USER KEY ${n}`]);
  let ukNames = {};                 // SuperRack USER KEY number -> name, from the session
  let btnState = { buttons:{}, learning:null };
  function btnLabel(k){
    if (!k) return "not set";
    const [layer, n, row] = k.split("/");
    const page = /^U\d+$/.test(layer) ? `USER ${layer}` : `Custom page ${layer}`;
    return `${page} · button ${n} · ${row === "bu" ? "upper" : "lower"}`;
  }
  let consoleBtns = null;            // last read of the console, or null
  let btnErr = {};                   // action -> last error message
  async function scanButtons(){
    const said = document.getElementById("said-btns");
    if (!API) return;
    said.textContent = "Reading buttons from the WING…";
    const r = await API.scan_buttons();
    if (!r.ok) { said.textContent = r.msg; consoleBtns = null; renderButtons(); return; }
    consoleBtns = r.buttons;
    said.textContent = "";
    renderButtons();
  }
  // Buttons are named as the console names them: USER 1-16 across banks U1-U4,
  // and the two GPIO buttons.
  const shortKey = k => {
    const [layer, n, row] = k.split("/");
    if (/^U\d+$/.test(layer)) return `USER ${(Number(layer.slice(1)) - 1) * 4 + Number(n)}`;
    if (layer === "gpio") return `GPIO ${n}`;
    return `${layer} · ${n} ${row === "bu" ? "top" : "bottom"}`;
  };
  function actionLabel(a){
    const named = BTN_ACTIONS.find(([k]) => k === a);
    const ukn = a && a.startsWith("uk") ? a.slice(2) : null;
    if (ukn) return `USER KEY ${ukn}` + (ukNames[ukn] ? ` — ${ukNames[ukn]}` : "");
    return named ? named[1] : a;
  }
  function renderButtons(){
    const box = document.getElementById("btnmap");
    if (!box) return;
    box.innerHTML = "";
    const pendingKeys = new Set(btnState.pending || []);
    const byKey = {};                       // WING button key -> action
    for (const [a, k] of Object.entries(btnState.buttons)) byKey[k] = a;
    // The 16 USER buttons are fixed hardware, so the rows are always shown —
    // read from the console when it answers, from their known keys when not.
    const KEYS = [];
    for (let b = 1; b <= 4; b++) for (let n = 1; n <= 4; n++) KEYS.push(`U${b}/${n}/bu`);
    const read = new Map((consoleBtns || []).map(b => [b.key, b]));
    const buttons = KEYS.map(k => read.get(k) || { key: k, mode: "", fname: "", name: "" });
    for (const b of buttons) {
      const mine = byKey[b.key] || "";
      const nm = document.createElement("span"); nm.className = "nm";
      nm.textContent = shortKey(b.key);
      if (mine && pendingKeys.has(b.key)) {
        const sm = document.createElement("small");
        sm.textContent = "waiting for the WING";
        nm.appendChild(sm);
      } else if (b.mode && b.mode !== "OFF" && !mine) {
        const sm = document.createElement("small");
        sm.textContent = "in use: " + (b.name || b.fname || b.mode).replace(/^\|/, "");
        nm.appendChild(sm);
      }
      const sel = document.createElement("select");
      sel.setAttribute("aria-label", `What ${shortKey(b.key)} does`);
      const taken = new Set(Object.keys(btnState.buttons).filter(a => a !== mine));
      const opts = [`<option value="">— nothing —</option>`];
      for (const [a, label] of BTN_ACTIONS) {
        if (taken.has(a)) continue;          // one action, one button
        opts.push(`<option value="${a}"${a === mine ? " selected" : ""}>${actionLabel(a)}</option>`);
      }
      sel.innerHTML = opts.join("");
      sel.disabled = !API;
      // Offline choices are kept and written to the console when it connects.
      if (!consoleBtns) sel.title = "The WING is not answering — this is applied when it connects";
      sel.addEventListener("change", async () => {
        sel.disabled = true;
        delete btnErr[b.key];
        let r;
        if (!sel.value) r = await API.release_button(mine);
        else {
          if (mine) await API.release_button(mine);
          r = await API.assign_button(sel.value, b.key);
        }
        if (!r.ok && r.inUse) { btnErr[b.key] = { msg: r.msg, action: sel.value, key: b.key }; renderButtons(); return; }
        if (!r.ok) btnErr[b.key] = r.msg;
        else {
          btnState.buttons = r.buttons;
          const p = new Set(btnState.pending || []);
          if (r.pending) p.add(b.key); else p.delete(b.key);
          btnState.pending = [...p];
        }
        await scanButtons();
        renderButtons();
      });
      let extra = document.createElement("span");
      const ukn = mine && mine.startsWith("uk") ? mine.slice(2) : null;
      if (ukn) {
        extra = document.createElement("button"); extra.type = "button";
        extra.textContent = "Send";
        extra.title = "Fire this USER KEY now — use it for SuperRack's MIDI Learn";
        extra.disabled = !API;
        extra.addEventListener("click", async () => {
          const r = await API.press_user_key(Number(ukn));
          if (!r.ok) { btnErr[b.key] = r.msg; renderButtons(); }
        });
      }
      box.append(nm, sel, extra);
      const err = btnErr[b.key];
      if (err) {
        const e = document.createElement("span"); e.className = "err";
        e.textContent = typeof err === "string" ? err : err.msg + " ";
        if (typeof err !== "string") {
          const yes = document.createElement("button"); yes.type = "button"; yes.textContent = "Replace";
          const no = document.createElement("button"); no.type = "button"; no.textContent = "Cancel";
          yes.addEventListener("click", async () => {
            delete btnErr[b.key];
            const r = await API.assign_button(err.action, err.key, true);
            if (!r.ok) btnErr[b.key] = r.msg; else btnState.buttons = r.buttons;
            await scanButtons();
          });
          no.addEventListener("click", () => { delete btnErr[b.key]; renderButtons(); });
          e.append(yes, " ", no);
        }
        box.append(e);
      }
    }
  }

  window.onBridgeEvent = function(kind, payload){
    if (kind === "status") applyStatus(payload);
    else if (kind === "racks") replaceRacks(payload);
    else if (kind === "selection") flashStrip(payload.fam, payload.n);
    else if (kind === "log") pushLog(payload);
    else if (kind === "health") showHealth(payload);
    else if (kind === "buttons") { btnState = payload; renderButtons(); }
    else if (kind === "userkeys") { ukNames = payload || {}; renderButtons(); }
  };

  function showHealth(h){
    const el = document.getElementById("health");
    if (!h || !Object.keys(h).length) { el.hidden = true; return; }
    const bits = [];
    if (typeof h.sampleRate === "number") bits.push(`${(h.sampleRate/1000).toFixed(h.sampleRate % 1000 ? 1 : 0)} kHz`);
    if (typeof h.cpu === "number") bits.push(h.cpu >= 80 ? `<span class="bad">CPU ${h.cpu}%</span>` : `CPU ${h.cpu}%`);
    if (h.ioBox === false) bits.push(`<span class="bad" title="SuperRack reports its I/O box as down">I/O down</span>`);
    if (h.sgs === false) bits.push(`<span class="bad" title="SoundGrid server not ready">SGS down</span>`);
    if (typeof h.snapshot === "number") bits.push(h.snapshot < 0 ? "no snapshot" : `snapshot ${h.snapshot + 1}`);
    if (h.sessionDirty === true) bits.push(`<span title="The SuperRack session has changes not saved yet">unsaved</span>`);
    el.innerHTML = "· " + bits.join(" · ");
    el.hidden = !bits.length;
  }

  function replaceRacks(list){
    if (!Array.isArray(list) || !list.length) return;
    RACKS.length = 0;
    for (const r of list) RACKS.push({ i:r.index, n:r.name, s:r.stereo?1:0, in:r.input });
    ensureAnchors();     // fills missing anchors only; a real divergence stays visible
    document.getElementById("nl-racks").dataset.built = "";
    render();      // rack count follows the inventory SuperRack sent
  }
  function flashStrip(fam, n){
    const el = document.getElementById(`nm-${fam}-${n}`); if (!el) return;
    const th = el.closest("th"); if (!th) return;
    th.classList.add("hot");
    th.scrollIntoView({ block:"nearest", behavior:"smooth" });
    setTimeout(() => th.classList.remove("hot"), 900);
  }
  // Fill the log from the app, in case the panel was built after the lines came.
  async function refillLog(){
    const box = document.getElementById("applog");
    if (!box) return;
    try {
      const st = await API.get_state();
      if (st && st.logs) box.textContent = st.logs.join("\n");
      box.scrollTop = box.scrollHeight;
    } catch(e){}
  }

  function pushLog(line){
    const box = document.getElementById("applog"); if (!box) return;
    box.textContent = (box.textContent + "\n" + line).split("\n").slice(-60).join("\n");
    box.scrollTop = box.scrollHeight;
  }

  async function bootApp(){
    API = window.pywebview.api;
    for (const id of ["follow","iface","btn-scan","btn-connect","btn-adv",
                      "pull-wing","push-wing","pull-waves","push-waves"])
      document.getElementById(id).disabled = false;
    document.getElementById("follow").removeAttribute("title");
    document.getElementById("hint-names").textContent =
      "Pull reads names from that device. Push writes them to it — which changes the console, or the SuperRack session.";

    const log = document.createElement("div");
    log.className = "applog"; log.id = "applog";
    document.getElementById("p-log").querySelector(".body").appendChild(log);

    const st = await API.get_state();
    if (st.cfg) {
      if (st.cfg.map && Object.keys(st.cfg.map).length) state.map = st.cfg.map;
      if (st.cfg.anchors) state.anchors = st.cfg.anchors;
      if (st.cfg.names) state.names = st.cfg.names;
      if (st.cfg.rackNames) state.rackNames = st.cfg.rackNames;
      document.getElementById("winghost").value = st.cfg.wingHost || "";
    }
    // One version string, from the package. Anyone reporting a problem from a
    // show can read it off the Help tab without hunting for a file.
    const about = document.getElementById("about-version");
    if (about && st.version) about.textContent = `Kite ${st.version}`;
    if (st.racks && st.racks.length) replaceRacks(st.racks); else render();
    applyStatus(st.status);
    (st.logs || []).forEach(pushLog);
    ukNames = st.userKeys || {};
    if (st.midi && st.midi.error)
      document.getElementById("said-midi").textContent = st.midi.error;
    else if (st.midi && st.midi.open)
      document.getElementById("said-midi").textContent = `MIDI port: ${st.midi.port}`;
    btnState = { buttons: (st.cfg && st.cfg.buttons) || {},
                 pending: (st.cfg && st.cfg.buttonsPending) || [], learning: null };
    renderButtons();
    wireSessions();
    fillSessions(await API.list_sessions());

    const mb = document.getElementById("btn-mrrc");
    mb.disabled = false;
    mb.addEventListener("click", async () => {
      const r = await API.export_midi_map();
      document.getElementById("said-midi").textContent =
        r.ok ? `${r.count} commands written to ${r.path} — import it in SuperRack's MIDI Controller.` : r.msg;
    });

    // Read the console whenever the USER keys tab is opened.
    document.querySelector('#tabs button[data-tab="keys"]').addEventListener("click", scanButtons);
    if (document.querySelector('#tabs button[data-tab="keys"]').getAttribute("aria-selected") === "true")
      scanButtons();

    const sel = document.getElementById("iface");
    // Interfaces are chosen by NAME. IPs (and the MACs behind them) change when
    // the machine joins another network, so they are shown only to recognise.
    async function fillIfaces(){
      const keep = sel.value || (st.cfg && st.cfg.iface) || "";
      const ifaces = await API.list_interfaces();
      const opts = [`<option value="">Automatic — all interfaces</option>`];
      for (const i of ifaces) {
        const tag = i.loopback ? " (this machine)" : i.linklocal ? " (no DHCP)" : !i.up ? " (down)" : "";
        opts.push(`<option value="${i.name}">${i.name} — ${i.ip}${tag}</option>`);
      }
      // A saved interface that is gone right now stays selectable and visible.
      if (keep && !ifaces.some(i => i.name === keep))
        opts.push(`<option value="${keep}">${keep} — not present</option>`);
      sel.innerHTML = opts.join("");
      sel.value = keep;
    }
    await fillIfaces();
    sel.addEventListener("focus", fillIfaces);
    sel.addEventListener("change", async () => {
      const r = await API.set_network({ iface: sel.value });
      say("said-conn", r.ok ? `Using ${sel.value || "all interfaces"}.` : r.error);
    });

    const net = await API.get_network();
    document.getElementById("pl-port").value = net.prolinkPort;
    document.getElementById("pl-name").value = net.consoleName;
    const advBtn = document.getElementById("btn-adv"), adv = document.getElementById("adv");
    advBtn.addEventListener("click", () => {
      adv.hidden = !adv.hidden;
      advBtn.setAttribute("aria-expanded", String(!adv.hidden));
      placeBars();
    });
    document.getElementById("btn-adv-apply").addEventListener("click", async () => {
      const r = await API.set_network({
        prolinkPort: document.getElementById("pl-port").value.trim(),
        consoleName: document.getElementById("pl-name").value.trim(),
      });
      if (r.ok) {
        document.getElementById("pl-port").value = r.network.prolinkPort;
        document.getElementById("pl-name").value = r.network.consoleName;
        say("said-conn", "Applied — SuperRack should reconnect by itself.");
      } else say("said-conn", r.error);
    });

    const origSave = save;
    save = function(){
      origSave();
      API.save_mapping({ map:state.map, anchors:state.anchors,
                         names:state.names, rackNames:state.rackNames });
      markDirty();
    };

    const fw = document.getElementById("follow");
    fw.addEventListener("click", async () => {
      const next = fw.getAttribute("aria-pressed") !== "true";
      setFollowUI(next);                       // answer the click at once
      applyStatus(await API.set_follow(next));
    });

    document.getElementById("btn-connect").addEventListener("click", async () => {
      const cb = document.getElementById("btn-connect");
      const disconnecting = cb.getAttribute("aria-pressed") === "true";
      // Disconnecting is connect_wing(""), which stops the client and clears the host.
      const host = disconnecting ? "" : document.getElementById("winghost").value.trim();
      applyStatus(await API.connect_wing(host));
      say("said-conn", disconnecting ? "Disconnected." : (host ? "" : "Enter an address first."));
    });
    document.getElementById("btn-scan").addEventListener("click", async () => {
      const b = document.getElementById("btn-scan");
      b.disabled = true; say("said-conn", "scanning…");
      const r = await API.scan_wing(sel.value);
      b.disabled = false;
      const box = document.getElementById("found");
      if (r.error) { say("said-conn", r.error); box.hidden = true; return; }
      if (!r.found.length) { say("said-conn", `nothing found on ${r.network}`); box.hidden = true; return; }
      box.hidden = false; box.innerHTML = "";
      for (const d of r.found) {
        const b2 = document.createElement("button");
        b2.type = "button"; b2.textContent = `${d.ip}  ·  ${d.name}`;
        b2.addEventListener("click", async () => {
          document.getElementById("winghost").value = d.ip;
          applyStatus(await API.connect_wing(d.ip));
          box.hidden = true;
        });
        box.appendChild(b2);
      }
      say("said-conn", `${r.found.length} found`);
    });
    // A list of addresses left hanging over the header is just clutter: any
    // click outside it puts it away.
    document.addEventListener("click", e => {
      const box = document.getElementById("found");
      if (!box.hidden && !box.contains(e.target) && e.target.id !== "btn-scan")
        box.hidden = true;
    });
    async function doPull(source){
      const r = await API.pull_names(source);
      Object.assign(state.names, r.names || {});
      Object.assign(state.rackNames, r.rackNames || {});
      save(); render();
      const n = source === "wing" ? `${Object.keys(r.names||{}).length} strips`
                                  : `${Object.keys(r.rackNames||{}).length} racks`;
      say("said-names", (r.errors && r.errors.length ? r.errors.join("; ") + " — " : "") + n + " read.");
    }
    async function doPush(target){
      const what = target === "wing" ? "strip names to the WING"
                                     : "rack names to SuperRack, changing the session";
      // Two-step confirm inside the page: the browser confirm() dialog is not
      // reliable in the macOS webview (OK there did not proceed).
      const btn = document.getElementById("push-" + target);
      if (btn.dataset.armed !== "1") {
        btn.dataset.armed = "1";
        btn.dataset.label = btn.textContent;
        btn.textContent = "Click again to write";
        btn.classList.add("armed");
        say("said-names", `This writes ${what}. Click again within 5 s to confirm.`);
        clearTimeout(btn._disarm);
        btn._disarm = setTimeout(() => {
          btn.dataset.armed = ""; btn.textContent = btn.dataset.label;
          btn.classList.remove("armed"); say("said-names", "Push cancelled.");
        }, 5000);
        return;
      }
      clearTimeout(btn._disarm);
      btn.dataset.armed = ""; btn.textContent = btn.dataset.label; btn.classList.remove("armed");
      say("said-names", "writing…");
      const r = await API.push_names({ names: state.names, rackNames: state.rackNames }, target);
      say("said-names", (target === "wing" ? `${r.wing} strips` : `${r.waves} racks`) + " written" +
        (r.sources ? ` (${r.sources} via the input source name, as those strips use it)` : "") + "." +
        (r.errors && r.errors.length ? " Errors: " + r.errors.slice(0,3).join("; ") : ""));
    }
    document.getElementById("pull-wing").addEventListener("click", () => doPull("wing"));
    document.getElementById("pull-waves").addEventListener("click", () => doPull("waves"));
    document.getElementById("push-wing").addEventListener("click", () => doPush("wing"));
    document.getElementById("push-waves").addEventListener("click", () => doPush("waves"));
  }
  window.addEventListener("pywebviewready", bootApp);

  restore();
  if (!(window.pywebview && window.pywebview.api)) {
    // Standalone page: nothing to drive, so do not imply it is live.
    const b = document.getElementById("follow");
    b.disabled = true;
    b.title = "Only active inside the application";
  }
  state.locked = true;               // always start protected
  if (!Object.keys(state.map).length) {
    for (const [famKey, rr] of Object.entries(RACK_RANGE)) {
      const f = FAMS.find(x => x.k === famKey);
      for (let n = 1; n <= f.n; n++) {
        const r = RACKS[rr[0] + n - 1];
        if (r && !isPlaceholder(r)) {
          setLink(key(famKey,n), r.i);
          if (!state.names[key(famKey,n)]) state.names[key(famKey,n)] = r.n;
        }
      }
    }
  }
  ensureAnchors();
  applyZoom();
  applyLock();
  render();
  placeBars();
  try { showTab(localStorage.getItem("wsr-tab") || "patch"); } catch(e){ showTab("patch"); }

