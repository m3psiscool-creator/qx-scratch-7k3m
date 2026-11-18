"use strict";
// Map: every map in the game by its in-game name. Maps we have replays for show every container (chests, rare chests, ammo boxes, ...) at its
// real position (read from replays, see worker/landings/Containers.cs); the others show their picture.
const MP = { list: [], key: null, entry: null, info: null, loot: null, grid: null, img: null, z: 1, ox: 0, oy: 0,
  layers: { chests: true, grid: gridPref(false), heat: false }, kinds: { chest: true, rare: true, ammo: false, produce: false, cash: false, fishing: false },
  minRate: 0, sel: null, hover: null, drag: null };
const MP_KINDS = [["chest", "Chests"], ["rare", "Rare chests"], ["ammo", "Ammo boxes"], ["produce", "Produce boxes"], ["cash", "Cash registers"], ["fishing", "Fishing barrels"]];
const MP_KIND_ONE = { chest: "Chest", rare: "Rare chest", ammo: "Ammo box", produce: "Produce box", cash: "Cash register", fishing: "Fishing barrel" };

async function mapPage(arg) {
  MP.info = MP.loot = MP.grid = MP.img = null; MP.z = 1; MP.ox = MP.oy = 0; MP.sel = MP.hover = null;
  app.innerHTML = `<div class="ph"><div><h1>Map</h1><p>Every map by its in-game name. Maps with replay data show every chest, rare chest and ammo box at its real position, coloured by how often it is opened in the first minutes. Drag to move, scroll to zoom, hover for details.</p></div></div>
    <div class="dr-layout"><div class="card dr-pick"><div class="hd"><h2>Maps</h2></div><div class="dr-list" id="mplist">${skel(3, 60)}</div></div><div id="mpmain" class="dr-main"></div></div>`;
  const list = await j("/api/maps");
  MP.list = Array.isArray(list) ? list : [];
  if (!MP.list.length) { $("#mplist").innerHTML = ""; $("#mpmain").innerHTML = `<div class="card err">The map list could not be loaded.</div>`; return; }
  const cur = MP.list.find(m => m.key === arg || m.window_id === arg) || MP.list.find(m => m.window_id) || MP.list[0];
  const modes = [...new Set(MP.list.map(m => m.mode))];
  $("#mplist").innerHTML = modes.map(md => `<div class="small" style="margin:8px 2px 2px;text-transform:uppercase;letter-spacing:.06em">${esc(md)}</div>` + MP.list.filter(m => m.mode === md).map(m =>
    `<a href="#/map/${encodeURIComponent(m.key)}" class="dr-item ${m.key === cur.key ? "on" : ""}"><b>${esc(m.name)}</b><small>${m.window_id ? nf(m.chests) + " chests · " + nf(m.matches) + " matches" : "picture only · no replay data yet"}</small></a>`).join("")).join("");
  MP.key = cur.key; MP.entry = cur;
  await mapLoad(cur);
}

async function mapLoad(m) {
  const box = $("#mpmain"); box.innerHTML = skel(1, 700);
  MP.info = MP.loot = MP.grid = MP.img = null; MP.sel = MP.hover = null; MP.z = 1; MP.ox = MP.oy = 0;
  let info = null, loot = null;
  if (m.window_id) {
    [info, loot] = await Promise.all([j("/api/drops/info?window=" + encodeURIComponent(m.window_id)), j("/api/drops/loot?window=" + encodeURIComponent(m.window_id) + "&cls=all")]);
    if (info.error || loot.error || !loot.sites) { info = loot = null; }
  }
  MP.info = info; MP.loot = loot;
  MP.minRate = m.key === "BR" ? 0.1 : 0;   // BR chests spawn at random places: one seen in under 10% of matches is usually not there in a given game
  const mp = (info && info.map) || {};
  const kinds = (loot && loot.kinds) || {};
  const sites = loot ? loot.sites : [];
  const chestSites = sites.filter(c => (c.cls || "chest") === "chest" || c.cls === "rare");
  const avg = chestSites.length ? chestSites.reduce((s, c) => s + c.rate, 0) / chestSites.length : 0;
  const hot = chestSites.filter(c => c.rate >= 0.6).length, cold = chestSites.filter(c => c.rate < 0.2).length;
  const picture = mp.image ? "" : (m.image ? "" : "");
  box.innerHTML = `<div class="card"><div class="hd"><h2>${esc(m.name)} <span class="pill">${esc(m.mode)}</span></h2><span class="sub">${loot ? nf(loot.chests) + " chests plotted · " + nf(loot.matches) + " matches read" : "picture only"}</span></div>
    ${loot ? `<div class="kpis" style="margin:0 0 12px">${kpi("Chests", nf(kinds.chest || 0), (kinds.rare ? "+ " + nf(kinds.rare) + " rare" : ""))}${kpi("Ammo boxes", nf(kinds.ammo || 0))}${kpi("Opened early, on average", pc(avg, 0), "share of games")}${kpi("Often opened (60%+)", nf(hot), nf(cold) + " rarely (under 20%)")}</div>
    <div class="chips" id="mpkinds" style="margin:0 0 8px">${MP_KINDS.filter(([k]) => kinds[k]).map(([k, l]) => `<button class="chip ${MP.kinds[k] ? "on" : ""}" data-k="${k}">${l} <small>${nf(kinds[k])}</small></button>`).join("")}</div>` : `<p class="mut">There is no replay data for this map yet, so no chest positions: the picture is the map as the game draws it. Chests appear here as soon as a tournament is played on it and its replays are read.</p>`}
    <div class="chips" id="mplay" style="margin:0 0 8px"><button class="chip ${MP.layers.grid ? "on" : ""}" data-l="grid">Grid</button>${loot ? `<button class="chip" data-l="heat">Where teams land</button>` : ""}
      <span style="flex:1"></span><button class="chip" id="mpz1">Zoom +</button><button class="chip" id="mpz2">Zoom −</button><button class="chip" id="mpreset">Reset view</button></div>
    ${loot ? `<div style="margin:0 0 10px"><label>Show chests opened in at least <b id="mpminv">${Math.round(MP.minRate * 100)}%</b> of games</label><input id="mpmin" type="range" min="0" max="100" value="${Math.round(MP.minRate * 100)}"></div>` : ""}
    <div class="dr-canvas" style="position:relative"><canvas id="mpc"></canvas><div id="mptip" class="mp-tip" style="display:none"></div></div>
    ${loot ? `<div class="mp-legend"><span>rarely opened</span><i></i><span>opened in most games</span></div>` : ""}
    <p class="small">${mp.credit ? esc(mp.credit) + ". " : (m.image ? "Map picture: Epic Games. " : "No picture of this map is available. ")}${loot ? `Each icon is one container at the position players stood when they searched it, read from ${nf(loot.matches)} real matches (the same chest gives the same spot in every match, within about a metre). Colour = share of games in which it was opened in the first minutes.` : ""}</p></div>
    ${loot ? `<div class="card"><div class="hd"><h2>Most and least contested chests</h2><span class="sub">click a row to find it on the map</span></div><div id="mplist2"></div></div>` : ""}`;
  const imgUrl = (info && mp.image) || m.image || "";
  if (imgUrl) { const im = new Image(); im.onload = () => { MP.img = (info && mp.fit) ? warp(im, mp.fit) : im; mapDraw(); }; im.src = imgUrl; }
  $$("#mpkinds button").forEach(b => b.onclick = () => { MP.kinds[b.dataset.k] = !MP.kinds[b.dataset.k]; b.classList.toggle("on", MP.kinds[b.dataset.k]); mapDraw(); mapRows(); });
  $$("#mplay button[data-l]").forEach(b => b.onclick = async () => {
    const l = b.dataset.l; MP.layers[l] = !MP.layers[l]; b.classList.toggle("on", MP.layers[l]); if (l === "grid") gridSave(MP.layers.grid);
    if (l === "heat" && MP.layers.heat && !MP.grid) { MP.grid = await j(`/api/drops/grid?window=${encodeURIComponent(m.window_id)}&top=1000`); }
    mapDraw();
  });
  if ($("#mpmin")) $("#mpmin").oninput = e => { MP.minRate = +e.target.value / 100; $("#mpminv").textContent = e.target.value + "%"; mapDraw(); mapRows(); };
  $("#mpz1").onclick = () => mapZoom(1.4); $("#mpz2").onclick = () => mapZoom(1 / 1.4);
  $("#mpreset").onclick = () => { MP.z = 1; MP.ox = MP.oy = 0; mapDraw(); };
  mapWire(); mapRows(); mapDraw();
}

// frame (0-1) <-> canvas pixels
function mapS() { return $("#mpc").width * MP.z; }
function mapPx(x, y) { const S = mapS(); return [MP.ox + x * S, MP.oy + y * S]; }
function mapRate(r) { return `hsl(${Math.round(130 * (1 - Math.min(1, Math.max(0, r))))}, 85%, 52%)`; }
function mapVisible() { return (MP.loot ? MP.loot.sites : []).filter(c => c.rate >= MP.minRate && MP.kinds[c.cls || "chest"]); }

function mapSize() {
  const c = $("#mpc"); if (!c) return;
  const w = c.parentElement.clientWidth, d = Math.min(2, window.devicePixelRatio || 1), px = Math.round(w * d);
  if (c.width !== px) { const k = px / (c.width || px); c.width = c.height = px; MP.ox *= k; MP.oy *= k; }
  c.style.height = w + "px";
}
function mapDraw() {
  const c = $("#mpc"); if (!c) return; mapSize();
  const x = c.getContext("2d"), W = c.width, S = mapS();
  x.fillStyle = "#0d2748"; x.fillRect(0, 0, W, W);
  if (MP.img) {
    if (MP.loot) x.drawImage(MP.img, MP.ox, MP.oy, S, S);
    else { const iw = MP.img.width || MP.img.naturalWidth || 1, ih = MP.img.height || MP.img.naturalHeight || 1, k = Math.min(S / iw, S / ih); x.drawImage(MP.img, MP.ox + (S - iw * k) / 2, MP.oy + (S - ih * k) / 2, iw * k, ih * k); }
  }
  if (!MP.loot) return;
  if (MP.layers.heat && MP.grid && MP.grid.all) {
    const n = MP.grid.size, cell = S / n, mx = Math.max(1, ...MP.grid.all.map(a => a[1]));
    x.fillStyle = "rgba(255,200,40,0.55)";
    MP.grid.all.forEach(([i, v]) => { x.globalAlpha = 0.25 + 0.6 * Math.sqrt(v / mx); x.fillRect(MP.ox + (i % n) * cell, MP.oy + Math.floor(i / n) * cell, cell, cell); });
    x.globalAlpha = 1;
  }
  if (MP.layers.grid) {
    x.strokeStyle = "rgba(255,255,255,0.35)"; x.lineWidth = 1; x.fillStyle = "rgba(255,255,255,0.85)"; x.font = `${Math.max(11, 13 * (W / 900))}px sans-serif`;
    for (let i = 0; i <= 10; i++) { const [a, b] = mapPx(i / 10, i / 10); x.beginPath(); x.moveTo(a, MP.oy); x.lineTo(a, MP.oy + S); x.moveTo(MP.ox, b); x.lineTo(MP.ox + S, b); x.stroke(); }
    for (let i = 0; i < 10; i++) { const [a, b] = mapPx((i + 0.5) / 10, (i + 0.5) / 10); x.fillText("ABCDEFGHIJ"[i], a - 4, MP.oy + 14 * (W / 900) + 2); x.fillText(String(i + 1), MP.ox + 4, b + 4); }
  }
  const d = Math.min(2, window.devicePixelRatio || 1), r = Math.max(4, Math.min(14, (2.2 + 2.7 * Math.sqrt(MP.z)) * d));
  mapVisible().forEach(s => {
    const [a, b] = mapPx(s.x, s.y); if (a < -20 || b < -20 || a > W + 20 || b > W + 20) return;
    drawChest(x, a, b, r, mapRate(s.rate), s.cls || "chest");
  });
  [MP.sel, MP.hover].forEach(s => { if (!s) return; const [a, b] = mapPx(s.x, s.y); x.beginPath(); x.arc(a, b, r * 1.45 + 4 * d, 0, 7); x.lineWidth = 2.4 * d; x.strokeStyle = "#fff"; x.stroke(); });
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
  t.innerHTML = `<b>${MP_KIND_ONE[s.cls || "chest"]} · ${mapLabel(s)}</b><br>opened early in ${pc(s.rate, 0)} of games`;
  t.style.display = "block"; t.style.left = Math.min(r.width - 190, ev.clientX - r.left + 14) + "px"; t.style.top = Math.max(4, ev.clientY - r.top - 12) + "px";
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
  const v = mapVisible().filter(c => (c.cls || "chest") === "chest" || c.cls === "rare");
  const top = v.slice().sort((a, b) => b.rate - a.rate).slice(0, 8), low = v.slice().sort((a, b) => a.rate - b.rate).slice(0, 8);
  const row = s => `<tr class="mp-row" data-x="${s.x}" data-y="${s.y}"><td>${mapLabel(s)}</td><td class="n">${pc(s.rate, 0)}</td></tr>`;
  const tbl = (h, a) => `<div><h3 style="margin:0 0 6px;font-size:.95rem">${h}</h3><table><tr><th>Grid</th><th class="n">Opened early</th></tr>${a.map(row).join("")}</table></div>`;
  box.innerHTML = `<div class="grid g2">${tbl("Most contested (opened in the most games)", top)}${tbl("Least contested (best for avoiding fights)", low)}</div>`;
  $$("#mplist2 .mp-row").forEach(t => t.onclick = () => {
    const s = MP.loot.sites.find(q => q.x == t.dataset.x && q.y == t.dataset.y); if (!s) return;
    MP.sel = s; MP.z = Math.max(MP.z, 4); const c = $("#mpc"), S = mapS(); MP.ox = c.width / 2 - s.x * S; MP.oy = c.width / 2 - s.y * S; mapClamp(); mapDraw();
    c.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}
