"use strict";
// Dropspots: where teams landed in a tournament, for the teams that qualified and for everyone.
// Landing rows are loaded by the owner (docs/dropspots-data.md); this page only reads them.
const DR = { wid: null, info: null, grid: null, hot: null, area: null, top: 100, game: 0, mode: "move", z: 1, ox: 0, oy: 0, poly: null, draft: null, hover: null,
  layers: { q: true, all: true, chests: true }, loot: null, areas: null, mark: null, blur: 5, alpha: 0.9, img: null, imgUrl: "", heat: {}, S: 700, sortBy: "landings", fq: "", freg: "" };
const MODES = [["move", "Move"], ["box", "Box"], ["draw", "Draw"]];

async function dropsPage(wid) {
  DR.wid = wid || null; DR.info = DR.grid = DR.hot = DR.area = DR.poly = null; DR.z = 1; DR.ox = DR.oy = 0; DR.heat = {}; DR.game = 0; DR.loot = DR.areas = DR.mark = null;
  const [avail, all] = await Promise.all([j("/api/drops/events"), allWindows()]);
  DR.avail = avail && !avail.error ? avail : {};
  DR.events = all.filter(w => w.status === "finished" || ACTIVE.includes(w.status)).map(w => ({ ...w, n: (DR.avail[w.window_id] || {}).landings || 0 }))
    .sort((a, b) => (b.n > 0) - (a.n > 0) || b.end - a.end);
  const withData = Object.keys(DR.avail).length;
  app.innerHTML = `<div class="ph"><div><h1>Dropspots</h1><p>Where teams landed in a tournament: the teams that qualified against everyone else. Pick a tournament, then draw any area on the map to see who landed there and how it went.</p></div></div>
    <div class="dr-layout ${wid ? "picked" : ""}"><div class="card dr-pick"><div class="hd"><h2>Tournament</h2><span class="sub">${withData} with landing data</span><button class="chip" id="dpickx" style="display:none">Hide list</button></div>
      <input id="dq" placeholder="Search name, region, gamemode…" value="${esc(DR.fq)}">
      <div class="chips" style="margin:8px 0" id="dreg">${["", ...REGIONS].map(r => `<button class="chip ${r === DR.freg ? "on" : ""}" data-r="${r}">${r || "All"}</button>`).join("")}</div>
      <div class="dr-list" id="dlist"></div></div>
    <div id="dtool" class="dr-main"></div></div>`;
  $("#dq").oninput = e => { DR.fq = e.target.value; drawList(); };
  $$("#dreg button").forEach(b => b.onclick = () => { DR.freg = b.dataset.r; $$("#dreg button").forEach(x => x.classList.toggle("on", x === b)); drawList(); });
  drawList();
  const L = $(".dr-layout"), toggle = () => { const o = L.classList.toggle("open"); $("#dpickx").style.display = o ? "" : "none"; };
  if (wid) {
    const cur = DR.events.find(w => w.window_id === wid);
    $(".dr-pick .hd h2").innerHTML = `<span class="mut" style="font-weight:500">Tournament:</span> ${cur ? esc(cur.name) + " · " + esc(cur.region) : ""}`;
    $("#dpickx").onclick = toggle;
    $(".dr-pick .hd").onclick = e => { if (e.target.id !== "dpickx" && !L.classList.contains("open")) toggle(); };
    const hint = document.createElement("small"); hint.className = "mut"; hint.id = "dchg"; hint.textContent = "change"; $(".dr-pick .hd .sub").after(hint);
  }
  if (wid) await loadDrops(wid); else $("#dtool").innerHTML = `<div class="card empty">Choose a tournament on the left.<br><small>Tournaments with landing data are listed first.</small></div>`;
}
function drawList() {
  const l = DR.events.filter(w => (!DR.freg || w.region === DR.freg) && (!DR.fq || matches(w, DR.fq))).slice(0, 80);
  $("#dlist").innerHTML = l.map(w => `<a href="#/drops/${encodeURIComponent(w.window_id)}" data-art="${esc(w.window_id)}" data-fam="${esc(w.family)}" class="dr-item ${w.window_id === DR.wid ? "on" : ""}"><b>${esc(w.name)}</b><small>${esc(w.region)} · ${esc(gm(w.category))} · ${fmt(w.end)}</small><small class="${w.n ? "ok" : "mut"}">${w.n ? nf(w.n) + " landings" : "no landing data"}</small></a>`).join("") || '<p class="mut">No tournament matches.</p>';
}

async function loadDrops(wid) {
  const tool = $("#dtool"); tool.innerHTML = skel(2, 120);
  const info = await j("/api/drops/info?window=" + encodeURIComponent(wid));
  if (info.error) { tool.innerHTML = `<div class="card err">${esc(info.error)}</div>`; return; }
  DR.info = info; DR.top = info.goal ? info.goal.rank : 100;
  tool.innerHTML = info.landings ? `<div id="dcontrols"></div><div id="dmap"></div><div id="dloot"></div>${infoCard(info)}` : infoCard(info) + noData(info);
  if (!info.landings) return;
  DR.imgUrl = info.map && info.map.image || ""; DR.img = null; DR.base = null;
  if (DR.imgUrl) { const im = new Image(); im.onload = () => { DR.img = info.map.fit ? warp(im, info.map.fit) : im; draw(); }; im.src = DR.imgUrl; }
  await refresh(true);
}
// A raw map texture from the game files, put into the 0-1 frame of the landings: turned k quarter turns counter-clockwise,
// L frames wide, centred on (cx, cy). The sea around it takes the colour of the picture's corner.
function warp(im, f) {
  const S = 1600, c = document.createElement("canvas"); c.width = c.height = S;
  const x = c.getContext("2d"), t = document.createElement("canvas"); t.width = t.height = 1; const tx = t.getContext("2d");
  tx.drawImage(im, 0, 0, 8, 8, 0, 0, 1, 1); const p = tx.getImageData(0, 0, 1, 1).data; x.fillStyle = `rgb(${p[0]},${p[1]},${p[2]})`; x.fillRect(0, 0, S, S);
  x.imageSmoothingQuality = "high"; x.translate(f.cx * S, f.cy * S); x.rotate(-f.k * Math.PI / 2);
  x.drawImage(im, -f.L * S / 2, -f.L * S / 2, f.L * S, f.L * S);
  return c;
}
function infoCard(i) {
  const m = i.map;
  return `<div class="card"><div class="hd"><h2>${esc(i.name)} <span class="pill">${esc(i.region)}</span></h2><span class="sub">${fmt(i.begin)}</span></div>
    <div class="kpis" style="margin:0"><div class="kpi"><div class="l">Map</div><div class="v" style="font-size:1.1rem">${esc(m && m.name ? m.name : i.label)}</div><div class="d">${m && m.credit ? esc(m.credit) : i.note ? esc(i.note) : ""}${i.map_check && i.map_check.status === "mismatch" ? `<br><span class="err">⚠ The saved picture does not match where teams landed (${pc(i.map_check.on_land, 0)} on land), so it is hidden. This event may use a different map.</span>` : ""}</div></div>
      <div class="kpi"><div class="l">Playlist</div><div class="v" style="font-size:.95rem;word-break:break-all">${esc(i.playlist || "unknown")}</div><div class="d">${i.codename ? "codename " + esc(i.codename) + " · " : ""}${i.build ? "builds on" : "zero build"} · ${esc(i.mode || "")}</div></div>
      <div class="kpi"><div class="l">Format</div><div class="v" style="font-size:1.1rem">${i.match_cap || "?"} games</div><div class="d">${i.goal ? "goal: top " + nf(i.goal.rank) + " (" + esc(i.goal.kind) + ")" : "no single goal"}</div></div>
      <div class="kpi"><div class="l">Landing data</div><div class="v" style="font-size:1.1rem">${i.landings ? nf(i.landings) + " landings" : "none yet"}</div><div class="d">${i.landings ? i.games + " game" + (i.games === 1 ? "" : "s") + " recorded" : "loads after the event ends"}</div></div></div></div>`;
}
const noData = i => `<div class="card"><div class="hd"><h2>No landing data for this tournament yet</h2></div>
  <p>Landings are read from the match replays of recent tournaments. They are loaded automatically a few hours after an event ends and only for events from roughly the last nine days, because Epic deletes replays after one to two weeks. ${i.final ? "Older events cannot be loaded." : "This event has not finished yet."} Once landings are loaded you get heatmaps of everyone and of the teams that qualified, and you can draw any area on the map.</p>
  <details><summary class="small" style="cursor:pointer">Owner: how to load it</summary>
  <p class="small">Send one row per team per game to <code>POST /api/admin/drops</code> with your admin key, or run <code>python scripts/import_drops.py landings.json</code>. Rows look like this:</p>
  <pre class="small">{ "window_id": "${esc(i.window_id)}", "coords": "unit",
  "map": { "name": "…", "image": "https://…", "pois": [{ "name": "Tilted", "x": 0.41, "y": 0.62 }] },
  "drops": [{ "game": 1, "team": "acct+acct", "x": 0.41, "y": 0.62, "poi": "Tilted", "placement": 7, "points": 23, "rank": 120 }] }</pre>
  <p class="small">x and y run from 0 to 1 across the map image (top-left is 0,0), or send game coordinates with bounds. Full format: <code>docs/dropspots-data.md</code>.</p></details></div>`;

async function refresh(first) {
  const q = `window=${encodeURIComponent(DR.wid)}&top=${DR.top}&game=${DR.game}`;
  const [g, h] = await Promise.all([j("/api/drops/grid?" + q), j("/api/drops/hotspots?" + q)]);
  if (g.error) { $("#dmap").innerHTML = `<div class="card err">${esc(g.error)}</div>`; return; }
  DR.grid = g; DR.hot = h.error ? null : h; DR.heat = {};
  if (first) { controls(); mapShell(); }
  draw(); overview();
  lootCard(first);
  if (DR.poly) selectPoly(DR.poly);
}

const totals = () => "";
function controls() {
  const goal = DR.info.goal ? DR.info.goal.rank : null, chips = [...new Set([...(goal ? [goal] : []), 10, 50, 100, 500, 1000])].sort((a, b) => a - b);
  $("#dcontrols").innerHTML = `<div class="card"><div class="row" style="align-items:flex-end">
    <div style="flex:1"><label>Qualified = finished top…</label><input id="dtop" type="number" min="1" max="10000" value="${DR.top}"></div>
    <div style="flex:1"><label>Game</label><select id="dgame"><option value="0">All games</option></select></div>
    <div style="flex:2"><label>Layers</label><div class="chips"><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="lq" checked> <span style="color:#3aa0ff">● Qualified</span></label><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="la" checked> <span style="color:#ffb02e">● Everyone</span></label><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="lc" checked> <span style="color:#5be38a">◉ Chests</span></label></div></div></div>
    <div class="chips" style="margin-top:8px"><small>Quick pick:</small>${chips.map(c => `<button class="chip ${c === DR.top ? "on" : ""}" data-t="${c}">${c === goal ? "★ " : ""}Top ${c.toLocaleString()}</button>`).join("")}</div>
    <div class="row" style="margin-top:10px;align-items:center"><div><label>Heat spread</label><input id="dblur" type="range" min="0" max="16" value="${DR.blur}" style="padding:0;min-height:0"></div><div><label>Heat strength</label><input id="dalpha" type="range" min="20" max="100" value="${Math.round(DR.alpha * 100)}" style="padding:0;min-height:0"></div></div></div>`;
  const sel = $("#dgame"); (DR.grid.games || []).forEach(g => sel.insertAdjacentHTML("beforeend", `<option value="${g}">Game ${g}</option>`));
  const redo = () => { DR.top = clamp(Math.round(+$("#dtop").value || 100), 1, 10000); DR.game = +$("#dgame").value; $$("[data-t]").forEach(b => b.classList.toggle("on", +b.dataset.t === DR.top)); refresh(false); };
  $("#dtop").onchange = redo; $("#dgame").onchange = redo;
  $$("[data-t]").forEach(b => b.onclick = () => { $("#dtop").value = b.dataset.t; redo(); });
  $("#lq").onchange = e => { DR.layers.q = e.target.checked; draw(); }; $("#la").onchange = e => { DR.layers.all = e.target.checked; draw(); }; $("#lc").onchange = e => { DR.layers.chests = e.target.checked; draw(); };
  $("#dblur").oninput = e => { DR.blur = +e.target.value; draw(); }; $("#dalpha").oninput = e => { DR.alpha = +e.target.value / 100; draw(); };
}

function mapShell() {
  const tips = { move: "Drag to pan, scroll to zoom", box: "Drag a rectangle to see the stats of that area", draw: "Draw any shape freehand to see the stats of that area" };
  $("#dmap").innerHTML = `<div class="dr-stage"><div class="card dr-mapcard"><div class="chips dr-tools"><div class="seg" id="dmodes">${MODES.map(([k, l]) => `<button data-m="${k}" class="${k === DR.mode ? "on" : ""}" title="${tips[k]}">${l}</button>`).join("")}</div>
      <div class="chips"><button class="chip" id="dzi" title="Zoom in">＋</button><button class="chip" id="dzo" title="Zoom out">－</button><button class="chip" id="dreset" title="Reset the view">Reset view</button><button class="chip" id="dclear" title="Remove the selection">Clear selection</button></div></div>
      <div class="dr-canvas"><canvas id="dc"></canvas></div><div class="small" style="margin-top:8px" id="dhover">Move over the map for the numbers under the pointer.</div></div>
    <aside class="card dr-side" id="darea"></aside></div>`;
  $$("#dmodes button").forEach(b => b.onclick = () => { DR.mode = b.dataset.m; $$("#dmodes button").forEach(x => x.classList.toggle("on", x === b)); $("#dc").style.cursor = DR.mode === "move" ? "grab" : "crosshair"; });
  $("#dzi").onclick = () => zoomAt(0.5, 0.5, 1.4); $("#dzo").onclick = () => zoomAt(0.5, 0.5, 1 / 1.4);
  $("#dreset").onclick = () => { DR.z = 1; DR.ox = DR.oy = 0; draw(); };
  $("#dclear").onclick = clearSel;
  bindCanvas();
}
function clearSel() { DR.poly = DR.draft = DR.area = DR.mark = null; $$(".dr-row.on").forEach(r => r.classList.remove("on")); draw(); overview(); }

// ---- the map canvas: view transform, heat layers, selection
function sizeCanvas() {
  const c = $("#dc"), w = Math.min(860, c.parentElement.clientWidth || 700), r = window.devicePixelRatio || 1;
  DR.S = w; c.style.width = w + "px"; c.style.height = w + "px"; c.width = Math.round(w * r); c.height = Math.round(w * r); c.getContext("2d").setTransform(r, 0, 0, r, 0, 0);
}
const toPx = (u, v) => [(u * DR.z + DR.ox) * DR.S, (v * DR.z + DR.oy) * DR.S];
const toUV = (px, py) => [(px / DR.S - DR.ox) / DR.z, (py / DR.S - DR.oy) / DR.z];
function clampView() { DR.z = clamp(DR.z, 1, 16); DR.ox = clamp(DR.ox, 1 - DR.z, 0); DR.oy = clamp(DR.oy, 1 - DR.z, 0); }
function zoomAt(fx, fy, k) { const [u, v] = [(fx - DR.ox) / DR.z, (fy - DR.oy) / DR.z]; DR.z = clamp(DR.z * k, 1, 16); DR.ox = fx - u * DR.z; DR.oy = fy - v * DR.z; clampView(); draw(); }
function heatLayer(key, sparse) {
  if (DR.heat[key]) return DR.heat[key];
  const n = DR.grid.size, c = document.createElement("canvas"); c.width = c.height = n; const x = c.getContext("2d"), im = x.createImageData(n, n);
  const counts = sparse.map(s => s[1]).sort((a, b) => a - b), top = counts.length ? counts[Math.min(counts.length - 1, Math.floor(counts.length * 0.985))] : 1;
  // Colour ramps that stay readable on top of a detailed map picture: everyone = yellow to red, qualified = cyan to blue.
  const lo = key === "q" ? [40, 225, 255] : [255, 214, 40], hi = key === "q" ? [30, 70, 255] : [255, 40, 30];
  sparse.forEach(([cell, cnt]) => {
    const a = Math.min(1, Math.sqrt(cnt / Math.max(1, top)));
    im.data.set([lo[0] + (hi[0] - lo[0]) * a, lo[1] + (hi[1] - lo[1]) * a, lo[2] + (hi[2] - lo[2]) * a, Math.round(255 * Math.min(1, 0.4 + 0.75 * a))], cell * 4);
  });
  x.putImageData(im, 0, 0); return DR.heat[key] = c;
}
function draw() {
  const c = $("#dc"); if (!c || !DR.grid) return; if (c.dataset.s != DR.S) sizeCanvas();
  const x = c.getContext("2d"), S = DR.S, [px, py] = toPx(0, 0), W = S * DR.z;
  x.clearRect(0, 0, S, S); x.fillStyle = cssv("--sf2"); x.fillRect(0, 0, S, S);
  if (DR.img) { x.drawImage(DR.img, px, py, W, W); x.fillStyle = "rgba(8,10,16,0.38)"; x.fillRect(px, py, W, W); }   // dimmed so the heat stands out
  else { x.strokeStyle = cssv("--line"); x.lineWidth = 1; for (let i = 0; i <= 10; i++) { x.beginPath(); x.moveTo(px + W * i / 10, py); x.lineTo(px + W * i / 10, py + W); x.moveTo(px, py + W * i / 10); x.lineTo(px + W, py + W * i / 10); x.stroke(); } x.fillStyle = cssv("--mut"); x.font = "600 12px system-ui"; x.fillText("No picture of this map is available yet", px + 10, py + 20); }
  x.imageSmoothingEnabled = true; x.filter = DR.blur ? `blur(${DR.blur * DR.z / 2}px)` : "none"; x.globalAlpha = DR.alpha;
  if (DR.layers.all) x.drawImage(heatLayer("all", DR.grid.all), px, py, W, W);
  if (DR.layers.q) x.drawImage(heatLayer("q", DR.grid.q), px, py, W, W);
  x.filter = "none"; x.globalAlpha = 1;
  if (DR.layers.chests && DR.loot && DR.loot.sites) DR.loot.sites.forEach(c => {
    const [sx, sy] = toPx(c.x, c.y); if (sx < -10 || sy < -10 || sx > S + 10 || sy > S + 10) return;
    if (c.rate < (DR.info && DR.info.game_type === "br" ? 0.1 : 0)) return;   // BR chests spawn at random: seen in under 10% of matches = usually not there
    const t = clamp(c.rate, 0, 1), col = `rgb(${Math.round(70 + 185 * t)},${Math.round(220 - 150 * t)},${Math.round(110 - 40 * t)})`;   // green = rarely looted, red = looted almost every game
    drawChest(x, sx, sy, Math.min(9, 3 + 1.5 * Math.sqrt(DR.z)), col);
  });
  { const sel = DR.draft || DR.poly;   // shade everything outside the selected area
    if (sel && sel.length > 2) { x.save(); x.beginPath(); x.rect(px, py, W, W); sel.forEach(([u, v], i) => { const [a, b] = toPx(u, v); i ? x.lineTo(a, b) : x.moveTo(a, b); }); x.closePath(); x.fillStyle = "rgba(4,6,12,0.52)"; x.fill("evenodd"); x.restore(); } }
  if (DR.mark) { const [mx, my] = toPx(DR.mark.x, DR.mark.y); x.beginPath(); x.arc(mx, my, DR.mark.r * S * DR.z, 0, 7); x.setLineDash([6, 4]); x.lineWidth = 2.5; x.strokeStyle = "#fff"; x.stroke(); x.setLineDash([]);
    x.font = "700 12px system-ui"; x.lineWidth = 4; x.strokeStyle = "#000c"; x.strokeText(DR.mark.label, mx - 8, my - DR.mark.r * S * DR.z - 6); x.fillStyle = "#fff"; x.fillText(DR.mark.label, mx - 8, my - DR.mark.r * S * DR.z - 6); }
  const poly = DR.draft || DR.poly;
  if (poly && poly.length > 1) { x.beginPath(); poly.forEach(([u, v], i) => { const [a, b] = toPx(u, v); i ? x.lineTo(a, b) : x.moveTo(a, b); }); x.closePath(); x.fillStyle = "rgba(255,255,255,.14)"; x.fill(); x.strokeStyle = "#fff"; x.lineWidth = 2; x.setLineDash(DR.draft ? [5, 4] : []); x.stroke(); x.setLineDash([]); }
}
function bindCanvas() {
  const c = $("#dc"); sizeCanvas(); c.dataset.s = DR.S; c.style.cursor = DR.mode === "move" ? "grab" : "crosshair"; c.style.touchAction = "none";
  let drag = null;
  const pos = e => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  c.onpointerdown = e => { c.setPointerCapture(e.pointerId); const [x, y] = pos(e), uv = toUV(x, y); drag = { x, y, uv, ox: DR.ox, oy: DR.oy, pts: [uv], moved: false };
  };
  c.onpointermove = e => {
    const [x, y] = pos(e), uv = toUV(x, y); hoverInfo(uv);
    if (!drag) return;
    if (DR.mode === "move") { if (Math.abs(x - drag.x) + Math.abs(y - drag.y) > 4) drag.moved = true; DR.ox = drag.ox + (x - drag.x) / DR.S; DR.oy = drag.oy + (y - drag.y) / DR.S; clampView(); draw(); }
    else if (DR.mode === "box") { const a = drag.uv, b = uv; DR.draft = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]; draw(); }
    else if (DR.mode === "draw") { const l = drag.pts[drag.pts.length - 1]; if (Math.hypot(uv[0] - l[0], uv[1] - l[1]) > 0.004 / DR.z) { drag.pts.push(uv); DR.draft = drag.pts.slice(); draw(); } }
  };
  c.onpointerup = e => { if (!drag) return;
    const d = DR.draft; DR.draft = null;
    if (d && ((DR.mode === "box" && Math.abs(d[0][0] - d[2][0]) > 0.004 && Math.abs(d[0][1] - d[2][1]) > 0.004) || (DR.mode === "draw" && d.length >= 4))) { const p = DR.mode === "draw" ? simplify(d, 60) : d; selectPoly(p.map(([u, v]) => [clamp(u, 0, 1), clamp(v, 0, 1)])); } else draw();
    drag = null; };
  c.onwheel = e => { e.preventDefault(); const [x, y] = pos(e); zoomAt(x / DR.S, y / DR.S, e.deltaY < 0 ? 1.25 : 0.8); };
  c.onpointerleave = () => { $("#dhover") && ($("#dhover").textContent = "Move over the map for the numbers under the pointer."); };
  window.addEventListener("resize", () => { if ($("#dc")) { sizeCanvas(); $("#dc").dataset.s = DR.S; draw(); } });
}
const simplify = (pts, max) => pts.length <= max ? pts : pts.filter((_, i) => i % Math.ceil(pts.length / max) === 0);
function hoverInfo(uv) {
  const g = DR.grid, el = $("#dhover"); if (!g || !el) return; const n = g.size, ix = Math.floor(uv[0] * n), iy = Math.floor(uv[1] * n);
  if (ix < 0 || iy < 0 || ix >= n || iy >= n) return; const cell = iy * n + ix, a = (g.all.find(s => s[0] === cell) || [0, 0])[1], q = (g.q.find(s => s[0] === cell) || [0, 0])[1];
  el.innerHTML = a ? `Here: <b>${a}</b> landing${a === 1 ? "" : "s"}, <b>${q}</b> by teams that finished top ${nf(DR.top)} (${pc(q / a)})` : "Nobody landed here.";
}
async function selectPoly(poly, label) {
  DR.poly = poly; DR.draft = null; draw();
  const box = $("#darea"); if (!box) return; box.innerHTML = '<div class="hd"><h2>Selected area</h2></div>' + skel(1, 160);
  const d = await j(`/api/drops/area?window=${encodeURIComponent(DR.wid)}&top=${DR.top}&game=${DR.game}&poly=${poly.map(p => p[0].toFixed(4) + "," + p[1].toFixed(4)).join(";")}`);
  if (DR.poly !== poly || !$("#darea")) return; DR.area = d; areaPanel(d, label);
}
const ctCls = r => r == null ? "" : r >= 0.6 ? "bad" : r >= 0.3 ? "warn" : "good";
const ctWord = r => r == null ? "" : r >= 0.75 ? "very contested" : r >= 0.5 ? "contested" : r >= 0.25 ? "sometimes shared" : "mostly quiet";
function contestKpi(ct) {
  if (!ct || ct.rate == null) return kpi("Contest rate", "–", "no landings");
  return `<div class="kpi hero dr-contest"><div class="l">Contest rate <span title="Share of games in which two or more different teams landed here. Players on the same team never count against each other.">ⓘ</span></div><div class="v ${ctCls(ct.rate)}">${pc(ct.rate, 0)}</div>
    <div class="prog" style="margin:6px 0 4px"><i style="width:${clamp(ct.rate * 100, 1, 100)}%;background:var(--${ctCls(ct.rate) || "ac"})"></i></div><div class="d">${ctWord(ct.rate)}${ct.estimated ? " · estimated" : ""}${ct.avg_teams ? " · " + nd(ct.avg_teams, 1) + " teams per game when landed" : ""}</div></div>`;
}
const circle = (x, y, r, n = 32) => Array.from({ length: n }, (_, i) => [x + r * Math.cos(i / n * 6.2832), y + r * Math.sin(i / n * 6.2832)]);
function overview() {
  const box = $("#darea"); if (!box || DR.poly) return;
  const g = DR.grid, spots = DR.hot && DR.hot.spots ? DR.hot.spots : [];
  box.innerHTML = `<div class="hd"><h2>Overview</h2><span class="sub">${nf(g.total)} landings</span></div>
    <div class="kpis dr-k2">${kpi("Landings", nf(g.total), `${nf(g.qualifier_landings)} by teams that finished top ${nf(DR.top)}`, "hero")}
      ${kpi("Qualified share", pc(g.total ? g.qualifier_landings / g.total : 0, 1), "of all landings")}</div>
    <p class="small mut" style="margin:10px 0">Mark an area with <b>Box</b> or <b>Draw</b>, or click a busy area below, to see its contest rate, qualified share, points and best teams.</p>
    <h3>Busiest landing areas</h3>
    ${spots.length ? `<div class="dr-hot">${spots.map((s, i) => `<button class="dr-spot" data-i="${i}"><span class="n">${i + 1}</span><span class="t"><b>${nf(s.landings)}</b> landings · ${pc(s.share_of_landings, 1)}<small>${pc(s.qualifier_share, 0)} qualified · ${nd(s.avg_points)} pts/game</small></span><span class="c ${ctCls(s.contest)}"><b>${s.contest == null ? "–" : pc(s.contest, 0)}</b><small>contest${s.contest_estimated ? " (est.)" : ""}</small></span></button>`).join("")}</div>` : '<p class="mut">Not enough landings to find busy areas.</p>'}`;
  $$("#darea .dr-spot").forEach(b => b.onclick = () => { const i = +b.dataset.i, s = spots[i]; DR.mark = { x: s.x, y: s.y, r: s.r, label: "Busy area " + (i + 1) }; selectPoly(circle(s.x, s.y, s.r), "Busy area " + (i + 1)); });
}
function areaPanel(d, label) {
  const box = $("#darea"), back = `<button class="chip" id="dback">← Overview</button>`;
  const fin = html => { box.innerHTML = html; $("#dback").onclick = clearSel; };
  if (d.error) return fin(`<div class="hd"><h2>Selected area</h2>${back}</div><p class="err">${esc(d.error)}</p>`);
  const a = d.area, e = d.everywhere;
  if (!a.landings) return fin(`<div class="hd"><h2>Selected area</h2>${back}</div><p class="mut">Nobody landed inside this area${DR.game ? " in game " + DR.game : ""}. Try a bigger one.</p>`);
  const dlt = (x, y, f = 1, suf = "") => { const v = x - y; return `<small class="${v > 0 ? "ok" : v < 0 ? "err" : ""}">${v > 0 ? "+" : ""}${nd(v, f)}${suf} vs everyone</small>`; };
  fin(`<div class="hd"><h2>${label ? esc(label) : "Selected area"}</h2>${back}</div>
    ${contestKpi(d.contest)}
    <div class="kpis dr-k2">${kpi("Landings", nf(a.landings), `${pc(a.share_of_landings, 1)} of all · ${a.qualifier_landings} qualified`)}
      ${kpi("Qualified share", pc(a.qualifier_share, 1), `everywhere ${pc(e.qualifier_share, 1)}`, a.qualifier_share > e.qualifier_share ? "good" : "")}
      ${kpi("Points per game", nd(a.avg_points), dlt(a.avg_points, e.avg_points))}
      ${kpi("Average finish", "top " + pc(a.avg_placement_pct), `everywhere top ${pc(e.avg_placement_pct)}`)}
      ${kpi("Early exits", pc(a.early_exit_rate), `everywhere ${pc(e.early_exit_rate)}`, a.early_exit_rate > e.early_exit_rate ? "bad" : "")}
      ${kpi("Wins", pc(a.win_rate, 1), `everywhere ${pc(e.win_rate, 1)}`)}
      ${kpi("Top-quarter finishes", pc(a.top_quarter_rate, 1), `everywhere ${pc(e.top_quarter_rate, 1)}`)}
      ${kpi("Of all qualifiers", pc(a.share_of_qualifier_landings, 1), "landed here")}</div>
    ${lootBlock(d.loot)}
    ${Object.keys(d.by_game).length > 1 ? `<div class="small" style="margin:8px 0">By game: ${Object.entries(d.by_game).map(([g, n]) => `G${g} <b>${n}</b>`).join(" · ")}</div>` : ""}
    ${d.teams && d.teams.length ? `<h3>Best teams that landed here</h3><p class="small" style="margin:0 0 6px">Ranked by final place in the event.</p>${table(["Team", "Final", "Landed", "Pts/game", "Best"], d.teams.map(t => [esc(t.team), "#" + nf(t.rank), t.landings + "×", nd(t.avg_points), "#" + t.best_placement]), ["", "n", "n", "n", "n"])}` : ""}
    <h3>Best single results from here</h3>${table(["Team", "Game", "Pts", "Place", "Final"], d.best.map(b => [esc(b.team), b.game, b.points, "#" + b.placement, b.rank ? "#" + nf(b.rank) : "-"]), ["", "n", "n", "n", "n"])}`);
}


// ---- chests: where they are, how often they are looted early, and the best loot for the fewest players
const lootBlock = l => !l ? `<p class="small mut">Chest positions are not known for this map yet.</p>` : !l.chests ? `<p class="small mut">No known chests in this area.</p>` :
  `<h3>Loot here</h3><div class="kpis" style="grid-template-columns:repeat(2,1fr)">${kpi("Chests", nf(l.chests), `looted early in ${pc(l.lootage, 0)} of games`)}${kpi("Players per game", nd(l.players_per_game, 1), `${nd(l.teams_per_game, 1)} teams on average`)}${kpi("Chests per player", nd(l.chests_per_player, 2), `${nd(l.free_chests, 1)} chests still free on average`, l.chests_per_player >= 1 ? "good" : "")}</div>`;

async function lootCard(first) {
  const box = $("#dloot"); if (!box) return;
  if (first || !DR.loot) { DR.loot = await j(`/api/drops/loot?window=${encodeURIComponent(DR.wid)}`); if (DR.loot.error) DR.loot = { sites: [], note: DR.loot.error }; draw(); }
  if (!DR.loot.sites || !DR.loot.sites.length) { box.innerHTML = `<div class="card"><div class="hd"><h2>Best loot for the fewest players</h2></div><p class="mut">${esc(DR.loot.note || "Chest positions are not known for this map yet.")} The scheduled job adds matches every few hours.</p></div>`; return; }
  const d = await j(`/api/drops/areas?window=${encodeURIComponent(DR.wid)}&top=${DR.top}&game=${DR.game}`);
  if (d.error) { box.innerHTML = `<div class="card"><div class="hd"><h2>Best loot for the fewest players</h2></div><p class="err">${esc(d.error)}</p></div>`; return; }
  DR.areas = d; renderLoot();
}
function renderLoot() {
  const box = $("#dloot"), d = DR.areas; if (!box || !d) return;
  const cols = [["label", "Area", 0], ["chests", "Chests", 1], ["lootage", "Looted early", 1], ["players_per_game", "Players / game", 1], ["contest", "Contest rate", 1], ["score", "Loot score", 1], ["chests_per_player", "Chests per player", 1], ["free_chests", "Chests still free", 1], ["avg_points", "Pts / game", 1], ["qualifier_share", "Qualified share", 1]];
  const key = DR.lootSort || "score", asc = ["players_per_game", "lootage"].includes(key);
  const rows = d.areas.slice().sort((a, b) => key === "label" ? a.label.localeCompare(b.label) : asc ? a[key] - b[key] : b[key] - a[key]);
  const best = d.areas[0];
  box.innerHTML = `<div class="card"><div class="hd"><h2>Best loot for the fewest players</h2><span class="sub">${nf(DR.loot.chests)} chests found · lootage = share of games in which a chest was opened in the first minutes · ${nf(d.chest_matches)} matches</span></div>
    ${best ? `<p style="margin:0 0 10px">Most loot for the fewest players: <b>area ${esc(best.label)}</b> with <b>${best.chests} chests</b> and only <b>${nd(best.players_per_game, 1)} players</b> landing per game (loot score ${nd(best.score, 2)} = chests ÷ (players + 1); chests there are looted early in ${pc(best.lootage, 0)} of games).</p>` : ""}
    <div class="small" style="margin-bottom:8px">On average <b>${nd(d.teams_per_match, 1)}</b> teams (${nd(d.teams_per_match * d.team_size, 1)} players) land per game. ${d.lobby && d.teams_per_match < d.lobby * 0.9 ? `<b class="err">Only ${nd(d.teams_per_match, 1)} of ${d.lobby} teams per match were loaded for this tournament (it was loaded before full lobbies were included), so players per game are too low here.</b> ` : ""}Click a row to mark the area on the map, click a heading to sort.</div>
    <div class="scroll"><table><tr>${cols.map(([k, l, n]) => `<th class="${n ? "n" : ""}" data-s="${k}" style="cursor:pointer">${l}${key === k ? " ▾" : ""}</th>`).join("")}</tr>` +
    rows.map(r => `<tr class="dr-row" data-l="${esc(r.label)}-${r.x}" style="cursor:pointer"><td><b>${esc(r.label)}</b></td><td class="n">${r.chests}</td><td class="n">${pc(r.lootage, 0)}</td><td class="n">${nd(r.players_per_game, 1)}</td><td class="n ${ctCls(r.contest)}">${r.contest == null ? "–" : pc(r.contest, 0)}</td><td class="n"><b>${nd(r.score, 2)}</b></td><td class="n">${nd(r.chests_per_player, 2)}</td><td class="n">${nd(r.free_chests, 1)}</td><td class="n">${nd(r.avg_points)}</td><td class="n">${pc(r.qualifier_share, 1)}</td></tr>`).join("") + "</table></div></div>";
  $$("#dloot th").forEach(t => t.onclick = () => { DR.lootSort = t.dataset.s; renderLoot(); });
  $$("#dloot .dr-row").forEach(t => t.onclick = () => {
    const r = d.areas.find(a => `${a.label}-${a.x}` === t.dataset.l); if (!r) return; $$("#dloot .dr-row.on").forEach(x => x.classList.remove("on")); t.classList.add("on");
    DR.mark = { x: r.x, y: r.y, r: r.r, label: r.label };
    selectPoly(circle(r.x, r.y, r.r), `Loot area ${r.label}`);
    $("#dmap").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}
