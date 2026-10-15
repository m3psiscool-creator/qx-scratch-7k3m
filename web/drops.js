"use strict";
// Dropspots: where teams landed in a tournament, for the teams that qualified and for everyone.
// Landing rows are loaded by the owner (docs/dropspots-data.md); this page only reads them.
const DR = { wid: null, info: null, grid: null, pois: null, area: null, top: 100, game: 0, mode: "move", z: 1, ox: 0, oy: 0, poly: null, draft: null, hover: null,
  layers: { q: true, all: true, spots: true }, blur: 5, alpha: 0.9, img: null, imgUrl: "", heat: {}, S: 700, sortBy: "landings", fq: "", freg: "" };
const MODES = [["move", "Move"], ["box", "Box"], ["draw", "Draw"], ["spot", "Spot"]];

async function dropsPage(wid) {
  DR.wid = wid || null; DR.info = DR.grid = DR.pois = DR.area = DR.poly = null; DR.z = 1; DR.ox = DR.oy = 0; DR.heat = {}; DR.game = 0;
  const [avail, all] = await Promise.all([j("/api/drops/events"), allWindows()]);
  DR.avail = avail && !avail.error ? avail : {};
  DR.events = all.filter(w => w.status === "finished" || ACTIVE.includes(w.status)).map(w => ({ ...w, n: (DR.avail[w.window_id] || {}).landings || 0 }))
    .sort((a, b) => (b.n > 0) - (a.n > 0) || b.end - a.end);
  const withData = Object.keys(DR.avail).length;
  app.innerHTML = `<div class="ph"><div><h1>Dropspots</h1><p>Where teams landed in a tournament: the teams that qualified against everyone else. Pick a tournament, then draw any area on the map to see who landed there and how it went.</p></div></div>
    <div class="dr-layout"><div class="card dr-pick"><div class="hd"><h2>Tournament</h2><span class="sub">${withData} with landing data</span></div>
      <input id="dq" placeholder="Search name, region, gamemode…" value="${esc(DR.fq)}">
      <div class="chips" style="margin:8px 0" id="dreg">${["", ...REGIONS].map(r => `<button class="chip ${r === DR.freg ? "on" : ""}" data-r="${r}">${r || "All"}</button>`).join("")}</div>
      <div class="dr-list" id="dlist"></div></div>
    <div id="dtool" class="dr-main"></div></div>`;
  $("#dq").oninput = e => { DR.fq = e.target.value; drawList(); };
  $$("#dreg button").forEach(b => b.onclick = () => { DR.freg = b.dataset.r; $$("#dreg button").forEach(x => x.classList.toggle("on", x === b)); drawList(); });
  drawList();
  if (wid) await loadDrops(wid); else $("#dtool").innerHTML = `<div class="card empty">Choose a tournament on the left.<br><small>Tournaments with landing data are listed first.</small></div>`;
}
function drawList() {
  const l = DR.events.filter(w => (!DR.freg || w.region === DR.freg) && (!DR.fq || matches(w, DR.fq))).slice(0, 80);
  $("#dlist").innerHTML = l.map(w => `<a href="#/drops/${encodeURIComponent(w.window_id)}" class="dr-item ${w.window_id === DR.wid ? "on" : ""}"><b>${esc(w.name)}</b><small>${esc(w.region)} · ${esc(gm(w.category))} · ${fmt(w.end)}</small><small class="${w.n ? "ok" : "mut"}">${w.n ? nf(w.n) + " landings" : "no landing data"}</small></a>`).join("") || '<p class="mut">No tournament matches.</p>';
}

async function loadDrops(wid) {
  const tool = $("#dtool"); tool.innerHTML = skel(2, 120);
  const info = await j("/api/drops/info?window=" + encodeURIComponent(wid));
  if (info.error) { tool.innerHTML = `<div class="card err">${esc(info.error)}</div>`; return; }
  DR.info = info; DR.top = info.goal ? info.goal.rank : 100;
  tool.innerHTML = infoCard(info) + (info.landings ? `<div id="dcontrols"></div><div id="dmap"></div><div id="dspots"></div>` : noData(info));
  if (!info.landings) return;
  DR.imgUrl = info.map && info.map.image || ""; DR.img = null; DR.base = info.map && info.map.base ? buildBase(info.map.base, info.map.base_size || 128) : null;
  if (DR.imgUrl) { const im = new Image(); im.onload = () => { DR.img = im; draw(); }; im.src = DR.imgUrl; }
  await refresh(true);
}
function infoCard(i) {
  const m = i.map;
  return `<div class="card"><div class="hd"><h2>${esc(i.name)} <span class="pill">${esc(i.region)}</span></h2><span class="sub">${fmt(i.begin)}</span></div>
    <div class="kpis" style="margin:0"><div class="kpi"><div class="l">Map</div><div class="v" style="font-size:1.1rem">${esc(m && m.name ? m.name : i.label)}</div><div class="d">${m && m.credit ? esc(m.credit) : i.note ? esc(i.note) : ""}</div></div>
      <div class="kpi"><div class="l">Playlist</div><div class="v" style="font-size:.95rem;word-break:break-all">${esc(i.playlist || "unknown")}</div><div class="d">${i.codename ? "codename " + esc(i.codename) + " · " : ""}${i.build ? "builds on" : "zero build"} · ${esc(i.mode || "")}</div></div>
      <div class="kpi"><div class="l">Format</div><div class="v" style="font-size:1.1rem">${i.match_cap || "?"} games</div><div class="d">${i.goal ? "goal: top " + nf(i.goal.rank) + " (" + esc(i.goal.kind) + ")" : "no single goal"}</div></div>
      <div class="kpi"><div class="l">Landing data</div><div class="v" style="font-size:1.1rem">${i.landings ? nf(i.landings) + " landings" : "none yet"}</div><div class="d">${i.landings ? i.games + " game" + (i.games === 1 ? "" : "s") + " recorded" : "see below"}</div></div></div></div>`;
}
const noData = i => `<div class="card"><div class="hd"><h2>No landing data for this tournament yet</h2></div>
  <p>Epic's leaderboard does not say where anyone landed, so this page needs landing data loaded from a replay source. Once it is loaded, you get heatmaps of everyone and of the teams that qualified, and you can draw any area on the map.</p>
  <details><summary class="small" style="cursor:pointer">Owner: how to load it</summary>
  <p class="small">Send one row per team per game to <code>POST /api/admin/drops</code> with your admin key, or run <code>python scripts/import_drops.py landings.json</code>. Rows look like this:</p>
  <pre class="small">{ "window_id": "${esc(i.window_id)}", "coords": "unit",
  "map": { "name": "…", "image": "https://…", "pois": [{ "name": "Tilted", "x": 0.41, "y": 0.62 }] },
  "drops": [{ "game": 1, "team": "acct+acct", "x": 0.41, "y": 0.62, "poi": "Tilted", "placement": 7, "points": 23, "rank": 120 }] }</pre>
  <p class="small">x and y run from 0 to 1 across the map image (top-left is 0,0), or send game coordinates with bounds. Full format: <code>docs/dropspots-data.md</code>.</p></details></div>`;

async function refresh(first) {
  const q = `window=${encodeURIComponent(DR.wid)}&top=${DR.top}&game=${DR.game}`;
  const [g, p] = await Promise.all([j("/api/drops/grid?" + q), j("/api/drops/pois?" + q)]);
  if (g.error) { $("#dmap").innerHTML = `<div class="card err">${esc(g.error)}</div>`; return; }
  DR.grid = g; DR.pois = p.error ? null : p; DR.heat = {};
  if (first) { controls(); mapShell(); }
  else { $("#dtotals") && ($("#dtotals").innerHTML = totals()); }
  spotsTable(); draw();
  if (DR.poly) selectPoly(DR.poly);
}
const spotsList = () => (DR.info.map && DR.info.map.pois && DR.info.map.pois.length ? DR.info.map.pois : (DR.pois ? DR.pois.pois.map(p => ({ name: p.name, x: p.x, y: p.y, r: 0.03 })) : []));
function totals() { const g = DR.grid; return `<b>${nf(g.total)}</b> landings · <b>${nf(g.qualifier_landings)}</b> by teams that finished top ${nf(DR.top)}`; }

function controls() {
  const goal = DR.info.goal ? DR.info.goal.rank : null, chips = [...new Set([...(goal ? [goal] : []), 10, 50, 100, 500, 1000])].sort((a, b) => a - b);
  $("#dcontrols").innerHTML = `<div class="card"><div class="row" style="align-items:flex-end">
    <div style="flex:1"><label>Qualified = finished top…</label><input id="dtop" type="number" min="1" max="10000" value="${DR.top}"></div>
    <div style="flex:1"><label>Game</label><select id="dgame"><option value="0">All games</option>${DR.grid ? "" : ""}</select></div>
    <div style="flex:2"><label>Layers</label><div class="chips"><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="lq" checked> <span style="color:var(--s1)">● Qualified</span></label><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="la" checked> <span style="color:var(--s2)">● Everyone</span></label><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="ls" checked> Named spots</label></div></div></div>
    <div class="chips" style="margin-top:8px"><small>Quick pick:</small>${chips.map(c => `<button class="chip ${c === DR.top ? "on" : ""}" data-t="${c}">${c === goal ? "★ " : ""}Top ${c.toLocaleString()}</button>`).join("")}</div>
    <div class="row" style="margin-top:10px;align-items:center"><div><label>Heat spread</label><input id="dblur" type="range" min="0" max="16" value="${DR.blur}" style="padding:0;min-height:0"></div><div><label>Heat strength</label><input id="dalpha" type="range" min="20" max="100" value="${Math.round(DR.alpha * 100)}" style="padding:0;min-height:0"></div></div></div>`;
  const sel = $("#dgame"); (DR.grid.games || []).forEach(g => sel.insertAdjacentHTML("beforeend", `<option value="${g}">Game ${g}</option>`));
  const redo = () => { DR.top = clamp(Math.round(+$("#dtop").value || 100), 1, 10000); DR.game = +$("#dgame").value; $$("[data-t]").forEach(b => b.classList.toggle("on", +b.dataset.t === DR.top)); refresh(false); };
  $("#dtop").onchange = redo; $("#dgame").onchange = redo;
  $$("[data-t]").forEach(b => b.onclick = () => { $("#dtop").value = b.dataset.t; redo(); });
  $("#lq").onchange = e => { DR.layers.q = e.target.checked; draw(); }; $("#la").onchange = e => { DR.layers.all = e.target.checked; draw(); }; $("#ls").onchange = e => { DR.layers.spots = e.target.checked; draw(); };
  $("#dblur").oninput = e => { DR.blur = +e.target.value; draw(); }; $("#dalpha").oninput = e => { DR.alpha = +e.target.value / 100; draw(); };
}

function mapShell() {
  $("#dmap").innerHTML = `<div class="dr-grid"><div class="card" style="padding:12px"><div class="chips" style="margin-bottom:8px;justify-content:space-between"><div class="seg" id="dmodes">${MODES.map(([k, l]) => `<button data-m="${k}" class="${k === DR.mode ? "on" : ""}" title="${{ move: "Drag to pan, scroll to zoom", box: "Drag a rectangle", draw: "Draw any shape freehand", spot: "Click a named spot" }[k]}">${l}</button>`).join("")}</div>
      <div class="chips"><button class="chip" id="dzi" title="Zoom in">＋</button><button class="chip" id="dzo" title="Zoom out">－</button><button class="chip" id="dreset" title="Reset the view">Reset view</button><button class="chip" id="dclear" title="Remove the selection">Clear selection</button></div></div>
      <div class="dr-canvas"><canvas id="dc"></canvas></div><div class="small" style="margin-top:6px" id="dhover">Move over the map for the numbers under the pointer.</div><div class="small" id="dtotals">${totals()}</div></div>
    <div class="card" id="darea"><div class="hd"><h2>Selected area</h2></div><p class="mut">Pick <b>Box</b>, <b>Draw</b> or <b>Spot</b> and mark an area on the map. You get who landed there, how many qualified, and how they scored compared with everyone.</p></div></div>`;
  $$("#dmodes button").forEach(b => b.onclick = () => { DR.mode = b.dataset.m; $$("#dmodes button").forEach(x => x.classList.toggle("on", x === b)); $("#dc").style.cursor = DR.mode === "move" ? "grab" : "crosshair"; });
  $("#dzi").onclick = () => zoomAt(0.5, 0.5, 1.4); $("#dzo").onclick = () => zoomAt(0.5, 0.5, 1 / 1.4);
  $("#dreset").onclick = () => { DR.z = 1; DR.ox = DR.oy = 0; draw(); };
  $("#dclear").onclick = () => { DR.poly = DR.draft = DR.area = null; $("#darea").innerHTML = areaEmpty(); draw(); $$(".dr-row.on").forEach(r => r.classList.remove("on")); };
  bindCanvas();
}
const areaEmpty = () => '<div class="hd"><h2>Selected area</h2></div><p class="mut">Pick <b>Box</b>, <b>Draw</b> or <b>Spot</b> and mark an area on the map.</p>';

// ---- the map canvas: view transform, heat layers, selection
function sizeCanvas() {
  const c = $("#dc"), w = Math.min(760, c.parentElement.clientWidth || 700), r = window.devicePixelRatio || 1;
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
  const rgb = key === "q" ? [57, 135, 229] : [232, 121, 63];
  sparse.forEach(([cell, cnt]) => { const a = Math.min(1, Math.sqrt(cnt / Math.max(1, top))); im.data.set([rgb[0], rgb[1], rgb[2], Math.round(255 * a)], cell * 4); });
  x.putImageData(im, 0, 0); return DR.heat[key] = c;
}
// A background drawn from where players moved after landing: the shape of the island appears from the traffic itself.
function buildBase(cells, size) {
  const c = document.createElement("canvas"); c.width = c.height = size; const g = c.getContext("2d"), im = g.createImageData(size, size);
  const vals = Object.values(cells), mx = Math.log(1 + Math.max(...vals, 1));
  for (const [k, n] of Object.entries(cells)) { const i = +k * 4, a = Math.min(1, Math.log(1 + n) / mx); im.data[i] = 150; im.data[i + 1] = 165; im.data[i + 2] = 190; im.data[i + 3] = Math.round(30 + 190 * a); }
  g.putImageData(im, 0, 0); return c;
}
function draw() {
  const c = $("#dc"); if (!c || !DR.grid) return; if (c.dataset.s != DR.S) sizeCanvas();
  const x = c.getContext("2d"), S = DR.S, [px, py] = toPx(0, 0), W = S * DR.z;
  x.clearRect(0, 0, S, S); x.fillStyle = cssv("--sf2"); x.fillRect(0, 0, S, S);
  if (DR.img) x.drawImage(DR.img, px, py, W, W);
  else if (DR.base) { x.imageSmoothingEnabled = true; x.drawImage(DR.base, px, py, W, W); x.fillStyle = cssv("--mut"); x.font = "600 11px system-ui"; x.fillText("Map drawn from where players moved", px + 10, py + 18); }
  else { x.strokeStyle = cssv("--line"); x.lineWidth = 1; for (let i = 0; i <= 10; i++) { x.beginPath(); x.moveTo(px + W * i / 10, py); x.lineTo(px + W * i / 10, py + W); x.moveTo(px, py + W * i / 10); x.lineTo(px + W, py + W * i / 10); x.stroke(); } x.fillStyle = cssv("--mut"); x.font = "600 12px system-ui"; x.fillText("No map image loaded: coordinates run 0 to 1", px + 10, py + 20); }
  x.imageSmoothingEnabled = true; x.filter = DR.blur ? `blur(${DR.blur * DR.z / 2}px)` : "none"; x.globalAlpha = DR.alpha;
  if (DR.layers.all) x.drawImage(heatLayer("all", DR.grid.all), px, py, W, W);
  if (DR.layers.q) x.drawImage(heatLayer("q", DR.grid.q), px, py, W, W);
  x.filter = "none"; x.globalAlpha = 1;
  if (DR.layers.spots) spotsList().forEach(p => { const [sx, sy] = toPx(p.x, p.y); if (sx < -20 || sy < -20 || sx > S + 20 || sy > S + 20) return; x.beginPath(); x.arc(sx, sy, 3.5, 0, 7); x.fillStyle = "#fff"; x.fill(); x.strokeStyle = "#000"; x.lineWidth = 1; x.stroke(); if (DR.z >= 1.3 || spotsList().length <= 14) { x.font = "600 11px system-ui"; x.lineWidth = 3; x.strokeStyle = "#0009"; x.strokeText(p.name, sx + 6, sy + 4); x.fillStyle = "#fff"; x.fillText(p.name, sx + 6, sy + 4); } });
  const poly = DR.draft || DR.poly;
  if (poly && poly.length > 1) { x.beginPath(); poly.forEach(([u, v], i) => { const [a, b] = toPx(u, v); i ? x.lineTo(a, b) : x.moveTo(a, b); }); x.closePath(); x.fillStyle = "rgba(255,255,255,.14)"; x.fill(); x.strokeStyle = "#fff"; x.lineWidth = 2; x.setLineDash(DR.draft ? [5, 4] : []); x.stroke(); x.setLineDash([]); }
}
function bindCanvas() {
  const c = $("#dc"); sizeCanvas(); c.dataset.s = DR.S; c.style.cursor = "grab"; c.style.touchAction = "none";
  let drag = null;
  const pos = e => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  c.onpointerdown = e => { c.setPointerCapture(e.pointerId); const [x, y] = pos(e), uv = toUV(x, y); drag = { x, y, uv, ox: DR.ox, oy: DR.oy, pts: [uv] };
    if (DR.mode === "spot") { drag = null; pickSpot(uv); } };
  c.onpointermove = e => {
    const [x, y] = pos(e), uv = toUV(x, y); hoverInfo(uv);
    if (!drag) return;
    if (DR.mode === "move") { DR.ox = drag.ox + (x - drag.x) / DR.S; DR.oy = drag.oy + (y - drag.y) / DR.S; clampView(); draw(); }
    else if (DR.mode === "box") { const a = drag.uv, b = uv; DR.draft = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]; draw(); }
    else if (DR.mode === "draw") { const l = drag.pts[drag.pts.length - 1]; if (Math.hypot(uv[0] - l[0], uv[1] - l[1]) > 0.004 / DR.z) { drag.pts.push(uv); DR.draft = drag.pts.slice(); draw(); } }
  };
  c.onpointerup = () => { if (!drag) return; const d = DR.draft; DR.draft = null;
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
function pickSpot(uv) {
  const l = spotsList(); if (!l.length) { $("#dhover").textContent = "This tournament has no named spots. Use Box or Draw."; return; }
  const best = l.reduce((b, p) => Math.hypot(p.x - uv[0], p.y - uv[1]) < Math.hypot(b.x - uv[0], b.y - uv[1]) ? p : b), r = Math.max(0.015, best.r || 0.03);
  if (Math.hypot(best.x - uv[0], best.y - uv[1]) > Math.max(r * 2.2, 0.04 / DR.z)) return;
  selectPoly(Array.from({ length: 28 }, (_, i) => [best.x + r * Math.cos(i / 28 * 6.2832), best.y + r * Math.sin(i / 28 * 6.2832)]), best.name);
}
async function selectPoly(poly, label) {
  DR.poly = poly; DR.draft = null; draw();
  const box = $("#darea"); if (!box) return; box.innerHTML = '<div class="hd"><h2>Selected area</h2></div>' + skel(1, 160);
  const d = await j(`/api/drops/area?window=${encodeURIComponent(DR.wid)}&top=${DR.top}&game=${DR.game}&poly=${poly.map(p => p[0].toFixed(4) + "," + p[1].toFixed(4)).join(";")}`);
  if (DR.poly !== poly || !$("#darea")) return; DR.area = d; areaPanel(d, label);
}
function areaPanel(d, label) {
  const box = $("#darea");
  if (d.error) { box.innerHTML = `<div class="hd"><h2>Selected area</h2></div><p class="err">${esc(d.error)}</p>`; return; }
  const a = d.area, e = d.everywhere;
  if (!a.landings) { box.innerHTML = `<div class="hd"><h2>Selected area</h2></div><p class="mut">Nobody landed inside this area${DR.game ? " in game " + DR.game : ""}. Try a bigger one.</p>`; return; }
  const dlt = (x, y, f = 1, suf = "") => { const v = x - y; return `<small class="${v > 0 ? "ok" : v < 0 ? "err" : ""}">${v > 0 ? "+" : ""}${nd(v, f)}${suf} vs everyone</small>`; };
  const bar = (v, base, color) => `<div class="prog" style="margin:4px 0 2px"><i style="width:${clamp(v * 100, 1, 100)}%;background:${color}"></i></div>`;
  box.innerHTML = `<div class="hd"><h2>${label ? esc(label) : "Selected area"}</h2><span class="sub">${pc(a.share_of_landings, 1)} of all landings</span></div>
    <div class="kpis" style="grid-template-columns:repeat(2,1fr)">${kpi("Landings", nf(a.landings), `${a.qualifier_landings} qualified`, "hero")}
      ${kpi("Qualified share", pc(a.qualifier_share, 1), `everywhere ${pc(e.qualifier_share, 1)}`, a.qualifier_share > e.qualifier_share ? "good" : "")}
      ${kpi("Points per game", nd(a.avg_points), dlt(a.avg_points, e.avg_points))}
      ${kpi("Average finish", "top " + pc(a.avg_placement_pct), `everywhere top ${pc(e.avg_placement_pct)}`)}
      ${kpi("Early exits", pc(a.early_exit_rate), `everywhere ${pc(e.early_exit_rate)}`, a.early_exit_rate > e.early_exit_rate ? "bad" : "")}
      ${kpi("Wins", pc(a.win_rate, 1), `everywhere ${pc(e.win_rate, 1)}`)}</div>
    <p class="small" style="margin:0 0 8px">Of all teams that qualified, <b>${pc(a.share_of_qualifier_landings, 1)}</b> landed here.${d.pois.length ? " Named spots inside: " + d.pois.map(p => `${esc(p[0])} (${p[1]})`).join(", ") + "." : ""}</p>
    ${Object.keys(d.by_game).length > 1 ? `<div class="small" style="margin-bottom:8px">By game: ${Object.entries(d.by_game).map(([g, n]) => `G${g} <b>${n}</b>`).join(" · ")}</div>` : ""}
    <h3>Best results from here</h3>${table(["Team", "Game", "Pts", "Place", "Final"], d.best.map(b => [esc(b.team), b.game, b.points, "#" + b.placement, b.rank ? "#" + nf(b.rank) : "-"]), ["", "n", "n", "n", "n"])}`;
}

function spotsTable() {
  const p = DR.pois, el = $("#dspots"); if (!el) return;
  if (!p || !p.pois.length) { el.innerHTML = ""; return; }
  const cols = [["name", "Spot", 0], ["landings", "Landings", 1], ["share_of_landings", "% of landings", 1], ["qualifier_share", "Qualified share", 1], ["share_of_qualifier_landings", "% of qualifiers", 1], ["avg_points", "Pts/game", 1], ["avg_placement_pct", "Avg finish", 1], ["early_exit_rate", "Early exit", 1]];
  const rows = p.pois.slice().sort((a, b) => DR.sortBy === "name" ? a.name.localeCompare(b.name) : (DR.sortBy === "avg_placement_pct" || DR.sortBy === "early_exit_rate" ? a[DR.sortBy] - b[DR.sortBy] : b[DR.sortBy] - a[DR.sortBy]));
  const b = p.baseline;
  el.innerHTML = `<div class="card"><div class="hd"><h2>Named spots compared</h2><span class="sub">click a heading to sort, a row to mark it on the map · everywhere: ${pc(b.qualifier_share, 1)} qualified, ${nd(b.avg_points)} pts/game</span></div><div class="scroll"><table><tr>${cols.map(([k, l, n]) => `<th class="${n ? "n" : ""}" data-s="${k}" style="cursor:pointer">${l}${DR.sortBy === k ? " ▾" : ""}</th>`).join("")}</tr>` +
    rows.map(r => `<tr class="dr-row" data-n="${esc(r.name)}" style="cursor:pointer"><td><b>${esc(r.name)}</b></td><td class="n">${nf(r.landings)}</td><td class="n">${pc(r.share_of_landings, 1)}</td><td class="n">${pc(r.qualifier_share, 1)}</td><td class="n">${pc(r.share_of_qualifier_landings, 1)}</td><td class="n">${nd(r.avg_points)}</td><td class="n">top ${pc(r.avg_placement_pct)}</td><td class="n">${pc(r.early_exit_rate)}</td></tr>`).join("") + "</table></div></div>";
  $$("#dspots th").forEach(t => t.onclick = () => { DR.sortBy = t.dataset.s; spotsTable(); });
  $$("#dspots .dr-row").forEach(t => t.onclick = () => { const sp = spotsList().find(s => s.name === t.dataset.n); if (!sp) return; $$(".dr-row.on").forEach(r => r.classList.remove("on")); t.classList.add("on"); const r = Math.max(0.015, sp.r || 0.03); selectPoly(Array.from({ length: 28 }, (_, i) => [sp.x + r * Math.cos(i / 28 * 6.2832), sp.y + r * Math.sin(i / 28 * 6.2832)]), sp.name); $("#dc").scrollIntoView({ behavior: "smooth", block: "center" }); });
}
