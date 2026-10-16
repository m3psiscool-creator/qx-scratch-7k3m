"use strict";
// Map: an interactive map of every map we have chest data for, with every chest plotted.
// Chest sites come from real match loot (see drops.py _sites); the picture is the map's real texture (drops.MAPS).
const MP = { list: [], wid: null, info: null, loot: null, grid: null, img: null, z: 1, ox: 0, oy: 0, layers: { chests: true, grid: false, heat: false }, minRate: 0, maxRate: 1, sel: null, hover: null, drag: null };

async function mapPage(wid) {
  MP.info = MP.loot = MP.grid = MP.img = null; MP.z = 1; MP.ox = MP.oy = 0; MP.sel = MP.hover = null;
  app.innerHTML = `<div class="ph"><div><h1>Map</h1><p>Every chest on the map, plotted from real match loot. Drag to move, scroll to zoom, hover a dot for details. Colour shows how often that chest is opened in the first minutes of a game.</p></div></div>
    <div class="dr-layout"><div class="card dr-pick"><div class="hd"><h2>Maps</h2></div><div class="dr-list" id="mplist">${skel(2, 70)}</div></div><div id="mpmain" class="dr-main"></div></div>`;
  const list = await j("/api/maps");
  MP.list = Array.isArray(list) ? list : [];
  if (!MP.list.length) { $("#mplist").innerHTML = ""; $("#mpmain").innerHTML = `<div class="card empty">No map has enough processed matches yet. The scheduled job adds matches every few hours.</div>`; return; }
  const cur = MP.list.find(m => m.window_id === wid) || MP.list[0];
  $("#mplist").innerHTML = MP.list.map(m => `<a href="#/map/${encodeURIComponent(m.window_id)}" class="dr-item ${m.window_id === cur.window_id ? "on" : ""}"><b>${esc(m.name)}</b><small>${nf(m.chests)} chests plotted · ${nf(m.matches)} matches</small></a>`).join("");
  MP.wid = cur.window_id;
  await mapLoad(cur);
}

async function mapLoad(m) {
  const box = $("#mpmain"); box.innerHTML = skel(1, 700);
  const [info, loot] = await Promise.all([j("/api/drops/info?window=" + encodeURIComponent(m.window_id)), j("/api/drops/loot?window=" + encodeURIComponent(m.window_id))]);
  if (info.error || loot.error || !loot.sites) { box.innerHTML = `<div class="card err">${esc(info.error || loot.error || "No chest data.")}</div>`; return; }
  MP.info = info; MP.loot = loot;
  const sites = loot.sites;
  const avg = sites.reduce((s, c) => s + c.rate * c.chests, 0) / Math.max(1, sites.reduce((s, c) => s + c.chests, 0));
  const hot = sites.filter(c => c.rate >= 0.6).length, cold = sites.filter(c => c.rate < 0.2).length;
  const mp = info.map || {};
  box.innerHTML = `<div class="card"><div class="hd"><h2>${esc(mp.name || m.name)}</h2><span class="sub">${nf(loot.chests)} chests plotted · ${nf(loot.matches)} matches behind them</span></div>
    <div class="kpis" style="margin:0 0 12px">${kpi("Chests plotted", nf(loot.chests))}${kpi("Opened early, on average", pc(avg, 0), "share of games")}${kpi("Often opened (60%+)", nf(hot))}${kpi("Rarely opened (under 20%)", nf(cold))}</div>
    <div class="chips" id="mplay" style="margin:0 0 8px"><button class="chip on" data-l="chests">Chests</button><button class="chip" data-l="grid">Grid</button><button class="chip" data-l="heat">Where teams land</button>
      <span style="flex:1"></span><button class="chip" id="mpz1">Zoom +</button><button class="chip" id="mpz2">Zoom −</button><button class="chip" id="mpreset">Reset view</button></div>
    <div style="margin:0 0 10px"><label>Show chests opened in at least <b id="mpminv">0%</b> of games</label><input id="mpmin" type="range" min="0" max="100" value="0"></div>
    <div class="dr-canvas" style="position:relative"><canvas id="mpc"></canvas><div id="mptip" class="mp-tip" style="display:none"></div></div>
    <div class="mp-legend"><span>rarely opened</span><i></i><span>opened in most games</span></div>
    ${mp.image ? "" : `<p class="small">${esc(info.note || "No picture of this map is available yet.")} The chests are still placed where they were found.</p>`}
    <p class="small">${mp.credit ? esc(mp.credit) + ". " : ""}A dot is one chest position found from real match loot; ${nf(loot.matches)} matches were read. Colour = share of games in which that chest was opened in the first minutes.</p></div>
    <div class="card"><div class="hd"><h2>Most and least contested chests</h2><span class="sub">click a row to find it on the map</span></div><div id="mplist2"></div></div>`;
  const imgUrl = mp.image || "";
  if (imgUrl) { const im = new Image(); im.onload = () => { MP.img = mp.fit ? warp(im, mp.fit) : im; mapDraw(); }; im.src = imgUrl; }
  $$("#mplay button[data-l]").forEach(b => b.onclick = async () => {
    const l = b.dataset.l; MP.layers[l] = !MP.layers[l]; b.classList.toggle("on", MP.layers[l]);
    if (l === "heat" && MP.layers.heat && !MP.grid) { MP.grid = await j(`/api/drops/grid?window=${encodeURIComponent(MP.wid)}&top=1000`); }
    mapDraw();
  });
  $("#mpmin").oninput = e => { MP.minRate = +e.target.value / 100; $("#mpminv").textContent = e.target.value + "%"; mapDraw(); mapRows(); };
  $("#mpz1").onclick = () => mapZoom(1.4); $("#mpz2").onclick = () => mapZoom(1 / 1.4);
  $("#mpreset").onclick = () => { MP.z = 1; MP.ox = MP.oy = 0; mapDraw(); };
  mapWire(); mapRows(); mapDraw();
}

// frame (0-1) <-> canvas pixels
function mapS() { return $("#mpc").width * MP.z; }
function mapPx(x, y) { const S = mapS(); return [MP.ox + x * S, MP.oy + y * S]; }
function mapRate(r) { return `hsl(${Math.round(130 * (1 - Math.min(1, Math.max(0, r))))}, 85%, 52%)`; }
function mapVisible() { return (MP.loot ? MP.loot.sites : []).filter(c => c.rate >= MP.minRate); }

function mapSize() {
  const c = $("#mpc"); if (!c) return;
  const w = c.parentElement.clientWidth, d = Math.min(2, window.devicePixelRatio || 1), px = Math.round(w * d);
  if (c.width !== px) { const k = px / (c.width || px); c.width = c.height = px; MP.ox *= k; MP.oy *= k; }
  c.style.height = w + "px";
}
function mapDraw() {
  const c = $("#mpc"); if (!c || !MP.loot) return; mapSize();
  const x = c.getContext("2d"), W = c.width, S = mapS();
  x.fillStyle = "#0d2748"; x.fillRect(0, 0, W, W);
  if (MP.img) x.drawImage(MP.img, MP.ox, MP.oy, S, S);
  if (MP.layers.heat && MP.grid && MP.grid.all) {
    const n = MP.grid.size, cell = S / n, mx = Math.max(1, ...MP.grid.all.map(a => a[1]));
    x.fillStyle = "rgba(255,200,40,0.55)";
    MP.grid.all.forEach(([i, v]) => { x.globalAlpha = 0.25 + 0.6 * Math.sqrt(v / mx); x.fillRect(MP.ox + (i % n) * cell, MP.oy + Math.floor(i / n) * cell, cell, cell); });
    x.globalAlpha = 1;
  }
  if (MP.layers.grid) {
    x.strokeStyle = "rgba(255,255,255,0.35)"; x.lineWidth = 1; x.fillStyle = "rgba(255,255,255,0.8)"; x.font = `${Math.max(11, 13 * (W / 900))}px sans-serif`;
    for (let i = 0; i <= 10; i++) { const [a, b] = mapPx(i / 10, i / 10); x.beginPath(); x.moveTo(a, MP.oy); x.lineTo(a, MP.oy + S); x.moveTo(MP.ox, b); x.lineTo(MP.ox + S, b); x.stroke(); }
    for (let i = 0; i < 10; i++) { const [a, b] = mapPx((i + 0.5) / 10, (i + 0.5) / 10); x.fillText("ABCDEFGHIJ"[i], a - 4, MP.oy + 14 * (W / 900) + 2); x.fillText(String(i + 1), MP.ox + 4, b + 4); }
  }
  if (MP.layers.chests) {
    const d = Math.min(2, window.devicePixelRatio || 1), r = Math.max(3.2, Math.min(11, (2.6 + 2.2 * Math.sqrt(MP.z)) * d));
    mapVisible().forEach(s => {
      const [a, b] = mapPx(s.x, s.y); if (a < -20 || b < -20 || a > W + 20 || b > W + 20) return;
      x.beginPath(); x.arc(a, b, r + (s.chests > 1 ? 1.5 : 0), 0, 7);
      x.fillStyle = mapRate(s.rate); x.fill(); x.lineWidth = 1.4 * d; x.strokeStyle = "rgba(10,12,20,0.9)"; x.stroke();
      if (s.chests > 1 && MP.z > 1.6) { x.fillStyle = "#101522"; x.font = `bold ${r * 1.2}px sans-serif`; x.textAlign = "center"; x.fillText(s.chests, a, b + r * 0.42); x.textAlign = "start"; }
    });
    [MP.sel, MP.hover].forEach(s => { if (!s) return; const [a, b] = mapPx(s.x, s.y); x.beginPath(); x.arc(a, b, r + 5 * d, 0, 7); x.lineWidth = 2.4 * d; x.strokeStyle = "#fff"; x.stroke(); });
  }
}
function mapZoom(f, cx, cy) {
  const c = $("#mpc"); if (!c) return; const z2 = Math.min(14, Math.max(1, MP.z * f)); f = z2 / MP.z;
  cx = cx ?? c.width / 2; cy = cy ?? c.width / 2;
  MP.ox = cx - (cx - MP.ox) * f; MP.oy = cy - (cy - MP.oy) * f; MP.z = z2; mapClamp(); mapDraw();
}
function mapClamp() { const c = $("#mpc"), S = mapS(), W = c.width; MP.ox = Math.min(W * 0.15, Math.max(W * 0.85 - S, MP.ox)); MP.oy = Math.min(W * 0.15, Math.max(W * 0.85 - S, MP.oy)); }
function mapNear(ev) {
  const c = $("#mpc"), r = c.getBoundingClientRect(), k = c.width / r.width, mx = (ev.clientX - r.left) * k, my = (ev.clientY - r.top) * k;
  let best = null, bd = (14 * k) ** 2;
  mapVisible().forEach(s => { const [a, b] = mapPx(s.x, s.y), d = (a - mx) ** 2 + (b - my) ** 2; if (d < bd) { bd = d; best = s; } });
  return { s: best, mx, my, k };
}
function mapLabel(s) { return "ABCDEFGHIJ"[Math.min(9, Math.floor(s.x * 10))] + (Math.min(9, Math.floor(s.y * 10)) + 1); }
function mapTip(s, ev) {
  const t = $("#mptip"); if (!t) return;
  if (!s) { t.style.display = "none"; return; }
  const r = $("#mpc").getBoundingClientRect();
  t.innerHTML = `<b>${s.chests > 1 ? s.chests + " chests" : "Chest"} · ${mapLabel(s)}</b><br>opened early in ${pc(s.rate, 0)} of games`;
  t.style.display = "block"; t.style.left = Math.min(r.width - 170, ev.clientX - r.left + 14) + "px"; t.style.top = Math.max(4, ev.clientY - r.top - 12) + "px";
}
function mapWire() {
  const c = $("#mpc"); if (!c) return;
  c.style.touchAction = "none"; c.style.cursor = "grab";
  c.onwheel = e => { e.preventDefault(); const q = mapNear(e); mapZoom(e.deltaY < 0 ? 1.25 : 0.8, q.mx, q.my); };
  c.onpointerdown = e => { c.setPointerCapture(e.pointerId); MP.drag = { x: e.clientX, y: e.clientY, ox: MP.ox, oy: MP.oy, moved: false }; c.style.cursor = "grabbing"; };
  c.onpointermove = e => {
    if (MP.drag) {
      const r = c.getBoundingClientRect(), k = c.width / r.width, dx = (e.clientX - MP.drag.x) * k, dy = (e.clientY - MP.drag.y) * k;
      if (Math.abs(dx) + Math.abs(dy) > 3) MP.drag.moved = true;
      MP.ox = MP.drag.ox + dx; MP.oy = MP.drag.oy + dy; mapClamp(); mapDraw(); return;
    }
    const q = mapNear(e); if (q.s !== MP.hover) { MP.hover = q.s; mapDraw(); } mapTip(q.s, e);
  };
  c.onpointerup = e => {
    const was = MP.drag; MP.drag = null; c.style.cursor = "grab";
    if (was && !was.moved) { const q = mapNear(e); MP.sel = q.s; mapDraw(); }
  };
  c.onpointerleave = () => { MP.hover = null; mapTip(null); mapDraw(); };
  c.ondblclick = e => { const q = mapNear(e); mapZoom(2, q.mx, q.my); };
  if (!MP.resizing) { MP.resizing = true; window.addEventListener("resize", () => { if ($("#mpc")) mapDraw(); }); }
}
function mapRows() {
  const box = $("#mplist2"); if (!box || !MP.loot) return;
  const v = mapVisible().slice();
  const top = v.slice().sort((a, b) => b.rate - a.rate).slice(0, 8), low = v.slice().sort((a, b) => a.rate - b.rate).slice(0, 8);
  const row = s => `<tr class="mp-row" data-x="${s.x}" data-y="${s.y}"><td>${mapLabel(s)}</td><td class="n">${s.chests}</td><td class="n">${pc(s.rate, 0)}</td></tr>`;
  const tbl = (h, a) => `<div><h3 style="margin:0 0 6px;font-size:.95rem">${h}</h3><table><tr><th>Grid</th><th class="n">Chests</th><th class="n">Opened early</th></tr>${a.map(row).join("")}</table></div>`;
  box.innerHTML = `<div class="grid g2">${tbl("Most contested (opened in the most games)", top)}${tbl("Least contested (best for avoiding fights)", low)}</div>`;
  $$("#mplist2 .mp-row").forEach(t => t.onclick = () => {
    const s = MP.loot.sites.find(q => q.x == t.dataset.x && q.y == t.dataset.y); if (!s) return;
    MP.sel = s; MP.z = Math.max(MP.z, 4); const c = $("#mpc"), S = mapS(); MP.ox = c.width / 2 - s.x * S; MP.oy = c.width / 2 - s.y * S; mapClamp(); mapDraw();
    c.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}
