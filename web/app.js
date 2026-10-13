"use strict";
const $ = (s, r = document) => r.querySelector(s);
const app = $("#app");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const nf = x => (x == null || isNaN(x)) ? "-" : Math.round(x).toLocaleString();
const fmt = t => new Date(t * 1000).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtDay = t => new Date(t * 1000).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
const ago = s => s == null ? "-" : s < 90 ? s + "s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago";
const dur = s => { s = Math.max(0, Math.round(s)); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + "d " : "") + (h || d ? h + "h " : "") + m + "m " + (s % 60) + "s" };
const TYPE = { FNCS: "FNCS", CASHCUP: "Cash cup", SKINCUP: "Skin cup" };
const LIVE = ["live", "games finishing", "ended (collecting)"];
let timers = [], charts = [];

async function j(url, opt) {
  const r = await fetch(url, opt);
  const d = await r.json();
  return d;
}
const pill = s => `<span class="pill ${LIVE.slice(0, 2).includes(s) ? "live" : s === "upcoming" ? "up" : "fin"}">${esc(s)}</span>`;
const link = (id, text) => `<a href="#/t/${encodeURIComponent(id)}">${esc(text)}</a>`;
function every(ms, fn) { timers.push(setInterval(fn, ms)); }
function clearAll() { timers.forEach(clearInterval); timers = []; charts.forEach(c => c.destroy()); charts = []; }
function setNav(p) { document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.dataset.p === p)); }
function table(head, rows, cls = []) {
  return `<div class="scroll"><table><tr>${head.map((h, i) => `<th class="${cls[i] || ""}">${h}</th>`).join("")}</tr>` +
    rows.map(r => `<tr>${r.map((c, i) => `<td class="${cls[i] || ""}">${c}</td>`).join("")}</tr>`).join("") + "</table></div>";
}
function countdowns() {
  document.querySelectorAll("[data-cd]").forEach(el => { el.textContent = dur(el.dataset.cd - Date.now() / 1000) });
}
setInterval(() => { countdowns(); $("#clock").textContent = new Date().toLocaleTimeString() }, 1000);

// ------------------------------------------------------------------ Home
async function home() {
  const d = await j("/api/home");
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const live = d.live.map(w => {
    const rows = Object.keys(w.now).map(r => {
      const p = w.preds[r];
      return [`Top ${r}`, nf(w.now[r]), p ? `<b>${nf(p.likely)}</b> <small>${nf(p.low)}–${nf(p.safe)}</small>` : "<small>calculating…</small>"];
    });
    return `<div class="card"><div class="row" style="align-items:center"><div style="flex:3"><h2>${link(w.window_id, w.name)}</h2>
      <span class="pill">${esc(w.region)}</span> <span class="pill">${esc(w.category)}</span> <span class="pill">${TYPE[w.family]}</span> ${pill(w.status)}</div>
      <div class="small" style="flex:2;text-align:right">board updated ${ago(w.age_s)}<br>${w.entrants ? nf(w.entrants) + " entrants" : ""}</div></div>
      <div class="prog"><i style="width:${Math.min(100, w.progress * 100)}%"></i></div>
      <div class="small">${Math.round(w.progress * 100)}% of the window · ends ${fmt(w.end)}</div>
      <div class="grid g2"><div><h3>Leaders</h3>${table(["#", "Player", "Pts", "Games"], w.top.map(t => [t.rank, esc(t.players.join(" + ")), nf(t.points), t.games]), ["", "", "n", "n"])}</div>
      <div><h3>Cutoffs: now → predicted final</h3>${table(["Rank", "Now", "Predicted"], rows, ["", "n", "n"])}</div></div></div>`;
  }).join("") || `<div class="card mut">Nothing is live right now.</div>`;
  const up = table(["Starts", "In", "Region", "Class", "Tournament"], d.upcoming.map(w => [fmt(w.begin), `<span data-cd="${w.begin}"></span>`, w.region, esc(w.category), link(w.window_id, w.name)]));
  const fin = table(["Ended", "Region", "Class", "Tournament"], d.finished.map(w => [fmt(w.end), w.region, esc(w.category), link(w.window_id, w.name)]));
  app.innerHTML = `<h1>Live now</h1>${live}<div class="grid g2"><div class="card"><h2>Starting soon</h2>${up}</div><div class="card"><h2>Just finished</h2>${fin}</div></div>`;
  countdowns();
}

// ------------------------------------------------------------------ Tournament

function rewardsCard(w) {
  const t = w.rewards || [];
  const now = Date.now() / 1000;
  const when = w.payout_at ? `<b>${fmt(w.payout_at)}</b> <small>(${Math.round((w.payout_at - w.end) / 60)} min after the window closes${w.payout_at < now ? " · already paid out" : ` · in ${dur(w.payout_at - now)}`})</small>` : "<span class=mut>not published</span>";
  const where = x => x.kind === "rank" ? (x.from === x.upto ? `Place ${x.upto}` : `Places ${x.from}–${x.upto}`) : x.kind === "value" ? `${nf(x.upto)}+ points` : x.kind === "percentile" ? `Top ${x.upto}%` : esc(x.kind);
  const body = t.length ? table(["Who", "Reward"], t.map(x => [where(x), x.items.map(i => `${i.type === "cash" ? "<b>" + esc(i.label) + "</b>" : esc(i.label)}`).join("<br>")])) : '<p class="mut">Epic lists no rewards for this window.</p>';
  return `<div class="card"><h2>Rewards</h2><p>Paid out: ${when}</p>${w.cash_total ? `<p>Total cash prize pool: <b>$${nf(w.cash_total)}</b></p>` : ""}${body}<p class="small">Item names come from Epic's internal IDs, so they can look run together. Payout time is Epic's published rule (${esc(w.payout_rule || "n/a")}).</p></div>`;
}
let TW = null, TPAGE = 0, TQ = "", TTOP = null;
async function tournament(id) {
  const w = await j("/api/window?window=" + encodeURIComponent(id));
  if (w.error) return app.innerHTML = `<div class="card err">${esc(w.error)}</div>`;
  TW = w; TPAGE = 0; TQ = "";
  const adv = (w.advance || []).map(a => `Top ${a[0]} advance (${esc(a[1])})`).join(" · ");
  const first = (w.advance && w.advance[0]) ? w.advance[0][0] : 100;
  TTOP = TTOP || first;
  const presets = [1, 10, 35, 50, 100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000];
  app.innerHTML = `
  <div class="card"><div class="row" style="align-items:center"><div style="flex:3"><h1 style="margin:0">${esc(w.name)}</h1>
    <span class="pill">${esc(w.region)}</span> <span class="pill">${esc(w.category)}</span> <span class="pill">${TYPE[w.family]}</span> ${pill(w.status)}</div>
    <div class="small" style="flex:2;text-align:right" id="cd"></div></div>
    <div class="grid g4" style="margin-top:10px">
      <div class="kpi"><div class="l">Starts</div><div class="v" style="font-size:1rem">${fmt(w.begin)}</div></div>
      <div class="kpi"><div class="l">Games starting until</div><div class="v" style="font-size:1rem">${fmt(w.end)}</div></div>
      <div class="kpi"><div class="l">Games / lobby</div><div class="v" style="font-size:1rem">${w.match_cap || "?"} games · ${w.lobby ? w.lobby + (w.mode === "solo" ? " players" : " teams") : "lobby ?"}</div></div>
      <div class="kpi"><div class="l">Last queue</div><div class="v" style="font-size:1rem">games started before the end still count (~22 min)</div></div></div>
    <p class="small">${esc(w.scoring || "")}</p><p class="small">${adv}</p></div>
  ${rewardsCard(w)}
  <div class="card"><h2>Rank calculator</h2>
    <div class="row"><div><label>Top X (1 – 10,000)</label><input id="x" type="number" min="1" max="10000" value="${TTOP}"></div>
    <div><label>Entrants (optional)</label><input id="e" type="number" min="1" placeholder="auto"></div>
    <div style="flex:0"><button id="go">Predict</button></div></div>
    <label style="margin-top:8px;display:flex;gap:8px;align-items:center"><input id="ap" type="checkbox" style="width:auto;margin:0"> Allow similar classes when this class has no history (approximate)</label>
    <div class="tabs">${presets.map(p => `<button class="sec chip" data-r="${p}">Top ${p.toLocaleString()}</button>`).join("")}</div>
    <div id="pred"></div></div>
  <div class="card"><h2>Points needed over time</h2><div id="chartbox"><canvas id="ch" height="110"></canvas></div><div id="chnote" class="small"></div></div>
  <div class="grid g2"><div class="card"><h2>Thresholds</h2><div id="th"></div></div>
  <div class="card"><h2>Leaderboard</h2><div class="row"><div><input id="q" placeholder="Search player name"></div><div style="flex:0"><button class="sec" id="qb">Search</button></div></div><div id="bd"></div></div></div>`;
  $("#go").onclick = () => predict();
  document.querySelectorAll("[data-r]").forEach(b => b.onclick = () => { $("#x").value = b.dataset.r; predict() });
  $("#qb").onclick = () => { TQ = $("#q").value.trim(); TPAGE = 0; boardLoad() };
  $("#q").onkeydown = e => { if (e.key === "Enter") $("#qb").click() };
  const active = LIVE.includes(w.status);
  const tick = () => { const t = w.begin - Date.now() / 1000, e = w.end - Date.now() / 1000; $("#cd") && ($("#cd").innerHTML = t > 0 ? `starts in <b>${dur(t)}</b>` : e > 0 ? `ends in <b>${dur(e)}</b>` : "") };
  tick(); every(1000, tick);
  await Promise.all([predict(), chart(), thresholds(), boardLoad()]);
  if (active || w.status === "upcoming") every(30000, () => { predict(true); chart(); thresholds(); if (TPAGE === 0 && !TQ) boardLoad() });
}
async function predict(quiet) {
  const x = +$("#x").value; TTOP = x;
  const q = new URLSearchParams({ window: TW.window_id, top: x, entrants: $("#e").value, approx: $("#ap").checked ? 1 : 0 });
  if (!quiet) $("#pred").innerHTML = '<p class="mut">Calculating…</p>';
  const d = await j("/api/predict?" + q);
  if (d.error) return $("#pred").innerHTML = `<p class="err">${esc(d.error)}</p>`;
  const row = (l, r, b) => `<tr><td>${l}</td><td class="n">${nf(r.low)}</td><td class="n ${b ? "big" : ""}">${nf(r.likely)}</td><td class="n">${nf(r.safe)}</td></tr>`;
  $("#pred").innerHTML = `<div class="scroll"><table><tr><th>Rank</th><th class="n">Low</th><th class="n">Most likely</th><th class="n">Safe (~95%)</th></tr>${row("Top " + nf(d.rank), d, 1)}${(d.cutoffs || []).map(c => row("Top " + c.rank + " <small>(advance)</small>", c)).join("")}</table></div>${evidence(d)}`;
}
function evidence(d) {
  const p = d.parts || {}, lv = d.live, sn = d.snapshots, pc = x => Math.round(x * 100) + "%";
  if (d.current != null && !lv) return `<p class="small">Now ${nf(d.current)} pts at this rank · ${esc(d.method || "")}</p>`;
  let h = lv ? `<div><span class="pill live">LIVE LEADERBOARD USED</span> rank ${d.rank} has <b>${nf(lv.current)}</b> pts now → projects to <b>${nf(p.live?.likely)}</b> <small>(${pc(p.live?.weight ?? 0)} of the answer · ${(lv.progress * 100).toFixed(0)}% through · ${lv.n || "?"} past events · ~${(lv.games_left_median || 0).toFixed(1)} games still to come for contenders)</small></div>`
    : `<div><span class="pill up">NO LIVE BOARD</span> <small>prediction from history only</small></div>`;
  h += p.history ? `<div>History says <b>${nf(p.history.likely)}</b> <small>(${pc(p.history.weight)} of the answer · ${d.prior?.n || "?"} comparable events)</small></div>` : "";
  if (sn) h += `<div class="small">Board refreshed ${ago(d.snapshot_age_s)} · ${sn.count} snapshots saved · ${d.board_players} players on the board</div>`;
  if (lv?.analogs?.length) h += `<details><summary class="small">Same moment in ${lv.analogs.length} past events of this class</summary>${table(["Region", "Event", "Then", "Final", "×"], lv.analogs.map(a => [a.region, esc(a.window.replace(/^S\d+_/, "")), nf(a.now), nf(a.final), a.now ? (a.final / a.now).toFixed(2) : "-"]), ["", "", "n", "n", "n"])}</details>`;
  return h + `<div class="small">${esc(d.method || "")}</div>`;
}
async function chart() {
  const s = await j("/api/series?window=" + encodeURIComponent(TW.window_id));
  const rows = s.points || [];
  if (rows.length < 2) { $("#chnote").textContent = "The chart appears once the live collector has recorded a few snapshots."; return; }
  const ranks = ["1", "10", "35", "100", "500", "1000", "5000", "10000"].filter(r => rows.some(p => p.p[r] != null));
  const colors = ["#7c5cff", "#5fd0ff", "#2ecc71", "#f5a623", "#ff5d6c", "#c678dd", "#98c379", "#e5c07b"];
  const data = { labels: rows.map(p => new Date(p.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })),
    datasets: ranks.map((r, i) => ({ label: "Top " + Number(r).toLocaleString(), data: rows.map(p => p.p[r] ?? null), borderColor: colors[i % 8], backgroundColor: colors[i % 8], pointRadius: 0, borderWidth: 2, tension: .25 })) };
  charts.forEach(c => c.destroy()); charts = [];
  charts.push(new Chart($("#ch"), { type: "line", data, options: { responsive: true, interaction: { mode: "index", intersect: false }, scales: { y: { title: { display: true, text: "points" } } }, plugins: { legend: { position: "bottom" } } } }));
  $("#chnote").textContent = rows.length + " snapshots";
}
async function thresholds() {
  const t = await j("/api/thresholds?window=" + encodeURIComponent(TW.window_id));
  const el = $("#th"); if (!el) return;
  const r = t.ranks || {};
  const keys = Object.keys(r).map(Number).sort((a, b) => a - b);
  el.innerHTML = keys.length ? table(["Rank", "Points " + (t.source === "live" ? "now" : "final")], keys.map(k => [`<a href="javascript:void 0" onclick="$('#x').value=${k};predict()">Top ${k.toLocaleString()}</a>`, nf(r[k])]), ["", "n"]) + `<p class="small">${t.source === "live" ? "Updated " + ago(Math.round(Date.now() / 1000 - t.updated)) : "Final board"}${t.entrants ? " · " + nf(t.entrants) + " entrants" : ""}</p>` : '<p class="mut">No board yet.</p>';
}
async function boardLoad() {
  const b = await j(`/api/board?window=${encodeURIComponent(TW.window_id)}&page=${TPAGE}&q=${encodeURIComponent(TQ)}`);
  const el = $("#bd"); if (!el) return;
  if (b.error || !b.rows) return el.innerHTML = `<p class="mut">${esc(b.error || "No board yet.")}</p>`;
  const pages = Math.max(1, Math.ceil(b.total / b.size));
  el.innerHTML = table(["#", "Player", "Pts", "G"], b.rows.map(r => [r.rank, r.players.length ? r.players.map(p => `<a href="#/player/${p.id}">${esc(p.name)}</a>`).join(" + ") : '<span class="mut">–</span>', nf(r.points), r.games]), ["", "", "n", "n"]) +
    `<div class="row" style="margin-top:8px;align-items:center"><button class="sec" ${TPAGE <= 0 ? "disabled" : ""} id="pv">‹ Prev</button><span class="small" style="text-align:center">page ${TPAGE + 1} / ${pages} · ${nf(b.total)} rows${b.source === "live" ? " · names shown for the top 60 live" : ""}</span><button class="sec" ${TPAGE + 1 >= pages ? "disabled" : ""} id="nx">Next ›</button></div>`;
  $("#pv").onclick = () => { TPAGE--; boardLoad() }; $("#nx").onclick = () => { TPAGE++; boardLoad() };
}

function rewardSummary(w) {
  const items = (w.rewards || []).flatMap(t => t.items);
  const parts = [];
  if (w.cash_total) parts.push(`<b>$${nf(w.cash_total)}</b>`);
  if (items.some(i => i.type === "item")) parts.push("cosmetics");
  if (items.some(i => i.type === "advance")) parts.push("advance");
  return parts.join(" · ") || "<span class=mut>-</span>";
}
// ------------------------------------------------------------------ Schedule
async function schedule() {
  const all = (await j("/api/windows")).filter?.(w => ["upcoming", "live", "games finishing", "ended (collecting)"].includes(w.status)) || [];
  const regs = [...new Set(all.map(w => w.region))].sort(), cats = [...new Set(all.map(w => w.category))].sort();
  app.innerHTML = `<h1>Schedule</h1><div class="card"><div class="row"><div><label>Region</label><select id="fr"><option value="">All</option>${regs.map(r => `<option>${r}</option>`).join("")}</select></div>
   <div><label>Type</label><select id="ft"><option value="">All</option>${Object.entries(TYPE).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
   <div><label>Class</label><select id="fc"><option value="">All</option>${cats.map(c => `<option>${esc(c)}</option>`).join("")}</select></div></div></div><div id="sl"></div>`;
  const draw = () => {
    const fr = $("#fr").value, ft = $("#ft").value, fc = $("#fc").value;
    const l = all.filter(w => (!fr || w.region === fr) && (!ft || w.family === ft) && (!fc || w.category === fc)).sort((a, b) => a.begin - b.begin);
    const days = {}; l.forEach(w => (days[fmtDay(w.begin)] ||= []).push(w));
    $("#sl").innerHTML = Object.entries(days).map(([d, ws]) => `<div class="card"><h2>${esc(d)}</h2>${table(["Start", "In", "Region", "Class", "Type", "Tournament", "Format", "Rewards", "Paid"], ws.map(w => [new Date(w.begin * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), w.status === "upcoming" ? `<span data-cd="${w.begin}"></span>` : pill(w.status), w.region, esc(w.category), TYPE[w.family], link(w.window_id, w.name), `${w.match_cap || "?"} games`, rewardSummary(w), w.payout_at ? new Date(w.payout_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "-"]))}</div>`).join("") || '<div class="card mut">Nothing matches.</div>';
    countdowns();
  };
  ["fr", "ft", "fc"].forEach(i => $("#" + i).onchange = draw); draw();
}

// ------------------------------------------------------------------ Archive
const ARCH = [1, 10, 35, 100, 500, 1000, 2000, 5000, 10000];
async function archive() {
  const all = await j("/api/archive");
  if (all.error) return app.innerHTML = `<div class="card err">${esc(all.error)}</div>`;
  const regs = [...new Set(all.map(w => w.region))].sort(), cats = [...new Set(all.map(w => w.category))].sort();
  app.innerHTML = `<h1>Archive</h1><div class="card"><div class="row"><div><label>Region</label><select id="fr"><option value="">All</option>${regs.map(r => `<option>${r}</option>`).join("")}</select></div>
   <div><label>Type</label><select id="ft"><option value="">All</option>${Object.entries(TYPE).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
   <div><label>Class</label><select id="fc"><option value="">All</option>${cats.map(c => `<option>${esc(c)}</option>`).join("")}</select></div>
   <div><label>Search</label><input id="fq" placeholder="event name"></div><div style="flex:0"><button class="sec" id="csv">CSV</button></div></div></div><div class="card" id="al"></div>`;
  let cur = [];
  const draw = () => {
    const fr = $("#fr").value, ft = $("#ft").value, fc = $("#fc").value, q = $("#fq").value.toLowerCase();
    cur = all.filter(w => (!fr || w.region === fr) && (!ft || w.family === ft) && (!fc || w.category === fc) && (!q || w.name.toLowerCase().includes(q) || w.window_id.toLowerCase().includes(q)));
    $("#al").innerHTML = `<p class="small">${cur.length} events · points needed to finish at each rank</p>` + table(["Ended", "Region", "Class", "Event", ...ARCH.map(r => "#" + r.toLocaleString())], cur.slice(0, 400).map(w => [fmt(w.end), w.region, esc(w.category), link(w.window_id, w.name), ...ARCH.map(r => nf(w.cutoffs[r]))]), ["", "", "", "", ...ARCH.map(() => "n")]);
  };
  ["fr", "ft", "fc"].forEach(i => $("#" + i).onchange = draw); $("#fq").oninput = draw;
  $("#csv").onclick = () => {
    const lines = [["event", "window_id", "region", "class", "ended", ...ARCH.map(r => "rank_" + r)].join(",")].concat(cur.map(w => [`"${w.name}"`, w.window_id, w.region, w.category, new Date(w.end * 1000).toISOString(), ...ARCH.map(r => w.cutoffs[r] ?? "")].join(",")));
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })); a.download = "fn-archive.csv"; a.click();
  };
  draw();
}

// ------------------------------------------------------------------ Classes
async function classes() {
  const d = await j("/api/classes");
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  app.innerHTML = `<h1>Classes</h1><p class="small">Each event class is kept separate. History is only ever compared within the same class.</p><div class="grid g3">` + d.map(c => `<a class="card" href="#/class/${encodeURIComponent(c.category)}" style="color:inherit;text-decoration:none"><h2>${esc(c.category)}</h2><div class="small">${c.events} finished · ${c.upcoming} upcoming</div>${Object.entries(c.median).map(([r, v]) => `<div>Median #${r}: <b>${nf(v)}</b></div>`).join("")}</a>`).join("") + "</div>";
}
async function classPage(name) {
  const d = await j("/api/class?name=" + encodeURIComponent(name));
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const t = d.table, ranks = Object.keys(t).map(Number).sort((a, b) => a - b);
  app.innerHTML = `<h1>${esc(name)}</h1><p class="small"><a href="#/classes">‹ all classes</a> · ${d.events.length} finished events</p>
  <div class="card"><h2>Points needed to reach each rank</h2>${table(["Rank", "Events", "Min", "25%", "Median", "75%", "Max"], ranks.map(r => ["Top " + r.toLocaleString(), t[r].n, nf(t[r].min), nf(t[r].p25), `<b>${nf(t[r].median)}</b>`, nf(t[r].p75), nf(t[r].max)]), ["", "n", "n", "n", "n", "n", "n"])}</div>
  <div class="card"><h2>Cutoffs across events</h2><canvas id="cc" height="110"></canvas></div>
  <div class="card"><h2>Events</h2>${table(["Ended", "Region", "Event", "#1", "#100", "#1000"], d.events.slice().reverse().map(e => [fmt(e.end), e.region, link(e.window_id, e.name), nf(e.cutoffs[1]), nf(e.cutoffs[100]), nf(e.cutoffs[1000])]), ["", "", "", "n", "n", "n"])}</div>`;
  const colors = ["#7c5cff", "#5fd0ff", "#2ecc71", "#f5a623"];
  charts.push(new Chart($("#cc"), { type: "line", data: { labels: d.events.map(e => e.region + " " + new Date(e.end * 1000).toLocaleDateString([], { month: "short", day: "numeric" })),
    datasets: [1, 100, 1000, 5000].map((r, i) => ({ label: "#" + r, data: d.events.map(e => e.cutoffs[r] ?? null), borderColor: colors[i], backgroundColor: colors[i], tension: .2, pointRadius: 2 })) }, options: { plugins: { legend: { position: "bottom" } } } }));
}

// ------------------------------------------------------------------ Players
async function players() {
  app.innerHTML = `<h1>Players</h1><div class="card"><div class="row"><div><label>Search by name</label><input id="pq" placeholder="player name"></div>
    <div style="flex:0"><button id="pb">Search</button></div></div><div id="pr"></div></div><div class="card"><h2>Strongest players so far</h2>
    <p class="small">Average finishing position as a share of entrants, over events where they reached the top 1000 (at least 3 events).</p><div id="tp">Loading…</div></div>`;
  const search = async () => {
    const q = $("#pq").value.trim(); if (!q) return;
    const r = await j("/api/players?q=" + encodeURIComponent(q));
    $("#pr").innerHTML = (r.error || !r.length) ? '<p class="mut">No player found. Names are collected gradually for top finishers.</p>' : table(["Player", "Events"], r.map(p => [`<a href="#/player/${p.id}">${esc(p.name)}</a>`, p.events]), ["", "n"]);
  };
  $("#pb").onclick = search; $("#pq").onkeydown = e => { if (e.key === "Enter") search() };
  const t = await j("/api/players");
  $("#tp").innerHTML = (t.error || !t.length) ? '<p class="mut">Not enough data yet.</p>' : table(["#", "Player", "Events", "Avg top %", "Best"], t.map((p, i) => [i + 1, `<a href="#/player/${p.id}">${esc(p.name)}</a>`, p.events, p.avg_top_pct + "%", "#" + p.best]), ["", "", "n", "n", "n"]);
}
async function playerPage(id) {
  const d = await j("/api/player?id=" + encodeURIComponent(id));
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  app.innerHTML = `<h1>${esc(d.name)}</h1><p class="small"><a href="#/players">‹ players</a> · ${d.events.length} top-1000 finishes recorded</p>
  <div class="card"><h2>By class</h2>${table(["Class", "Events", "Best", "Median", "Avg top %", "Pts / game", "Wins", "Elims / game"], d.summary.map(s => [esc(s.category), s.events, "#" + s.best_rank, "#" + s.median_rank, s.avg_top_pct + "%", s.pts_per_game ?? "-", s.wins, s.elims_per_game ?? "-"]), ["", "n", "n", "n", "n", "n", "n", "n"])}</div>
  <div class="card"><h2>Events</h2>${table(["Date", "Event", "Region", "Class", "Rank", "Points", "Games", "Avg place", "Wins"], d.events.map(e => [fmt(e.end), link(e.window_id, e.name), e.region, esc(e.category), "#" + e.rank, nf(e.points), e.games, e.avg_place ?? "-", e.wins]), ["", "", "", "", "n", "n", "n", "n", "n"])}</div>`;
}

// ------------------------------------------------------------------ FNCS
async function fncs() {
  const d = await j("/api/fncs");
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const groups = {}; d.forEach(w => (groups[w.name.split(" · ")[0]] ||= []).push(w));
  app.innerHTML = `<h1>FNCS tracker</h1><p class="small">Qualifiers → Heats → Last Chance → Final. For each window: the places that advance, the real cutoff once finished, and the predicted cutoff while it runs.</p>` +
    Object.entries(groups).map(([g, ws]) => `<div class="card"><h2>${esc(g)}</h2>${table(["Start", "Region", "Window", "Status", "Games", "Advancement cutoffs"], ws.map(w => [fmt(w.begin), w.region, link(w.window_id, w.name.split(" · ").slice(1).join(" · ") || w.name), pill(w.status), w.match_cap || "?",
      w.advance.map(a => `Top ${a.rank}: ${a.actual != null ? `<b>${nf(a.actual)}</b> pts` : a.predicted ? `~<b>${nf(a.predicted.likely)}</b> <small>(${nf(a.predicted.low)}–${nf(a.predicted.safe)})</small>` : "<small>not yet</small>"}`).join("<br>") || "<small>no cutoff</small>"]))}</div>`).join("");
}

// ------------------------------------------------------------------ Accuracy
async function accuracy() {
  const d = await j("/api/accuracy");
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  app.innerHTML = `<h1>Prediction accuracy</h1><div class="card"><p class="small">Every prediction the site stores during a live event is compared with the real final cutoff once the event is collected. ${d.events} events scored so far.</p>` +
    (d.buckets.length ? table(["Point in event", "Predictions", "Average error", "Bias", "Real result inside range"], d.buckets.map(b => [Math.round(b.progress * 100) + "% through", b.n, b.mean_abs_error_pct + "%", (b.bias_pct > 0 ? "+" : "") + b.bias_pct + "%", b.inside_range_pct + "%"]), ["", "n", "n", "n", "n"]) +
      `<p class="small">Bias above 0 means the site guessed too high. Range = Low to Safe.</p>` : '<p class="mut">No scored predictions yet. They accumulate as live events finish.</p>') + "</div>";
}

// ------------------------------------------------------------------ Status
async function status() {
  const [s, a] = await Promise.all([j("/api/status_full"), j("/api/status")]);
  if (s.error) return app.innerHTML = `<div class="card err">${esc(s.error)}</div>`;
  const c = s.counts || {};
  app.innerHTML = `<h1>Status</h1><div class="grid g4">
   <div class="kpi"><div class="l">Collector last ran</div><div class="v ${s.last_tick_age_s != null && s.last_tick_age_s < 150 ? "ok" : "err"}">${ago(s.last_tick_age_s)}</div></div>
   <div class="kpi"><div class="l">Epic login</div><div class="v ${s.login.logged_in ? "ok" : "err"}">${s.login.logged_in ? "valid" : "needed"}</div></div>
   <div class="kpi"><div class="l">Events stored</div><div class="v">${c.final ?? "-"} / ${c.windows ?? "-"}</div></div>
   <div class="kpi"><div class="l">Database</div><div class="v">${c.db_mb ?? "-"} MB</div></div></div>
  <div class="card"><h2>Details</h2><p class="small">Regions tracked: ${esc((s.regions || []).join(", "))}. Windows: ${esc(JSON.stringify(s.windows_by_status))}.<br>
   Snapshots ${c.snapshots} · series points ${c.series} · stored predictions ${c.predictions} · player names ${c.names} · events still needing deep thresholds ${c.deep_missing}.</p>
   <h3>Last collector pass</h3><pre class="small" style="white-space:pre-wrap">${esc((s.last_tick || []).map(x => x.join(" ")).join("\n"))}</pre></div>
  ${s.login.logged_in ? "" : `<div class="card"><b>Epic login needed</b><p class="small">Log in to Epic in this browser, open <a href="${esc(a.login_url)}" target="_blank">this link</a>, copy the authorizationCode and paste it here.</p>
   <input id="code" placeholder="authorizationCode"><input id="key" type="password" placeholder="Admin key" style="margin-top:6px"><button id="lg" style="margin-top:8px">Save login</button> <span id="lm" class="small"></span></div>`}
  <div class="card"><h2>How the predictions work</h2><p class="small">Every player on the live leaderboard is replayed forward. Their remaining games (including the last queue that starts before the cutoff), points per game and chance of catching up come from players in the same spot at the same moment in earlier events <b>of the same class</b>. The result is corrected using a back-test on those past events. Ranks beyond 700 are scaled from the stored thresholds (ranks 1000, 1500 … 10000). Unofficial data; estimates only.</p></div>`;
  const lg = $("#lg");
  if (lg) lg.onclick = async () => {
    const r = await j("/api/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ code: $("#code").value.trim(), key: $("#key").value }) });
    $("#lm").textContent = r.ok ? "Logged in." : (r.error || "failed");
  };
}

// ------------------------------------------------------------------ Router
async function route() {
  clearAll();
  const h = location.hash.replace(/^#\/?/, ""), [p, ...rest] = h.split("/"), arg = decodeURIComponent(rest.join("/"));
  const page = p || "home"; setNav(["t"].includes(page) ? "schedule" : ["class"].includes(page) ? "classes" : ["player"].includes(page) ? "players" : page);
  window.scrollTo(0, 0);
  try {
    if (page === "home") { await home(); every(30000, home); }
    else if (page === "t") await tournament(arg);
    else if (page === "schedule") await schedule();
    else if (page === "archive") await archive();
    else if (page === "classes") await classes();
    else if (page === "class") await classPage(arg);
    else if (page === "players") await players();
    else if (page === "player") await playerPage(arg);
    else if (page === "fncs") await fncs();
    else if (page === "accuracy") await accuracy();
    else if (page === "status") await status();
    else app.innerHTML = '<div class="card">Page not found.</div>';
  } catch (e) { app.innerHTML = `<div class="card err">Something went wrong: ${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", route);
route();
