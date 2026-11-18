"use strict";
// Rotations: where everyone moved in one match. Search a player, open one of their games, then watch every team move over the map
// with the storm circles, or click a team to follow it. Data: worker/run.mjs --tracks (full replays), /api/tracks/*.
const RT = { g: null, info: null, img: null, t: 0, speed: 8, playing: false, sel: null, trails: true, storm: true, grid: gridPref(false), qOnly: false, z: 1, ox: 0, oy: 0, drag: null, raf: 0, last: 0, W: 800 };

async function rotationsPage(arg) {
  cancelAnimationFrame(RT.raf); RT.playing = false;
  if (arg) return rotGame(arg);
  app.innerHTML = `<div class="ph"><div><h1>Rotations</h1><p>See where everyone moved in a game: the drop, every rotation, and the storm. Search a player, open one of their games, and follow any team.</p></div></div>
    <div class="grid g2" style="align-items:start"><div class="card"><div class="hd"><h2>Find a player</h2></div><div class="row"><div><input id="rq" placeholder="Epic name"></div><div style="flex:0"><button id="rb">Search</button></div></div><div id="rres" class="small" style="margin-top:10px"></div><div id="rgames" style="margin-top:10px"></div></div>
    <div class="card"><div class="hd"><h2>Games with movement data</h2><span class="sub">the most recent ones</span></div><div id="rrecent">${skel(1, 120)}</div></div></div>`;
  const search = async () => {
    const q = $("#rq").value.trim(); if (!q) return;
    $("#rres").innerHTML = "Searching…";
    const r = await j("/api/players?q=" + encodeURIComponent(q));
    $("#rres").innerHTML = Array.isArray(r) && r.length ? r.slice(0, 12).map(p => `<button class="chip" data-a="${esc(p.id)}">${esc(p.name)}</button>`).join(" ") : '<span class="mut">No player with that name. Only players we have read replays for (and top-1,000 finishers) can be found.</span>';
    $$("#rres [data-a]").forEach(b => b.onclick = () => rotPlayer(b.dataset.a));
  };
  $("#rb").onclick = search; $("#rq").onkeydown = e => { if (e.key === "Enter") search(); };
  const rec = await j("/api/tracks/recent");
  $("#rrecent").innerHTML = Array.isArray(rec) && rec.length ? table(["Event", "Region", "Length", "Players", ""], rec.map(r => [esc(r.event), esc(r.region || ""), Math.round(r.duration / 60) + " min", r.players, `<a href="#/rotations/${esc(r.session)}">Open ›</a>`]), ["", "", "n", "n", ""])
    : '<p class="mut">No game has movement data yet. The scheduled job reads full replays for a few matches of each tournament.</p>';
}
async function rotPlayer(acc) {
  const box = $("#rgames"); box.innerHTML = skel(1, 100);
  const d = await j("/api/tracks/player?account=" + encodeURIComponent(acc));
  if (d.error) { box.innerHTML = `<p class="err">${esc(d.error)}</p>`; return; }
  box.innerHTML = `<h3 style="margin:6px 0">${esc(d.name)}</h3>` + (d.games.length ? table(["Event", "Game", "Finish", "Kills", "Final", ""], d.games.map(g => [esc(g.event) + " <small>" + esc(g.region || "") + "</small>", g.game || "-", "#" + g.placement, g.kills, g.rank ? "#" + nf(g.rank) : "-", `<a href="#/rotations/${esc(g.session)}">Open ›</a>`]), ["", "n", "n", "n", "n", ""])
    : '<p class="mut">None of this player\'s games has movement data yet. Movement is read for the matches with the most qualifying teams, so it can take a while.</p>');
}

const rotColor = (ti, bright) => `hsl(${Math.round((ti * 137.5) % 360)}, ${bright ? 85 : 25}%, ${bright ? 58 : 45}%)`;
const rotMmss = s => Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");

async function rotGame(session) {
  app.innerHTML = `<div class="crumb"><a href="#/rotations">Rotations</a> ›</div><div id="rgame">${skel(1, 600)}</div>`;
  const g = await j("/api/tracks/game?session=" + encodeURIComponent(session));
  if (g.error) { $("#rgame").innerHTML = `<div class="card err">${esc(g.error)}</div>`; return; }
  RT.g = g; RT.t = 0; RT.sel = null; RT.z = 1; RT.ox = RT.oy = 0; RT.img = null;
  const info = await j("/api/drops/info?window=" + encodeURIComponent(g.window_id)); RT.info = info.error ? null : info;
  const goal = g.goal ? g.goal.rank : null;
  g.teams.forEach(t => { t.q = t.rank && goal ? t.rank <= goal : false; t.color = rotColor(t.team, true); });
  g.byTeam = {}; g.tracks.forEach(p => { (g.byTeam[p.t] = g.byTeam[p.t] || []).push(p); });
  $("#rgame").innerHTML = `<div class="card"><div class="hd"><h2>${esc(g.event)} <span class="pill">${esc(g.region || "")}</span></h2><span class="sub">${Math.round(g.duration / 60)} min · ${g.tracks.length} players · ${g.teams.length} teams</span></div>
    <div class="chips" style="margin-bottom:8px"><button class="chip on" id="rplay">▶ Play</button><button class="chip" id="rs1">1×</button><button class="chip" id="rs2">4×</button><button class="chip on" id="rs3">8×</button><button class="chip" id="rs4">30×</button>
      <label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="rtr" checked> Trails</label><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="rst" checked> Storm</label><label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="rgr" ${RT.grid ? "checked" : ""}> Grid</label>
      ${goal ? `<label class="chk" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="rq"> Only teams that finished top ${nf(goal)}</label>` : ""}<span style="flex:1"></span><b id="rtime">0:00</b></div>
    <input id="rslider" type="range" min="0" max="${g.duration}" value="0" style="width:100%"><div class="rt-grid"><div class="dr-canvas" style="position:relative"><canvas id="rc"></canvas></div><div id="rside"></div></div>
    <p class="small">Each dot is a player (a cross is where they were eliminated); the line behind it is where they have been. White circle = the safe zone, dashed = the next one. Click a team to follow it.</p></div>`;
  const imgUrl = RT.info && RT.info.map && RT.info.map.image;
  if (imgUrl) { const im = new Image(); im.onload = () => { RT.img = RT.info.map.fit ? warp(im, RT.info.map.fit) : im; rotDraw(); }; im.src = imgUrl; }
  $("#rplay").onclick = () => { RT.playing = !RT.playing; $("#rplay").textContent = RT.playing ? "❚❚ Pause" : "▶ Play"; $("#rplay").classList.toggle("on", RT.playing); if (RT.playing) { RT.last = performance.now(); rotLoop(); } };
  [[1, 1], [2, 4], [3, 8], [4, 30]].forEach(([i, sp]) => $("#rs" + i).onclick = () => { RT.speed = sp; [1, 2, 3, 4].forEach(k => $("#rs" + k).classList.toggle("on", k === i)); });
  $("#rtr").onchange = e => { RT.trails = e.target.checked; rotDraw(); }; $("#rst").onchange = e => { RT.storm = e.target.checked; rotDraw(); }; $("#rgr").onchange = e => { RT.grid = e.target.checked; gridSave(RT.grid); rotDraw(); };
  if ($("#rq")) $("#rq").onchange = e => { RT.qOnly = e.target.checked; rotDraw(); rotSide(); };
  $("#rslider").oninput = e => { RT.t = +e.target.value; rotDraw(); rotSide(); };
  rotWire(); RT.playing = true; RT.last = performance.now(); $("#rplay").textContent = "❚❚ Pause"; rotLoop(); rotSide(); rotDraw();
}
function rotLoop() {
  cancelAnimationFrame(RT.raf);
  const step = now => {
    if (!RT.playing || !$("#rc")) return;
    RT.t = Math.min(RT.g.duration, RT.t + (now - RT.last) / 1000 * RT.speed); RT.last = now;
    $("#rslider").value = RT.t; rotDraw();
    if (Math.floor(RT.t) % 5 === 0) rotSide();
    if (RT.t >= RT.g.duration) { RT.playing = false; $("#rplay").textContent = "▶ Play"; $("#rplay").classList.remove("on"); return; }
    RT.raf = requestAnimationFrame(step);
  };
  RT.raf = requestAnimationFrame(step);
}
// position of a player at time t (linear between the samples); null before the first sample
// samples outside the map are the pre-game island: never drawn, never joined to the match
const rotIn = s => { const k = RT.g.scale; return s[1] > -0.08 * k && s[1] < 1.08 * k && s[2] > -0.08 * k && s[2] < 1.08 * k; };
function rotAt(p, t) {
  const a = p.p; if (!a.length || t < a[0][0]) return null;
  if (t >= a[a.length - 1][0]) return rotIn(a[a.length - 1]) ? a[a.length - 1] : null;
  let lo = 0, hi = a.length - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (a[m][0] <= t) lo = m; else hi = m; }
  if (!rotIn(a[lo]) || !rotIn(a[hi])) return null;
  const f = (t - a[lo][0]) / Math.max(1, a[hi][0] - a[lo][0]); return [t, a[lo][1] + (a[hi][1] - a[lo][1]) * f, a[lo][2] + (a[hi][2] - a[lo][2]) * f, a[lo][3]];
}
const rotDead = (p, t) => p.x && t >= p.x[2];
function rotStorm(t) {   // current and next circle at time t, in fractions of the map
  const S = RT.g.storm, sc = RT.g.scale; let cur = null, next = null, prev = { r: 1.2, x: 0.5, y: 0.5 };
  for (const z of S) {
    const [ti, , , , nr, nx, ny, st, fi] = z;
    if (t >= ti) next = { r: nr / sc, x: nx / sc, y: ny / sc, st, fi };
    if (t >= st) { const f = t >= fi ? 1 : (t - st) / Math.max(1, fi - st); cur = { r: prev.r + (nr / sc - prev.r) * f, x: prev.x + (nx / sc - prev.x) * f, y: prev.y + (ny / sc - prev.y) * f }; }
    if (t >= fi) prev = { r: nr / sc, x: nx / sc, y: ny / sc };
  }
  return { cur, next: next && t < next.fi ? next : null };   // the next circle is shown dashed until the zone has finished closing onto it
}
function rotView() { const c = $("#rc"), S = c.width * RT.z; return (u, v) => [RT.ox + u * S, RT.oy + v * S]; }
function rotDraw() {
  const c = $("#rc"); if (!c || !RT.g) return;
  const w = c.parentElement.clientWidth, d = Math.min(2, window.devicePixelRatio || 1), px = Math.round(w * d);
  if (c.width !== px) { c.width = c.height = px; } c.style.height = w + "px";
  const x = c.getContext("2d"), W = c.width, S = W * RT.z, P = rotView(), g = RT.g, sc = g.scale, t = RT.t;
  x.fillStyle = "#0d2748"; x.fillRect(0, 0, W, W);
  if (RT.img) { x.drawImage(RT.img, RT.ox, RT.oy, S, S); x.fillStyle = "rgba(8,10,16,.35)"; x.fillRect(RT.ox, RT.oy, S, S); }
  if (RT.grid) {   // A1-J10, same squares as the Dropspots and Map tabs
    x.strokeStyle = "rgba(255,255,255,0.35)"; x.lineWidth = 1; x.fillStyle = "rgba(255,255,255,0.85)"; x.font = `${Math.max(11, 13 * (W / 900))}px sans-serif`;
    for (let i = 0; i <= 10; i++) { const [a, b] = P(i / 10, i / 10); x.beginPath(); x.moveTo(a, RT.oy); x.lineTo(a, RT.oy + S); x.moveTo(RT.ox, b); x.lineTo(RT.ox + S, b); x.stroke(); }
    for (let i = 0; i < 10; i++) { const [a, b] = P((i + 0.5) / 10, (i + 0.5) / 10); x.fillText("ABCDEFGHIJ"[i], a - 4, RT.oy + 14 * (W / 900) + 2); x.fillText(String(i + 1), RT.ox + 4, b + 4); }
  }
  if ($("#rtime")) $("#rtime").textContent = rotMmss(t);
  if (RT.storm) {
    const z = rotStorm(t);
    if (z.next) { const [a, b] = P(z.next.x, z.next.y); x.beginPath(); x.arc(a, b, z.next.r * S, 0, 7); x.setLineDash([8 * d, 6 * d]); x.lineWidth = 2 * d; x.strokeStyle = "rgba(160,210,255,.9)"; x.stroke(); x.setLineDash([]); }
    if (z.cur) { const [a, b] = P(z.cur.x, z.cur.y); x.save(); x.beginPath(); x.rect(RT.ox, RT.oy, S, S); x.arc(a, b, Math.max(0, z.cur.r * S), 0, 7, true); x.fillStyle = "rgba(120,40,200,.30)"; x.fill("evenodd"); x.restore();
      x.beginPath(); x.arc(a, b, Math.max(0, z.cur.r * S), 0, 7); x.lineWidth = 2.5 * d; x.strokeStyle = "#fff"; x.stroke(); }
  }
  const sel = RT.sel, teamShown = ti => { const tm = g.teams.find(q => q.team === ti); return !RT.qOnly || (tm && tm.q) || ti === sel; };
  // trails first, dots on top
  g.tracks.forEach(p => {
    if (!teamShown(p.t)) return; const tm = g.teams.find(q => q.team === p.t), hot = sel === p.t, dim = sel != null && !hot;
    if (RT.trails || hot) {
      x.beginPath(); let started = false;
      for (const s of p.p) { if (s[0] > t) break; if (s[3] > 250 || !rotIn(s)) { started = false; continue; } const [a, b] = P(s[1] / sc, s[2] / sc); started ? x.lineTo(a, b) : x.moveTo(a, b); started = true; }
      const cur = rotAt(p, t); if (cur && cur[3] <= 250 && started) { const [a, b] = P(cur[1] / sc, cur[2] / sc); x.lineTo(a, b); }
      x.lineWidth = (hot ? 3.2 : 1.3) * d; x.strokeStyle = hot ? tm.color : (tm.q || !dim ? tm.color : "rgba(190,200,215,.5)"); x.globalAlpha = hot ? 1 : dim ? 0.18 : (tm.q ? 0.75 : 0.4); x.stroke(); x.globalAlpha = 1;
    }
  });
  g.tracks.forEach(p => {
    if (!teamShown(p.t)) return; const tm = g.teams.find(q => q.team === p.t), hot = sel === p.t, dim = sel != null && !hot;
    const cur = rotAt(p, t); if (!cur) return;
    const [a, b] = P(cur[1] / sc, cur[2] / sc), r = (hot ? 6 : 4) * d;
    if (rotDead(p, t)) { const [ex, ey] = P(p.x[0] / sc, p.x[1] / sc); x.lineWidth = 2 * d; x.strokeStyle = dim ? "rgba(255,255,255,.25)" : "#ff4d4f"; x.beginPath(); x.moveTo(ex - r, ey - r); x.lineTo(ex + r, ey + r); x.moveTo(ex + r, ey - r); x.lineTo(ex - r, ey + r); x.stroke(); return; }
    x.beginPath(); x.arc(a, b, r, 0, 7); x.fillStyle = dim ? "rgba(190,200,215,.45)" : tm.color; x.fill(); x.lineWidth = (hot ? 2.2 : 1.2) * d; x.strokeStyle = hot ? "#fff" : "rgba(10,12,20,.9)"; x.stroke();
  });
}
function rotSide() {
  const g = RT.g, box = $("#rside"); if (!g || !box) return; const t = RT.t;
  const rows = g.teams.filter(tm => !RT.qOnly || tm.q).map(tm => {
    const ps = g.byTeam[tm.team] || [], alive = ps.filter(p => !rotDead(p, t)).length;
    return `<tr class="rt-row ${RT.sel === tm.team ? "on" : ""}" data-t="${tm.team}"><td><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${tm.color}"></i></td><td>${tm.placement < 999 ? "#" + tm.placement : "-"}</td><td>${tm.players.map(p => esc(p.name)).join(" + ")}${tm.q ? ' <span class="ok" title="finished in the top of the event">★</span>' : ""}</td><td class="n">${alive}/${ps.length}</td></tr>`;
  }).join("");
  box.innerHTML = `<div class="card" style="margin:0;padding:10px"><div class="rt-scroll"><table><tr><th></th><th>Finish</th><th>Team</th><th class="n">Alive</th></tr>${rows}</table></div></div>${RT.sel != null ? rotTeamCard(RT.sel) : '<p class="small">Click a team (here or on the map) to follow it and see where it was when each storm circle closed.</p>'}`;
  $$("#rside .rt-row").forEach(r => r.onclick = () => { RT.sel = RT.sel === +r.dataset.t ? null : +r.dataset.t; rotSide(); rotDraw(); });
}
function rotTeamCard(ti) {   // where the team was when each zone started closing and when it finished
  const g = RT.g, ps = g.byTeam[ti] || [], tm = g.teams.find(q => q.team === ti), sc = g.scale;
  const cell = (u, v) => "ABCDEFGHIJ"[Math.min(9, Math.max(0, Math.floor(u * 10)))] + (Math.min(9, Math.max(0, Math.floor(v * 10))) + 1);
  const centre = t => { const pts = ps.map(p => rotAt(p, t)).filter((q, i) => q && !rotDead(ps[i], t)); if (!pts.length) return null; return [pts.reduce((s, q) => s + q[1], 0) / pts.length / sc, pts.reduce((s, q) => s + q[2], 0) / pts.length / sc]; };
  const land = ps.map(p => p.p.find(q => q[3] <= 250 && rotIn(q))).filter(Boolean).sort((a, b) => a[0] - b[0])[0];
  const rows = []; if (land) rows.push(["Landed", rotMmss(land[0]), cell(land[1] / sc, land[2] / sc)]);
  g.storm.forEach((z, i) => { const st = z[7], fi = z[8], c1 = centre(st), c2 = centre(fi); if (st > g.duration) return;
    const inside = c2 ? Math.hypot(c2[0] - z[5] / sc, c2[1] - z[6] / sc) <= z[4] / sc : null;
    rows.push([`Zone ${i + 1} (closes ${rotMmss(st)}–${rotMmss(fi)})`, c1 ? cell(c1[0], c1[1]) : "dead", c2 ? cell(c2[0], c2[1]) + (inside === false ? " ✗ outside" : "") : "dead"]); });
  const dead = ps.filter(p => p.x).map(p => p.x[2]).sort((a, b) => b - a)[0];
  return `<div class="card" style="margin:8px 0 0;padding:10px"><h3 style="margin:0 0 6px;font-size:.95rem"><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${tm.color}"></i> ${tm.players.map(p => esc(p.name)).join(" + ")}</h3>
    <div class="small" style="margin-bottom:6px">Finished #${tm.placement} · ${tm.kills} elim${tm.kills === 1 ? "" : "s"}${tm.rank ? " · event rank #" + nf(tm.rank) : ""}${dead ? " · out at " + rotMmss(dead) : ""}</div>
    ${table(["Moment", "Zone starts closing", "Zone closed"], rows, ["", "", ""])}</div>`;
}
function rotWire() {
  const c = $("#rc"); c.style.touchAction = "none"; c.style.cursor = "grab";
  const near = e => { const r = c.getBoundingClientRect(), k = c.width / r.width, mx = (e.clientX - r.left) * k, my = (e.clientY - r.top) * k, P = rotView(); let best = null, bd = (16 * k) ** 2;
    RT.g.tracks.forEach(p => { const cur = rotAt(p, RT.t); if (!cur || rotDead(p, RT.t)) return; const [a, b] = P(cur[1] / RT.g.scale, cur[2] / RT.g.scale), dd = (a - mx) ** 2 + (b - my) ** 2; if (dd < bd) { bd = dd; best = p; } }); return { p: best, mx, my }; };
  c.onwheel = e => { e.preventDefault(); const q = near(e), f = e.deltaY < 0 ? 1.25 : 0.8, z2 = Math.min(10, Math.max(1, RT.z * f)), k = z2 / RT.z; RT.ox = q.mx - (q.mx - RT.ox) * k; RT.oy = q.my - (q.my - RT.oy) * k; RT.z = z2;
    RT.ox = Math.min(c.width * .15, Math.max(c.width * .85 - c.width * RT.z, RT.ox)); RT.oy = Math.min(c.width * .15, Math.max(c.width * .85 - c.width * RT.z, RT.oy)); rotDraw(); };
  c.onpointerdown = e => { c.setPointerCapture(e.pointerId); RT.drag = { x: e.clientX, y: e.clientY, ox: RT.ox, oy: RT.oy, moved: false }; };
  c.onpointermove = e => { if (!RT.drag) return; const r = c.getBoundingClientRect(), k = c.width / r.width, dx = (e.clientX - RT.drag.x) * k, dy = (e.clientY - RT.drag.y) * k; if (Math.abs(dx) + Math.abs(dy) > 3) RT.drag.moved = true; RT.ox = RT.drag.ox + dx; RT.oy = RT.drag.oy + dy; rotDraw(); };
  c.onpointerup = e => { const was = RT.drag; RT.drag = null; if (was && !was.moved) { const q = near(e); RT.sel = q.p ? (RT.sel === q.p.t ? null : q.p.t) : null; rotSide(); rotDraw(); } };
  if (!RT.resizing) { RT.resizing = true; window.addEventListener("resize", () => { if ($("#rc")) rotDraw(); }); }
}
