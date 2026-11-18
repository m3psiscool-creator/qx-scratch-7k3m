"use strict";
// Pages, navigation and the router. Helpers live in lib.js, the Strategy tab in strategy.js.
const app = $("#app");
const TYPE = { FNCS: "FNCS", CASHCUP: "Cash cup", SKINCUP: "Skin cup", VICTORYCUP: "Victory cup", WORKSHOP: "Evaluation cup", TESTCUP: "Test cup" };
const ACTIVE = ["live", "games finishing"];
const REGIONS = ["NAC", "NAW", "EU", "BR", "ASIA", "ME", "OCE"];
const DOT = { live: "#2ecc71", "games finishing": "#2ecc71", "ended (collecting)": "#f5a623", upcoming: "#f5a623", finished: "#9aa3b4", "not collected yet": "#9aa3b4" };
let timers = [];
let REGION = store.get("region", "");
let FILT = store.get("filt", { q: "", type: "", cls: "", status: "", fav: false });
let FAVS = new Set(store.get("favs", []));

function every(ms, fn) { timers.push(setInterval(fn, ms)); }
function clearAll() { timers.forEach(clearInterval); timers = []; destroyCharts(); }
const pill = s => `<span class="pill ${ACTIVE.includes(s) ? "live" : s === "upcoming" ? "up" : ""}">${esc(s)}</span>`;
const link = (id, text, tab) => `<a href="#/t/${encodeURIComponent(id)}${tab ? "/" + tab : ""}">${esc(text)}</a>`;
function countdowns() { $$("[data-cd]").forEach(el => { el.textContent = dur(el.dataset.cd - Date.now() / 1000); }); }
setInterval(() => { countdowns(); const c = $("#clock"); if (c) c.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }, 1000);

// ---------------------------------------------------------------- shell: navigation, theme, region
const NAV = [
  { g: "", items: [["home", "Home", "home", "#/"]] },
  { g: "Plan", items: [["strategy", "Strategy", "target", "#/strategy"], ["me", "My results", "user", "#/me"], ["drops", "Dropspots", "map", "#/drops"], ["map", "Map", "pin", "#/map"], ["rotations", "Rotations", "route", "#/rotations"], ["schedule", "Schedule", "cal", "#/schedule"], ["fncs", "FNCS", "trophy", "#/fncs"]] },
  { g: "Research", items: [["archive", "Archive", "archive", "#/archive"], ["classes", "Gamemodes", "layers", "#/classes"], ["players", "Players", "user", "#/players"]] },
  { g: "Site", items: [["accuracy", "Accuracy", "gauge", "#/accuracy"], ["status", "Status", "gear", "#/status"]] },
];
const MOBILE = ["home", "strategy", "schedule", "archive"];
const flat = NAV.flatMap(g => g.items);
$("#nav").innerHTML = NAV.map(g => (g.g ? `<div class="navgrp">${g.g}</div>` : "") + g.items.map(([k, l, i, h]) => `<a href="${h}" data-p="${k}">${icon(i)}<span>${l}</span></a>`).join("")).join("");
$("#mnav").innerHTML = MOBILE.map(k => { const [, l, i, h] = flat.find(x => x[0] === k); return `<a href="${h}" data-p="${k}">${icon(i)}<span>${l}</span></a>`; }).join("") + `<a href="javascript:void 0" id="morebtn" data-p="more">${icon("more")}<span>More</span></a>`;
$("#morebtn").onclick = e => {
  e.stopPropagation(); const old = $(".more-pop"); if (old) return old.remove();
  const d = document.createElement("div"); d.className = "more-pop";
  d.innerHTML = flat.filter(x => !MOBILE.includes(x[0])).map(([k, l, i, h]) => `<a href="${h}">${icon(i)}${l}</a>`).join("") + `<a href="javascript:void 0" id="mfb">${icon("info")}Send feedback</a>`;
  setTimeout(() => { const f = $("#mfb"); if (f) f.onclick = ev => { ev.stopPropagation(); d.remove(); feedbackPop(); }; });
  document.body.appendChild(d);
};
document.addEventListener("click", e => { const p = $(".more-pop"); if (p) p.remove(); });
function setNav(page, tab) {
  const main = { t: tab === "strategy" ? "strategy" : "schedule", player: "players", class: "classes" }[page] || page;
  $$("#nav a, #mnav a[data-p]").forEach(a => a.classList.toggle("on", a.dataset.p === main || (a.dataset.p === "more" && !MOBILE.includes(main) && main !== "home")));
}
// theme: dark (default) -> light -> auto (follow the system)
let THEME = store.get("theme", "dark");
function applyTheme() {
  if (THEME === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", THEME);
  const dark = THEME === "dark" || (THEME === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#theme").innerHTML = icon(dark ? "moon" : "sun"); $("#theme").title = "Theme: " + THEME + " (click to change)";
}
$("#theme").onclick = () => { THEME = { dark: "light", light: "auto", auto: "dark" }[THEME]; store.set("theme", THEME); applyTheme(); route(); };
applyTheme();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { applyTheme(); if (THEME === "auto") route(); });

const rgSel = $("#rg");
rgSel.value = REGION; rgSel.onchange = () => setRegion(rgSel.value);
function setRegion(r) { REGION = r; store.set("region", r); rgSel.value = r; route(); }

// ---------------------------------------------------------------- the player's Epic account: chosen once, checked everywhere
let ACCT = store.get("acct", null);   // {name, id}
const MEC = {};                       // results per event, kept 45 seconds so pages share one lookup
async function fetchMe(wid, force) {
  if (!ACCT) return null;
  const c = MEC[wid]; if (c && !force && Date.now() - c.t < 45000) return c.d;
  let d; try { d = await j(`/api/me?window=${encodeURIComponent(wid)}&name=${encodeURIComponent(ACCT.name)}&account=${ACCT.id}`); } catch (e) { d = { error: "Could not reach the site." }; }
  MEC[wid] = { t: Date.now(), d }; return d;
}
function renderAcct() { const b = $("#acct"); b.classList.toggle("on", !!ACCT); b.innerHTML = ACCT ? `<span class="dot"></span>${esc(ACCT.name)}` : `${icon("user")}<span>Add my Epic account</span>`; }
function acctPop(edit) {
  const old = $(".acctpop"); if (old) { old.remove(); if (!edit) return; }
  const d = document.createElement("div"); d.className = "acctpop";
  d.innerHTML = ACCT && !edit ? `<h3>Your Epic account</h3><p style="margin:0 0 12px"><b>${esc(ACCT.name)}</b><br><small>Checked automatically on the home page and every event page.</small></p><div class="chips"><button class="sec" id="ap-change">Change</button><button class="sec" id="ap-clear">Remove</button></div>`
    : `<h3>${ACCT ? "Change account" : "Add your Epic account"}</h3><p class="small" style="margin:0 0 8px">Type your Epic display name once. The site reads your points and games from the public leaderboard and checks them automatically. No password or login is needed.</p><input id="ap-name" placeholder="Epic display name" autocomplete="off" value="${esc(ACCT ? ACCT.name : "")}"><div class="chips" style="margin-top:10px"><button id="ap-save">Save</button><span id="ap-msg" class="small"></span></div>`;
  document.body.appendChild(d);
  const save = async () => {
    const name = $("#ap-name").value.trim(); if (!name) return;
    $("#ap-msg").textContent = "Checking…";
    const r = await j("/api/account?name=" + encodeURIComponent(name));
    if (r.error) { $("#ap-msg").innerHTML = `<span class="err">${esc(r.error)}</span>`; return; }
    ACCT = { name: r.name, id: r.id }; store.set("acct", ACCT); Object.keys(MEC).forEach(k => delete MEC[k]);
    d.remove(); renderAcct(); route();
  };
  if ($("#ap-save")) { $("#ap-save").onclick = save; $("#ap-name").addEventListener("keydown", e => { if (e.key === "Enter") save(); }); setTimeout(() => $("#ap-name").focus(), 50); }
  if ($("#ap-change")) $("#ap-change").onclick = () => acctPop(true);
  if ($("#ap-clear")) $("#ap-clear").onclick = () => { ACCT = null; store.set("acct", null); Object.keys(MEC).forEach(k => delete MEC[k]); d.remove(); renderAcct(); route(); };
}
$("#acct").onclick = e => { e.stopPropagation(); acctPop(); };
document.addEventListener("click", e => { const p = $(".acctpop"); if (p && !e.target.closest(".acctpop") && !e.target.closest("#acct")) p.remove(); });
renderAcct();
// an account typed in the old Strategy box: keep it without asking again
(async () => { const old = store.get("epicname", ""); if (!ACCT && old) { try { const r = await j("/api/account?name=" + encodeURIComponent(old)); if (!r.error) { ACCT = { name: r.name, id: r.id }; store.set("acct", ACCT); renderAcct(); route(); } } catch (e) { } } store.set("epicname", ""); })();
// one line about the player's own result in an event
const meLine = (d, wid) => !d || d.error ? "" : d.found ? `<span class="dot" style="width:8px;height:8px;border-radius:50%;background:var(--good);display:inline-block"></span> <b>${esc(d.name)}</b> · rank <b>#${nf(d.rank)}</b> · <b>${nf(d.points)}</b> points · ${d.games_played} games${d.team && d.team.length ? " · with " + esc(d.team.join(", ")) : ""} <a href="#/t/${encodeURIComponent(wid)}/strategy">Your games ›</a>` : `<span class="mut">${esc(d.message || "")}</span>`;

// ---------------------------------------------------------------- feedback from anyone (read by the owner on the Status page)
function feedbackPop() {
  const old = $(".acctpop"); if (old) old.remove();
  const d = document.createElement("div"); d.className = "acctpop";
  d.innerHTML = `<h3>Send feedback</h3><p class="small" style="margin:0 0 8px">Tell us what you want from the site, or what is broken. Nothing personal is collected.</p>
    <select id="fb-kind" style="margin-bottom:8px"><option value="idea">An idea or a request</option><option value="bug">Something is broken</option><option value="data">The numbers look wrong</option></select>
    <textarea id="fb-text" rows="4" maxlength="1200" placeholder="What would help you play better?" style="width:100%;font:inherit;padding:8px 11px;border-radius:10px;border:1px solid var(--line2);background:var(--sf);color:var(--tx);resize:vertical"></textarea>
    <div class="chips" style="margin-top:10px"><button id="fb-send">Send</button><span id="fb-msg" class="small"></span></div>`;
  document.body.appendChild(d); $("#fb-text").focus();
  $("#fb-send").onclick = async () => {
    const r = await j("/api/feedback", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ kind: $("#fb-kind").value, text: $("#fb-text").value, page: location.hash }) });
    if (r.ok) { $("#fb-msg").innerHTML = '<span class="ok">Thank you, sent.</span>'; $("#fb-send").disabled = true; setTimeout(() => d.remove(), 1400); } else $("#fb-msg").innerHTML = `<span class="err">${esc(r.error || "Could not send")}</span>`;
  };
}
if ($("#fbk")) $("#fbk").onclick = e => { e.stopPropagation(); feedbackPop(); };
document.addEventListener("click", e => { const p = $(".acctpop"); if (p && $("#fb-text") && !e.target.closest(".acctpop")) p.remove(); });
const calUrl = (o = {}) => "/api/calendar.ics?" + new URLSearchParams(Object.fromEntries(Object.entries(o).filter(([, v]) => v))).toString();

// ---------------------------------------------------------------- favourites (an event is starred in every region)
const evKey = id => id.replace(/_(NAC|NAW|EU|BR|ASIA|ME|OCE)$/, "");
const isFav = id => FAVS.has(evKey(id));
const star = id => `<a href="javascript:void 0" class="star ${isFav(id) ? "on" : ""}" data-fav="${esc(evKey(id))}" title="Favourite this event in every region">${isFav(id) ? "★" : "☆"}</a>`;
document.addEventListener("click", e => {
  const s = e.target.closest("[data-fav]"); if (!s) return;
  const k = s.dataset.fav; FAVS.has(k) ? FAVS.delete(k) : FAVS.add(k); store.set("favs", [...FAVS]);
  $$("[data-fav]").forEach(el => { if (el.dataset.fav === k) { const on = FAVS.has(k); el.classList.toggle("on", on); el.textContent = on ? "★" : "☆"; } });
});

// ---------------------------------------------------------------- one search box for every tournament
let ALLW = null, ALLW_AT = 0;
async function allWindows() {
  if (!ALLW || Date.now() - ALLW_AT > 300000) { const d = await j("/api/windows"); if (Array.isArray(d)) { ALLW = d; ALLW_AT = Date.now(); } }
  return ALLW || [];
}
const gs = $("#gs"), gsr = $("#gsr");
function rank(w) { return (ACTIVE.includes(w.status) ? 0 : w.status === "upcoming" ? 1 : 2) * 1e12 + (w.status === "finished" ? -w.begin : w.begin) + (isFav(w.window_id) ? -1e13 : 0); }
function matches(w, q) {
  const hay = (w.name + " " + w.region + " " + w.category + " " + (TYPE[w.family] || "") + " " + w.status + " " + w.window_id).toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every(t => hay.includes(t));
}
let gsSel = -1;
async function gsRender() {
  const q = gs.value.trim();
  if (!q) { gsr.hidden = true; return; }
  const l = (await allWindows()).filter(w => w.status !== "not collected yet" && matches(w, q) && (!REGION || w.region === REGION || q.length > 3)).sort((a, b) => rank(a) - rank(b)).slice(0, 12);
  gsSel = -1;
  gsr.innerHTML = l.length ? l.map(w => `<a href="#/t/${encodeURIComponent(w.window_id)}">${isFav(w.window_id) ? "★ " : ""}<b>${esc(w.name)}</b> <small>${w.region} · ${esc(gm(w.category))} · ${TYPE[w.family]} · ${w.status === "upcoming" ? "starts " + fmt(w.begin) : w.status === "finished" ? "finished " + fmt(w.end) : esc(w.status)}</small></a>`).join("") : '<a class="mut">No tournament matches.</a>';
  gsr.hidden = false;
}
let gst; gs.addEventListener("input", () => { clearTimeout(gst); gst = setTimeout(gsRender, 120); });
gs.addEventListener("focus", gsRender);
gs.addEventListener("keydown", e => {
  const items = $$("a[href]", gsr);
  if (e.key === "ArrowDown") gsSel = Math.min(items.length - 1, gsSel + 1);
  else if (e.key === "ArrowUp") gsSel = Math.max(0, gsSel - 1);
  else if (e.key === "Enter") { (items[Math.max(0, gsSel)] || {}).click?.(); return; }
  else if (e.key === "Escape") { gsr.hidden = true; return; }
  else return;
  items.forEach((a, i) => a.classList.toggle("sel", i === gsSel)); e.preventDefault();
});
document.addEventListener("click", e => { if (!e.target.closest(".gsearch")) gsr.hidden = true; });
gsr.addEventListener("click", () => { gsr.hidden = true; gs.value = ""; });

// ---------------------------------------------------------------- shared filter bar (Schedule, Archive)
function filterBar(rows, opts) {
  const cats = [...new Set(rows.map(w => w.category))].sort();
  return `<div class="card"><div class="filters">
    <div><label>Search</label><input id="fq" placeholder="name, gamemode…" value="${esc(FILT.q)}"></div>
    <div><label>Region</label><select id="fr"><option value="">All</option>${REGIONS.map(r => `<option ${r === REGION ? "selected" : ""}>${r}</option>`).join("")}</select></div>
    <div><label>Type</label><select id="ft"><option value="">All</option>${Object.entries(TYPE).map(([k, v]) => `<option value="${k}" ${k === FILT.type ? "selected" : ""}>${v}</option>`).join("")}</select></div>
    <div><label>Gamemode</label><select id="fc"><option value="">All</option>${cats.map(c => `<option value="${esc(c)}" ${c === FILT.cls ? "selected" : ""}>${esc(gm(c))}</option>`).join("")}</select></div>
    ${opts.status ? `<div><label>Status</label><select id="fs"><option value="">All</option><option value="live" ${FILT.status === "live" ? "selected" : ""}>Live now</option><option value="upcoming" ${FILT.status === "upcoming" ? "selected" : ""}>Upcoming</option></select></div>` : ""}
    <label class="chk"><input id="ff" type="checkbox" ${FILT.fav ? "checked" : ""}> ★ Favourites</label>
    ${opts.csv ? '<div style="flex:0"><button class="sec" id="csv">Export CSV</button></div>' : ""}</div></div>`;
}
function bindFilters(redraw) {
  const read = () => { FILT = { q: $("#fq").value, type: $("#ft").value, cls: $("#fc").value, status: $("#fs") ? $("#fs").value : "", fav: $("#ff").checked }; store.set("filt", FILT); };
  ["fq", "ft", "fc", "fs", "ff"].forEach(id => { const el = $("#" + id); if (el) el[id === "fq" ? "oninput" : "onchange"] = () => { read(); redraw(); }; });
  $("#fr").onchange = () => { REGION = $("#fr").value; store.set("region", REGION); rgSel.value = REGION; redraw(); };
}
const applyFilters = rows => rows.filter(w => (!REGION || w.region === REGION) && (!FILT.type || w.family === FILT.type) && (!FILT.cls || w.category === FILT.cls) &&
  (!FILT.fav || isFav(w.window_id)) && (!FILT.q || matches(w, FILT.q)) && (!FILT.status || (FILT.status === "live" ? ACTIVE.includes(w.status) : w.status === FILT.status)));

const head = (title, sub, right) => `<div class="ph"><div><h1>${title}</h1>${sub ? `<p>${sub}</p>` : ""}</div>${right || ""}</div>`;
const goalText = w => w.goal ? `Top ${nf(w.goal.rank)} · ${w.goal.kind}` : "no single goal";
// a clickable event card: opens the strategy page of that event
function evCard(w) {
  const when = w.status === "upcoming" ? `starts in <span class="cd" data-cd="${w.begin}"></span>` : w.status === "finished" ? "finished " + fmt(w.end) : esc(w.status);
  return `<a class="ev" href="#/t/${encodeURIComponent(w.window_id)}/strategy"><div class="meta"><span class="pill">${esc(w.region)}</span><span class="pill">${esc(gm(w.category))}</span><span class="pill">${TYPE[w.family]}</span>${ACTIVE.includes(w.status) ? pill(w.status) : ""}</div>
    <div class="t">${isFav(w.window_id) ? "★ " : ""}${esc(w.name)}</div><div class="small">${when} · ${w.match_cap || "?"} games</div>
    <div class="go"><span>${esc(goalText(w))}</span><b>Plan strategy ›</b></div></a>`;
}

// ---------------------------------------------------------------- Home
const NEWS_VER = "2026-10-15";
const NEWS = ["<b>Coach notes</b> on the Strategy tab: your games against finishers, with what to fix.", "<b>Which style gives the best chance?</b> Finishers grouped by elims, replayed from your next game.", "<b>Calendar</b>: add events with a 30 minute reminder. <b>Feedback</b>: tell us what you want."];
let HOME_SIG = "";
async function home(quiet) {
  const d = await j("/api/home" + (REGION ? "?region=" + REGION : ""));
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const sig = JSON.stringify([d.live.map(w => [w.window_id, w.now, w.preds, w.top, w.status]), d.upcoming.map(w => w.window_id), d.finished.map(w => w.window_id), REGION]);
  if (quiet && sig === HOME_SIG) return;   // same data: do not rebuild the page and its charts
  HOME_SIG = sig; destroyCharts();
  const live = d.live.map((w, i) => {
    const goal = w.goal ? w.goal.rank : null, pr = goal ? w.preds[goal] : null, ranks = Object.keys(w.now).map(Number).sort((a, b) => a - b);
    const rows = ranks.map(r => { const p = w.preds[r]; return [(goal === r) ? `<b>★ Top ${r}</b>` : `Top ${r}`, nf(w.now[r]), p ? `<b>${nf(p.likely)}</b> <small>${nf(p.low)}–${nf(p.safe)}</small>` : "<small>calculating…</small>"]; });
    return `<div class="card"><div class="hd"><h2>${star(w.window_id)}${link(w.window_id, w.name)}</h2><span class="sub">board updated ${ago(w.age_s)}${w.entrants ? " · " + nf(w.entrants) + " entrants" : ""}</span></div>
      <div class="meta chips"><span class="pill">${esc(w.region)}</span><span class="pill">${esc(gm(w.category))}</span><span class="pill">${TYPE[w.family]}</span>${pill(w.status)}</div>
      <div class="prog"><i style="width:${Math.min(100, w.progress * 100)}%"></i></div>
      <div class="small">${Math.round(w.progress * 100)}% of the window · ends ${fmt(w.end)}</div>
      ${goal ? `<div class="kpis" style="margin-top:14px">${kpi("Goal: top " + nf(goal), nf(w.now[goal]), "points right now")}${kpi("Predicted final", pr ? nf(pr.likely) : "…", pr ? "range " + nf(pr.low) + " – " + nf(pr.safe) : "calculating", "hero")}<div class="kpi"><div class="l">Goal cutoff, recent trend</div><div class="cv spark"><canvas id="sp${i}"></canvas></div></div></div>` : ""}
      <div class="grid g2"><div><h3>Leaders</h3>${table(["#", "Player", "Pts", "G"], w.top.map(t => [t.rank, esc(t.players.join(" + ")), nf(t.points), t.games]), ["", "", "n", "n"])}</div>
      <div><h3>Cutoffs: now → predicted final</h3>${table(["Rank", "Now", "Predicted"], rows, ["", "n", "n"])}</div></div>
      <div class="mestrip" id="mh${i}"></div><div class="chips" style="margin-top:12px"><a class="btn" href="#/t/${encodeURIComponent(w.window_id)}/strategy">Strategy ›</a><a class="btn sec" href="#/t/${encodeURIComponent(w.window_id)}/predictions">Predictions</a></div></div>`;
  }).join("");
  const favs = FAVS.size ? (await allWindows()).filter(w => isFav(w.window_id) && (!REGION || w.region === REGION) && w.status !== "not collected yet").sort((a, b) => rank(a) - rank(b)).slice(0, 6) : [];
  const nextUp = (d.upcoming || []).slice(0, 6);
  app.innerHTML = head("Live now" + (REGION ? " · " + REGION : ""), "Live leaderboards, predicted final cutoffs, and a strategy page for every event.") +
    (store.get("seen_new", "") === NEWS_VER ? "" : `<div class="card" id="newscard"><div class="hd"><h2>What's new</h2><button class="sec chip" id="newsx">Got it</button></div><ul style="margin:0;padding-left:18px;line-height:1.6">${NEWS.map(n => `<li>${n}</li>`).join("")}</ul></div>`) +
    (ACCT ? "" : `<div class="card flat" style="display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap"><div><b>Add your Epic account once</b><div class="small">Then your rank, points and games are checked automatically on every event, with no login.</div></div><button id="ap-open">Add my account</button></div>`) +
    (live || `<div class="card flat"><b>Nothing is live right now${REGION ? " in " + REGION : ""}.</b> <span class="mut">Plan ahead with the next events below.</span></div>`) +
    (favs.length ? `<h3 style="margin-top:22px">★ Your favourites</h3><div class="evgrid" style="margin-bottom:20px">${favs.map(evCard).join("")}</div>` : "") +
    `<h3 style="margin-top:22px">Starting soon</h3><div class="evgrid">${nextUp.map(evCard).join("") || '<div class="card flat mut">No upcoming events.</div>'}</div>
    <div class="card" style="margin-top:20px"><div class="hd"><h2>Just finished</h2></div>${table(["Ended", "Region", "Tournament", ""], d.finished.map(w => [fmt(w.end), w.region, star(w.window_id) + link(w.window_id, w.name), link(w.window_id, "Results ›", "predictions")]))}</div>`;
  countdowns();
  if ($("#newsx")) $("#newsx").onclick = () => { store.set("seen_new", NEWS_VER); $("#newscard").remove(); };
  if ($("#ap-open")) $("#ap-open").onclick = e => { e.stopPropagation(); acctPop(); };
  if (ACCT) (async () => { for (const [w, i] of d.live.map((w, i) => [w, i]).filter(([w]) => ACTIVE.includes(w.status)).slice(0, REGION ? 8 : 4)) { const r = await fetchMe(w.window_id); const el = $("#mh" + i); if (el) el.innerHTML = meLine(r, w.window_id); } })();
  d.live.forEach(async (w, i) => {
    const goal = w.goal ? w.goal.rank : null; if (!goal || !$("#sp" + i)) return;
    const s = await j("/api/series?window=" + encodeURIComponent(w.window_id)), rows = (s.points || []);
    if (rows.length < 2 || !$("#sp" + i)) return;
    const keys = Object.keys(rows[rows.length - 1].p).map(Number), key = String(keys.reduce((b, k) => Math.abs(k - goal) < Math.abs(b - goal) ? k : b, keys[0]));
    const pts = rows.filter(r => r.p[key] != null).map(r => ({ x: r.ts, y: r.p[key] }));
    mk($("#sp" + i), { type: "line", data: { datasets: [{ data: pts, borderColor: SER(0), backgroundColor: withAlpha(SER(0), .15), fill: true, borderWidth: 2 }] }, options: { interaction: { mode: null }, scales: { x: { type: "linear", display: false }, y: { display: false } }, plugins: { legend: { display: false }, tooltip: { enabled: false } } } });
  });
}

// ---------------------------------------------------------------- Strategy hub
async function strategyHub() {
  const all = (await allWindows()).filter(w => ["live", "games finishing", "upcoming"].includes(w.status) && (!REGION || w.region === REGION));
  const sorted = all.sort((a, b) => rank(a) - rank(b));
  const groups = [["Live now", sorted.filter(w => ACTIVE.includes(w.status))], ["Your favourites", sorted.filter(w => w.status === "upcoming" && isFav(w.window_id))], ["Coming up", sorted.filter(w => w.status === "upcoming" && !isFav(w.window_id)).slice(0, 36)]];
  app.innerHTML = head("Strategy", "Pick an event to get a plan: the points to aim for, what the scoring rewards, what finishers did, pace, safety margin and whether to keep playing.") +
    `<div class="card"><div class="hd"><h2>How it works</h2></div><div class="grid g3">
      <div class="recipe"><b>1 · Target</b><div>Choose a rank. We predict the cutoff and how sure each level of certainty is.</div></div>
      <div class="recipe"><b>2 · Playstyle</b><div>See how many elims and which placements add up to that cutoff, and what finishers did.</div></div>
      <div class="recipe"><b>3 · Track</b><div>Enter your points as you play. Pace and keep-playing odds update at once.</div></div></div></div>` +
    groups.filter(g => g[1].length).map(([t, ws]) => `<h3 style="margin-top:22px">${t}</h3><div class="evgrid">${ws.map(evCard).join("")}</div>`).join("") +
    (all.length ? "" : `<div class="card empty">No live or upcoming events${REGION ? " in " + REGION : ""}. <a href="#/archive">Browse the archive</a> to study past events.</div>`);
  countdowns(); every(1000, countdowns);
}

// ---------------------------------------------------------------- Tournament
function regionChips(w, tab) {
  const sib = w.siblings || [];
  if (sib.length < 2) return "";
  return `<div class="chips" style="margin-top:12px"><small>Same event in</small>` + sib.map(o => {
    const on = o.window_id === w.window_id;
    return `<a class="pill ${on ? "ac" : ""}" href="#/t/${encodeURIComponent(o.window_id)}/${tab}" title="${esc(o.status)} · ${fmt(o.begin)}"><span style="width:7px;height:7px;border-radius:50%;background:${DOT[o.status] || "#999"}"></span>${esc(o.region)}</a>`;
  }).join("") + `</div>`;
}
function payoutText(w) {
  const now = Date.now() / 1000;
  return w.payout_at ? `<b>${fmt(w.payout_at)}</b> <small>(${Math.round((w.payout_at - w.end) / 60)} min after the window closes${w.payout_at < now ? " · already paid out" : ` · in ${dur(w.payout_at - now)}`})</small>` : "<span class=mut>not published</span>";
}
function rewardsCard(w) {
  const t = w.rewards || [];
  const where = x => x.kind === "rank" ? (x.from === x.upto ? `Place ${x.upto}` : `Places ${x.from}–${x.upto}`) : x.kind === "value" ? `${nf(x.upto)}+ points` : x.kind === "percentile" ? `Top ${x.upto}%` : esc(x.kind);
  const body = t.length ? table(["Who", "Reward"], t.map(x => [where(x), x.items.map(i => `${i.type === "cash" ? "<b>" + esc(i.label) + "</b>" : esc(i.label)}`).join("<br>")])) : '<p class="mut">Epic lists no rewards for this window.</p>';
  return `<div class="card"><div class="hd"><h2>Rewards</h2></div><p>Paid out: ${payoutText(w)}</p>${w.cash_total ? `<p>Total cash prize pool: <b>$${nf(w.cash_total)}</b></p>` : ""}${body}<p class="small">Item names come from Epic's internal IDs, so they can look run together. Payout time is Epic's published rule (${esc(w.payout_rule || "n/a")}).</p></div>`;
}
function rewardSummary(w) {
  const f = w.reward_flags || {}, parts = [];
  if (w.cash_total) parts.push(`<b>$${nf(w.cash_total)}</b>`);
  if (f.item) parts.push("cosmetics");
  if (f.advance) parts.push("advance");
  return parts.join(" · ") || "<span class=mut>-</span>";
}
// ---- skip through the sessions (rounds, days, editions) of the same event in the same region
let SESS = null;
async function loadSessions(w, tab) {
  const el = $("#sessions"); SESS = null;
  const d = await j("/api/sessions?window=" + encodeURIComponent(w.window_id));
  if (!el || !$("#sessions") || d.error || !d.items || d.items.length < 2) return;
  SESS = { items: d.items, i: d.index, tab };
  const href = it => "#/t/" + encodeURIComponent(it.window_id) + "/" + tab, short = t => new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
  const sub = it => it.status === "finished" ? (it.goal_pts != null ? `top ${d.goal_rank}: ${nf(it.goal_pts)}` : "finished") : ACTIVE.includes(it.status) ? "live now" : it.status === "upcoming" ? "starts " + short(it.begin) : it.status;
  const prev = d.items[d.index - 1], next = d.items[d.index + 1];
  el.innerHTML = `<div class="sess"><div class="sess-h"><b>Sessions of this event</b><small>${esc(d.region)} · ${d.total} in total · arrow keys ← → also work</small>
    <button class="chip" id="s-prev" ${prev ? "" : "disabled"}>‹ Previous</button><button class="chip" id="s-next" ${next ? "" : "disabled"}>Next ›</button></div>
    <div class="sess-row" id="sessrow">${d.items.map((it, n) => `<a class="sc ${n === d.index ? "on" : ""} ${it.status}" href="${href(it)}"><b>${esc(it.label)}</b><small>${short(it.begin)}${it.games ? " · " + it.games + " games" : ""}</small><small>${esc(sub(it))}</small></a>`).join("")}</div></div>`;
  if (prev) $("#s-prev").onclick = () => { location.hash = href(prev); };
  if (next) $("#s-next").onclick = () => { location.hash = href(next); };
  const row = $("#sessrow"), cur = row.querySelector(".on"); if (cur) row.scrollLeft = cur.offsetLeft - row.clientWidth / 2 + cur.clientWidth / 2;
}
document.addEventListener("keydown", e => {
  if (!SESS || !location.hash.startsWith("#/t/") || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  const it = SESS.items[SESS.i + (e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0)];
  if (it && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); location.hash = "#/t/" + encodeURIComponent(it.window_id) + "/" + SESS.tab; }
});
let TW = null, TPAGE = 0, TQ = "", TTOP = null;
const TABS = [["overview", "Overview"], ["strategy", "Strategy"], ["predictions", "Predictions"], ["leaderboard", "Leaderboard"], ["rewards", "Rewards"]];
async function tournament(id, tab) {
  tab = TABS.some(t => t[0] === tab) ? tab : "overview";
  const w = await j("/api/window?window=" + encodeURIComponent(id));
  if (w.error) return app.innerHTML = `<div class="card err">${esc(w.error)}</div>`;
  TW = w; TPAGE = 0; TQ = "";
  TTOP = w.goal ? w.goal.rank : (w.advance && w.advance[0] ? w.advance[0][0] : 100);
  app.innerHTML = `
  <div class="crumb"><a href="#/schedule">Schedule</a> › ${esc(w.region)}</div>
  <div class="card"><div class="hd" style="margin:0"><div><h1 style="font-size:1.45rem">${star(w.window_id)}${esc(w.name)}</h1>
    <div class="chips" style="margin-top:8px"><span class="pill">${esc(w.region)}</span><span class="pill">${esc(gm(w.category))}</span><span class="pill">${TYPE[w.family]}</span>${pill(w.status)}${w.status === "upcoming" || ACTIVE.includes(w.status) ? `<a class="pill ac" href="${calUrl({ window: w.window_id })}" title="Download a calendar entry with a 30 minute reminder">＋ Calendar</a>` : ""}</div></div>
    <div class="small" style="text-align:right" id="cd"></div></div>${regionChips(w, tab)}<div class="mestrip" id="mestrip"></div><div id="sessions"></div></div>
  <div class="tabbar">${TABS.map(([k, label]) => `<a href="#/t/${encodeURIComponent(w.window_id)}/${k}" class="${k === tab ? "on" : ""}">${label}${k === "strategy" ? '<span class="new">NEW</span>' : ""}</a>`).join("")}</div>
  <div id="panel"></div>`;
  const tick = () => { const t = w.begin - Date.now() / 1000, e = w.end - Date.now() / 1000; $("#cd") && ($("#cd").innerHTML = t > 0 ? `starts in <b class="cd">${dur(t)}</b>` : e > 0 ? `games can start for <b class="cd">${dur(e)}</b>` : ""); };
  tick(); every(1000, tick);
  const open = w.status === "upcoming" || ACTIVE.includes(w.status);
  const stripMe = async force => { if (!ACCT || w.status === "upcoming") return; const r = await fetchMe(w.window_id, force); const el = $("#mestrip"); if (el) el.innerHTML = meLine(r, w.window_id); };
  loadSessions(w, tab);
  stripMe(); if (open) every(180000, () => stripMe(true));   // your own result, checked automatically on every event page
  if (tab === "overview") await tabOverview(w, open);
  else if (tab === "strategy") await tabStrategy(w, open);
  else if (tab === "predictions") await tabPredictions(w, open);
  else if (tab === "leaderboard") await tabLeaderboard(w, open);
  else $("#panel").innerHTML = rewardsCard(w);
}
async function tabOverview(w, open) {
  const adv = (w.advance || []).map(a => `Top ${a[0]}: ${esc(a[1].replace(/^Advance: /, ""))}`).join(" · ");
  const goal = w.goal, wid = encodeURIComponent(w.window_id);
  $("#panel").innerHTML = `
  <div class="kpis">${kpi("Starts", fmt(w.begin).replace(/,/g, ""))}${kpi("Games can start until", fmt(w.end).replace(/,/g, ""))}${kpi("Format", (w.match_cap || "?") + " games", w.lobby ? w.lobby + (w.mode === "solo" ? " players" : " teams") + " per lobby" : "lobby size unknown")}${kpi("Rewards paid", w.payout_at ? fmt(w.payout_at).replace(/,/g, "") : "n/a")}</div>
  ${goal ? `<div class="card"><div class="hd"><h2><span class="pill live" style="margin-right:8px">MAIN GOAL</span>Top ${nf(goal.rank)}</h2><span class="sub">${esc(goal.label)}</span></div>
    <div id="ovpred"><p class="mut">Calculating…</p></div>
    <div class="chips" style="margin-top:12px"><a class="btn" href="#/t/${wid}/strategy">Plan my strategy ›</a><a class="btn sec" href="#/t/${wid}/predictions">Try any other rank</a></div></div>` : `<div class="card"><p>No single goal rank for this event. <a href="#/t/${wid}/strategy">Open the strategy tools ›</a></p></div>`}
  <div class="grid g2"><div class="card"><div class="hd"><h2>Rewards at a glance</h2></div><p style="margin:0">${rewardSummary(w)}</p><p class="small">${adv}</p>
    <p class="small">Paid: ${payoutText(w)}</p><a href="#/t/${wid}/rewards">All rewards ›</a></div>
  <div class="card"><div class="hd"><h2>Points needed</h2></div><div id="th"></div></div></div>
  <div class="card"><details><summary class="small" style="cursor:pointer">Scoring rules</summary><p class="small">${esc(w.scoring || "Not published.")}</p><p class="small">Games started before the end still count, and can finish up to about 22 minutes later (the "last queue").</p></details></div>`;
  if (goal) await predictInto($("#ovpred"), goal.rank, { compact: true });
  await thresholds(true);
  if (open) every(120000, () => { if (goal) predictInto($("#ovpred"), goal.rank, { compact: true, quiet: true }); thresholds(true); });
}
async function tabPredictions(w, open) {
  const presets = [1, 10, 35, 50, 100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000];
  $("#panel").innerHTML = `
  <div class="card"><div class="hd"><h2>Rank calculator</h2><span class="sub">${w.goal ? `main goal: top ${nf(w.goal.rank)}` : ""}</span></div>
    <div class="row"><div><label>Top X (1 – 10,000)</label><input id="x" type="number" min="1" max="10000" value="${TTOP}"></div>
    <div><label>Entrants (optional)</label><input id="e" type="number" min="1" placeholder="auto"></div>
    <div style="flex:0"><button id="go">Predict</button></div></div>
    <div class="chips" style="margin-top:10px">${presets.map(p => `<button class="chip" data-r="${p}">Top ${p.toLocaleString()}</button>`).join("")}</div>
    <div id="pred"></div></div>
  ${chartCard("ch", "Points needed by rank", "now, previous events of this gamemode and format (same region first), and the predicted final", { cls: "tall", table: false, zoom: true, ctrl: `<div class="seg" id="ladseg"><button data-s="log" class="${LADLOG ? "on" : ""}">Log scale</button><button data-s="lin" class="${LADLOG ? "" : "on"}">Linear</button></div><small>Click a point to calculate that rank</small>` })}
  ${chartCard("ch2", "Points needed over time", "how the cutoffs have grown during this window", { cls: "tall", table: false, zoom: true, ctrl: `<div class="seg" id="rngseg">${[[0, "Whole window"], [3, "Last 3 hours"], [1, "Last hour"], [0.5, "Last 30 min"]].map(([h, l]) => `<button data-h="${h}" class="${h === TRANGE ? "on" : ""}">${l}</button>`).join("")}</div><small>Click a legend item to hide a rank</small>` })}
  <div class="card"><div class="hd"><h2>Thresholds</h2></div><div id="th"></div></div>
  <div class="card" id="bubblecard" style="display:none"><div class="hd"><h2>Bubble: who is in the race</h2></div><div id="bubble"></div></div>`;
  $("#go").onclick = () => { predict(); bubble(); };
  $$("[data-r]").forEach(b => b.onclick = () => { $("#x").value = b.dataset.r; predict(); bubble(); });
  $$("#ladseg button").forEach(b => b.onclick = () => { LADLOG = b.dataset.s === "log"; store.set("ladlog", LADLOG); $$("#ladseg button").forEach(x => x.classList.toggle("on", x === b)); const cv = $("#ch"); if (cv) cv.dataset.sig = ""; ladderChart(); });
  $$("#rngseg button").forEach(b => b.onclick = () => { TRANGE = +b.dataset.h; $$("#rngseg button").forEach(x => x.classList.toggle("on", x === b)); const cv = $("#ch2"); if (cv) cv.dataset.sig = ""; timeChart(); });
  await Promise.all([predict(), ladderChart(), timeChart(), thresholds(false), bubble()]);
  if (open) {
    every(120000, () => { predict(true); bubble(); ladderChart(); });
    every(60000, () => { timeChart(); thresholds(false); });
  }
}
async function tabLeaderboard(w, open) {
  $("#panel").innerHTML = `<div class="card"><div class="hd"><h2>Leaderboard</h2></div><div class="row"><div><input id="q" placeholder="Search player name"></div><div style="flex:0"><button class="sec" id="qb">Search</button></div></div><div id="bd" style="margin-top:10px"></div></div>`;
  $("#qb").onclick = () => { TQ = $("#q").value.trim(); TPAGE = 0; boardLoad(); };
  $("#q").onkeydown = e => { if (e.key === "Enter") $("#qb").click(); };
  await boardLoad();
  if (open) every(60000, () => { if (TPAGE === 0 && !TQ) boardLoad(); });
}

async function predictInto(el, rank, o = {}) {
  if (!el || !TW) return;
  if (!o.quiet) el.innerHTML = '<p class="mut">Calculating…</p>';
  const q = new URLSearchParams({ window: TW.window_id, top: rank, entrants: o.entrants || "" });
  const d = await j("/api/predict?" + q);
  if (d.error) return el.innerHTML = `<p class="${o.compact ? "mut" : "err"}">${esc(d.error)}</p>`;
  if (o.compact) {
    el.innerHTML = (d.final || !(d.safe > d.low) ? `<div class="kpis">${kpi("Low", nf(d.low))}${kpi("Most likely", nf(d.likely), "", "hero")}${kpi("Safe", nf(d.safe))}</div>` : estimateStrip(d)) + miniEvidence(d) + noteLine(d);
    return;
  }
  const row = (l, r, b) => `<tr><td>${l}</td><td class="n">${nf(r.low)}</td><td class="n mid" style="${b ? "font-weight:800;font-size:1.15rem" : ""}">${nf(r.likely)}</td><td class="n">${nf(r.safe)}</td></tr>`;
  el.innerHTML = estimateStrip(d) + `<div class="scroll" style="margin-top:12px"><table><tr><th>Rank</th><th class="n">Low (10%)</th><th class="n mid">Most likely</th><th class="n">Safe (90%)</th></tr>${row("Top " + nf(d.rank), d, 1)}${(d.cutoffs || []).map(c => row("Top " + c.rank + " <small>(advance)</small>", c)).join("")}</table></div>${noteLine(d)}${evidence(d)}`;
}
function noteLine(d) {   // why the answer is not the plain one: last place of a small field, or the closest gamemodes were used
  return (d.note ? `<p class="small">${esc(d.note)}</p>` : "") + (d.similar_modes ? `<p class="small">No past event of this exact gamemode yet, so this estimate comes from the closest gamemodes.</p>` : "");
}
function miniEvidence(d) {
  const lv = d.live, p = d.parts || {};
  if (d.final) return `<p class="small">Final result: this event has finished.</p>`;
  if (lv) return `<p class="small"><span class="pill live">LIVE LEADERBOARD USED</span> now <b>${nf(lv.current)}</b> pts at this rank, ${(lv.progress * 100).toFixed(0)}% through · board ${ago(d.snapshot_age_s)}</p>`;
  return `<p class="small"><span class="pill up">FROM HISTORY</span> ${p.history ? "based on " + (d.prior?.n || "?") + " comparable past events" : esc(d.method || "")}</p>`;
}
async function predict(quiet) {
  const x = Math.min(10000, Math.max(1, Math.round(+$("#x").value || TTOP || 1))); TTOP = x; $("#x").value = x;   // any whole number from 1 to 10,000
  await predictInto($("#pred"), x, { entrants: $("#e").value, quiet });
}
function evidence(d) {
  const p = d.parts || {}, lv = d.live, sn = d.snapshots, pcx = x => Math.round(x * 100) + "%";
  if (d.current != null && !lv) return `<p class="small">Now ${nf(d.current)} pts at this rank · ${esc(d.method || "")}</p>`;
  let h = lv ? `<div style="margin-top:10px"><span class="pill live">LIVE LEADERBOARD USED</span> rank ${d.rank} has <b>${nf(lv.current)}</b> pts now → projects to <b>${nf(p.live?.likely)}</b> <small>(${pcx(p.live?.weight ?? 0)} of the answer · ${(lv.progress * 100).toFixed(0)}% through · ${lv.n || "?"} past events · ~${(lv.games_left_median || 0).toFixed(1)} games still to come for contenders)</small></div>`
    : `<div style="margin-top:10px"><span class="pill up">NO LIVE BOARD</span> <small>prediction from history only</small></div>`;
  const hm_ = d.history_mix, mix = hm_ ? ` · ${hm_.same} previous in ${esc(hm_.region)}${hm_.other ? " + " + hm_.other + " from other regions (too few here)" : ""}, same gamemode and format` : "";
  h += p.history ? `<div>History says <b>${nf(p.history.likely)}</b> <small>(${pcx(p.history.weight)} of the answer · ${d.prior?.n || "?"} comparable events${mix})</small></div>` : "";
  if (sn) h += `<div class="small">Board refreshed ${ago(d.snapshot_age_s)} · ${sn.count} snapshots saved · ${d.board_players} players on the board</div>`;
  if (lv?.analogs?.length) h += `<details style="margin-top:8px"><summary class="small" style="cursor:pointer">Same moment in ${lv.analogs.length} past events of this gamemode</summary>${table(["Region", "Event", "Then", "Final", "×"], lv.analogs.map(a => [a.region, esc(a.window.replace(/^S\d+_/, "")), nf(a.now), nf(a.final), a.now ? (a.final / a.now).toFixed(2) : "-"]), ["", "", "n", "n", "n"])}</details>`;
  return h + `<div class="small">${esc(d.method || "")}</div>`;
}
async function bubble() {
  if (!TW || !ACTIVE.includes(TW.status)) return;
  const card = $("#bubblecard"); if (!card) return;
  const goal = (+$("#x").value > 0 && +$("#x").value <= 700) ? +$("#x").value : (TW.goal ? Math.min(TW.goal.rank, 700) : 100);
  const b = await j(`/api/bubble?window=${encodeURIComponent(TW.window_id)}&rank=${goal}`);
  card.style.display = "block";
  if (b.error) { $("#bubble").innerHTML = `<p class="mut">${esc(b.error)}</p>`; return; }
  const col = p => p >= 0.8 ? "var(--good)" : p >= 0.4 ? "var(--warn)" : "var(--mut)";
  $("#bubble").innerHTML = `<div class="kpis">${kpi("Goal", "Top " + nf(b.goal))}${kpi("Cutoff now", nf(b.cutoff_now))}${kpi("Expected to end near", nf(b.cutoff_final), b.cutoff_range ? nf(b.cutoff_range[0]) + " – " + nf(b.cutoff_range[1]) : "", "hero")}${kpi("Virtually safe", b.safe, "players")}</div>` +
    table(["#", "Player", "Pts", "G", "Expected final", "Chance"], b.rows.map(r => [r.rank, r.players.length ? r.players.map(p => `<a href="#/player/${p.id}">${esc(p.name)}</a>`).join(" + ") : '<span class="mut">-</span>', nf(r.points), r.games, nf(r.final),
      `<b style="color:${col(r.prob)}">${Math.round(r.prob * 100)}%</b>`]), ["", "", "n", "n", "n", "n"]) +
    `<p class="small">Updated ${ago(b.age_s)}. Each player is simulated game by game with comparable players from past events of this gamemode. In past events the current leaders finished inside the cutoff more often than these percentages say, so the top of the table is conservative.</p>`;
}
// points needed by rank: now vs history vs predicted final
let LADLOG = store.get("ladlog", true), TRANGE = 0;
async function ladderChart() {
  const d = await j("/api/ladder?window=" + encodeURIComponent(TW.window_id)), cv = $("#ch");
  if (!cv) return; if (d.error) { cv.parentElement.innerHTML = `<p class="mut">${esc(d.error)}</p>`; return; }
  const rk = d.ranks.filter(r => d.history[r] || d.now[r]);
  const H = k => rk.filter(r => d.history[r]).map(r => ({ x: r, y: d.history[r][k] }));
  const nowD = Object.keys(d.now).map(Number).sort((a, b) => a - b).map(r => ({ x: r, y: d.now[r] }));
  const pr = Object.entries(d.predicted).map(([r, v]) => ({ x: +r, y: v.likely, lo: v.low, hi: v.safe })).sort((a, b) => a.x - b.x);
  const ds = [
    { label: "Past events: 25%", data: H("p25"), borderColor: withAlpha(SER(0), .3), borderWidth: 1, pointRadius: 0, fill: false, order: 5 },
    { label: "Past events: 25–75%", data: H("p75"), borderColor: withAlpha(SER(0), .3), borderWidth: 1, pointRadius: 0, backgroundColor: withAlpha(SER(0), .14), fill: "-1", order: 5 },
    { label: "Past events: median", data: H("median"), borderColor: SER(0), borderDash: [6, 4], borderWidth: 2, pointRadius: 0, order: 3 },
    { label: d.source === "live" ? "Now" : d.source === "final" ? "Final" : "Now", data: nowD, borderColor: SER(1), backgroundColor: SER(1), borderWidth: 3, pointRadius: 0, order: 2 },
  ];
  if (pr.length) ds.push({ label: "Predicted final", data: pr, showLine: false, borderColor: SER(2), backgroundColor: SER(2), pointStyle: "rectRot", pointRadius: 7, pointHoverRadius: 9, order: 1 });
  const sig = JSON.stringify(ds); if (cv.dataset.sig === sig) return; cv.dataset.sig = sig;   // unchanged: keep the chart as it is
  const tk = $("#ch-take"); if (tk) tk.innerHTML = `<p class="small" style="margin:8px 0 0">History: ${d.same_region} previous ${esc(d.region)} event${d.same_region === 1 ? "" : "s"} of this gamemode and format${d.events > d.same_region ? " + " + (d.events - d.same_region) + " from other regions (this region has too few)" : ""}.</p>`;
  mk(cv, { type: "line", zoom: "x", click: hit => { const x = hit.element.$context.parsed.x, r = d.ranks.reduce((a, b) => Math.abs(b - x) < Math.abs(a - x) ? b : a, d.ranks[0]); if ($("#x")) { $("#x").value = r; predict(); bubble(); $("#pred").scrollIntoView({ behavior: "smooth", block: "center" }); } }, data: { datasets: ds }, options: { interaction: { mode: "nearest", axis: "x", intersect: false }, scales: { x: { type: LADLOG ? "logarithmic" : "linear", min: LADLOG ? 1 : 0, max: 10000, title: { text: LADLOG ? "Rank (log scale)" : "Rank" }, ticks: { maxRotation: 0, autoSkip: !LADLOG, callback: v => !LADLOG || [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000].includes(v) ? v.toLocaleString() : "" } }, y: { title: { text: "Points" }, beginAtZero: false } }, plugins: { tooltip: { callbacks: { title: c => "Top " + nf(c[0].parsed.x), label: c => c.raw && c.raw.lo != null ? `Predicted final: ${nf(c.raw.y)} (${nf(c.raw.lo)} – ${nf(c.raw.hi)})` : `${c.dataset.label}: ${nf(c.parsed.y)}` } }, legend: { labels: { filter: i => i.text !== "Past events: 25%" } } } } });
}
async function timeChart() {
  const cv = $("#ch2"); if (!cv) return;
  const s = await j("/api/series?window=" + encodeURIComponent(TW.window_id)), rows = s.points || [];
  if (rows.length < 2) { cv.parentElement.innerHTML = '<p class="mut">The chart appears once the live collector has recorded a few snapshots.</p>'; return; }
  const ranks = ["1", "10", "35", "100", "500", "1000", "5000", "10000"].filter(r => rows.some(p => p.p[r] != null));
  const pred = {}; try { const d = await j("/api/ladder?window=" + encodeURIComponent(TW.window_id)); Object.assign(pred, d.predicted || {}); } catch (e) { }
  const ds = ranks.map((r, i) => ({ label: "Top " + Number(r).toLocaleString(), data: rows.filter(p => p.p[r] != null).map(p => ({ x: p.ts, y: p.p[r] })), borderColor: SER(i), backgroundColor: SER(i), pointRadius: 0, borderWidth: 2 }));
  ranks.forEach((r, i) => { if (pred[r]) ds.push({ label: "pred:" + r, data: [{ x: TW.end, y: pred[r].likely, lo: pred[r].low, hi: pred[r].safe, r }], showLine: false, borderColor: SER(i), backgroundColor: SER(i), pointStyle: "rectRot", pointRadius: 6, pointHoverRadius: 8 }); });
  const sig = JSON.stringify(ds); if (cv.dataset.sig === sig) return; cv.dataset.sig = sig;
  const lastTs = rows[rows.length - 1].ts, xr = TRANGE ? { min: lastTs - TRANGE * 3600, max: lastTs + TRANGE * 360 } : { max: Math.max(TW.end, lastTs) };
  mk(cv, { type: "line", zoom: "x", data: { datasets: ds }, options: { interaction: { mode: "nearest", axis: "x", intersect: false }, scales: { x: { type: "linear", ...xr, ticks: { maxTicksLimit: 8, callback: v => hm(v) }, title: { text: "Time (diamonds = predicted final at the window's end)" } }, y: { title: { text: "Points" } } }, plugins: { legend: { labels: { filter: i => !i.text.startsWith("pred:") } }, tooltip: { callbacks: { title: c => fmt(c[0].parsed.x), label: c => c.raw && c.raw.lo != null ? `Top ${nf(c.raw.r)} predicted final: ${nf(c.raw.y)} (${nf(c.raw.lo)} – ${nf(c.raw.hi)})` : `${c.dataset.label}: ${nf(c.parsed.y)}` } } } } });
}
async function thresholds(compact) {
  const t = await j("/api/thresholds?window=" + encodeURIComponent(TW.window_id));
  const el = $("#th"); if (!el) return;
  const r = t.ranks || {};
  let keys = Object.keys(r).map(Number).sort((a, b) => a - b);
  if (compact) keys = keys.filter(k => [1, 10, 35, 50, 100, 250, 500, 1000, 2000, 5000, 10000].includes(k) || (TW.goal && k === TW.goal.rank));
  el.innerHTML = keys.length ? table(["Rank", "Points " + (t.source === "live" ? "now" : "final")], keys.map(k => [compact ? `Top ${k.toLocaleString()}` : `<a href="javascript:void 0" onclick="$('#x').value=${k};predict()">Top ${k.toLocaleString()}</a>`, nf(r[k])]), ["", "n"]) + `<p class="small">${t.source === "live" ? "Updated " + ago(Math.round(Date.now() / 1000 - t.updated)) : "Final board"}${t.entrants ? " · " + nf(t.entrants) + " entrants" : ""}</p>` : '<p class="mut">No board yet.</p>';
}
async function boardLoad() {
  const b = await j(`/api/board?window=${encodeURIComponent(TW.window_id)}&page=${TPAGE}&q=${encodeURIComponent(TQ)}`);
  const el = $("#bd"); if (!el) return;
  if (b.error || !b.rows) return el.innerHTML = `<p class="mut">${esc(b.error || "No board yet.")}</p>`;
  const pages = Math.max(1, Math.ceil(b.total / b.size));
  el.innerHTML = table(["#", "Player", "Pts", "G"], b.rows.map(r => [r.rank, r.players.length ? r.players.map(p => `<a href="#/player/${p.id}">${esc(p.name)}</a>`).join(" + ") : '<span class="mut">–</span>', nf(r.points), r.games]), ["", "", "n", "n"]) +
    `<div class="row" style="margin-top:12px;align-items:center"><button class="sec" ${TPAGE <= 0 ? "disabled" : ""} id="pv">‹ Prev</button><span class="small" style="text-align:center">page ${TPAGE + 1} / ${pages} · ${nf(b.total)} rows${b.source === "live" ? " · names shown for the top 60 live" : ""}</span><button class="sec" ${TPAGE + 1 >= pages ? "disabled" : ""} id="nx">Next ›</button></div>`;
  $("#pv").onclick = () => { TPAGE--; boardLoad(); }; $("#nx").onclick = () => { TPAGE++; boardLoad(); };
}

// ---------------------------------------------------------------- Schedule
async function schedule() {
  const all = (await allWindows()).filter(w => ["upcoming", "live", "games finishing", "ended (collecting)"].includes(w.status));
  app.innerHTML = head("Schedule", "Every live and upcoming window, with the rewards and how many games it runs.", `<a class="btn sec" id="calbtn" href="#" title="Download these events with a 30 minute reminder">＋ Add to calendar</a>`) + filterBar(all, { status: true }) + `<div id="sl"></div>`;
  const draw = () => {
    const l = applyFilters(all).sort((a, b) => a.begin - b.begin);
    const days = {}; l.forEach(w => (days[fmtDay(w.begin)] ||= []).push(w));
    $("#sl").innerHTML = Object.entries(days).map(([d, ws]) => `<div class="card"><div class="hd"><h2>${esc(d)}</h2><span class="sub">${ws.length} windows</span></div>${table(["Start", "In", "Region", "Gamemode", "Type", "Tournament", "Games", "Rewards", "Paid", ""], ws.map(w => [hm(w.begin), w.status === "upcoming" ? `<span class="cd" data-cd="${w.begin}"></span>` : pill(w.status), w.region, esc(gm(w.category)), TYPE[w.family], star(w.window_id) + link(w.window_id, w.name), w.match_cap || "?", rewardSummary(w), w.payout_at ? hm(w.payout_at) : "-", link(w.window_id, "Plan ›", "strategy")]))}</div>`).join("") || '<div class="card empty">Nothing matches these filters.</div>';
    countdowns();
    $("#calbtn").href = calUrl({ region: REGION, family: FILT.type, category: FILT.cls, q: FILT.q, favs: FILT.fav ? [...FAVS].join(",") : "" });
  };
  bindFilters(draw); draw(); every(1000, countdowns);
}

// ---------------------------------------------------------------- Archive
const ARCH = [1, 10, 35, 100, 500, 1000, 2000, 5000, 10000];
async function archive() {
  const all = await j("/api/archive");
  if (all.error) return app.innerHTML = `<div class="card err">${esc(all.error)}</div>`;
  let TR = +store.get("archrank", 100);
  app.innerHTML = head("Archive", "Points needed at every rank in every finished window. Filter, then look at the trend.") + filterBar(all, { csv: true }) +
    chartCard("ar", "Cutoff trend", "one dot per finished window · click a dot to open it", { cls: "tall", zoom: true, ctrl: `<label style="margin:0">Rank</label><select id="arr" style="width:auto;margin:0">${ARCH.map(r => `<option value="${r}" ${r === TR ? "selected" : ""}>Top ${r.toLocaleString()}</option>`).join("")}</select>` }) + `<div class="card" id="al"></div>`;
  let cur = [];
  const draw = () => {
    cur = applyFilters(all);
    $("#al").innerHTML = `<div class="hd"><h2>Events</h2><span class="sub">${cur.length} events · points needed to finish at each rank</span></div>` + table(["Ended", "Region", "Gamemode", "Event", ...ARCH.map(r => "#" + r.toLocaleString())], cur.slice(0, 400).map(w => [fmt(w.end), w.region, esc(gm(w.category)), star(w.window_id) + link(w.window_id, w.name), ...ARCH.map(r => nf(w.cutoffs[r]))]), ["", "", "", "", ...ARCH.map(() => "n")]);
    trend();
  };
  const trend = () => {
    const old = Chart.getChart($("#ar")); if (old) old.destroy();
    const rows = cur.filter(w => w.cutoffs[TR] > 0).sort((a, b) => a.end - b.end);
    if (rows.length < 2) { $("#ar-take").innerHTML = take("warn", "Not enough events match the filters for a trend."); return; }
    // one gamemode selected: a line per region. Otherwise dots coloured by gamemode (they score very differently).
    const byClass = !FILT.cls, key = w => byClass ? w.category : w.region;
    const counts = {}; rows.forEach(w => counts[key(w)] = (counts[key(w)] || 0) + 1);
    const names = Object.keys(counts).sort((a, b) => counts[b] - counts[a]), shown = byClass ? names.slice(0, 7) : names;
    const grp = w => shown.includes(key(w)) ? key(w) : "Other";
    const keys = byClass && names.length > 7 ? [...shown, "Other"] : shown;
    mk($("#ar"), { type: "scatter", zoom: "x", clickMode: "nearest", clickIntersect: true, click: hit => { const r = hit.element.$context.raw; if (r && r.id) location.hash = "#/t/" + encodeURIComponent(r.id); }, data: { datasets: keys.map((k, i) => ({ label: byClass ? gm(k) : k, showLine: !byClass, data: rows.filter(w => grp(w) === k).map(w => ({ x: w.end, y: w.cutoffs[TR], n: w.name, r: w.region, c: w.category, id: w.window_id })), borderColor: SER(i), backgroundColor: withAlpha(SER(i), byClass ? .8 : 1), borderWidth: 1.4, pointRadius: 4, pointHoverRadius: 7 })) }, options: { interaction: { mode: "nearest", intersect: true }, scales: { x: { type: "linear", ticks: { maxTicksLimit: 8, callback: v => new Date(v * 1000).toLocaleDateString([], { month: "short", day: "numeric" }) }, title: { text: "Date the window ended" } }, y: { title: { text: "Points for top " + TR.toLocaleString() } } }, plugins: { tooltip: { callbacks: { title: c => c[0].raw.n, label: c => `${gm(c.raw.c)} · ${c.raw.r} · ${new Date(c.parsed.x * 1000).toLocaleDateString()}: ${nf(c.parsed.y)}` } } } } });
    const v = rows.map(w => w.cutoffs[TR]).sort((a, b) => a - b), med = v[v.length >> 1];
    $("#ar-take").innerHTML = take(byClass ? "warn" : "", byClass ? `${rows.length} events across every gamemode: median <b>${nf(med)}</b>, but the range is ${nf(v[0])} – ${nf(v[v.length - 1])} because gamemodes score very differently. Pick a <b>Gamemode</b> above to see one clean trend per region.` : `${rows.length} events: median points for top ${TR.toLocaleString()} <b>${nf(med)}</b>, from ${nf(v[0])} to ${nf(v[v.length - 1])}. Each line is one region.`);
    $("#ar-tbl").innerHTML = table(["Ended", "Region", "Event", "Points"], rows.slice(-60).reverse().map(w => [fmt(w.end), w.region, esc(w.name), nf(w.cutoffs[TR])]), ["", "", "", "n"]);
  };
  bindFilters(draw);
  $("#arr").onchange = () => { TR = +$("#arr").value; store.set("archrank", TR); trend(); };
  $("#csv").onclick = () => {
    const lines = [["event", "window_id", "region", "class", "ended", ...ARCH.map(r => "rank_" + r)].join(",")].concat(cur.map(w => [`"${w.name}"`, w.window_id, w.region, w.category, new Date(w.end * 1000).toISOString(), ...ARCH.map(r => w.cutoffs[r] ?? "")].join(",")));
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })); a.download = "fn-archive.csv"; a.click();
  };
  draw();
}

// ---------------------------------------------------------------- Gamemodes
async function classes() {
  const d = await j("/api/classes");
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  app.innerHTML = head("Gamemodes", "Each gamemode is kept separate. History is only ever compared within the same gamemode.") +
    `<div class="evgrid">` + d.map(c => `<a class="ev" href="#/class/${encodeURIComponent(c.category)}"><div class="t">${esc(gm(c.category))}</div><div class="small">${c.events} finished · ${c.upcoming} upcoming</div><div class="kpis" style="margin:0;grid-template-columns:repeat(3,1fr)">${Object.entries(c.median).slice(0, 3).map(([r, v]) => `<div class="kpi"><div class="l">Median #${r}</div><div class="v" style="font-size:1.1rem">${nf(v)}</div></div>`).join("")}</div><div class="go"><span></span><b>Open ›</b></div></a>`).join("") + "</div>";
}
const STD = [1, 10, 35, 50, 100, 250, 500, 1000, 2000, 5000, 10000];
const STAGES = [["open", "Open round (Round 1)"], ["later", "Later rounds"]];
const med = v => v.length ? (v[(v.length - 1) >> 1] + v[v.length >> 1]) / 2 : null;
const qt = (v, f) => v[Math.min(v.length - 1, Math.floor(f * v.length))];
function cutStats(evs) {
  const t = {};
  STD.forEach(r => { const v = evs.map(e => e.cutoffs[r]).filter(x => x > 0).sort((a, b) => a - b); if (v.length) t[r] = { n: v.length, min: v[0], p25: qt(v, .25), median: med(v), p75: qt(v, .75), max: v[v.length - 1] }; });
  return t;
}
async function classPage(name) {
  const d = await j("/api/class?name=" + encodeURIComponent(name));
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const ev = d.events, regs = REGIONS.filter(r => ev.some(e => e.region === r)), stages = STAGES.filter(([k]) => ev.some(e => e.stage === k));
  let CF = Object.assign({ region: "", stage: "", by: "none" }, store.get("classf", {}));
  if (CF.region && !regs.includes(CF.region)) CF.region = "";
  if (CF.stage && !stages.some(s => s[0] === CF.stage)) CF.stage = "";
  app.innerHTML = `<div class="crumb"><a href="#/classes">Gamemodes</a> ›</div>` + head(esc(gm(name)), `${ev.length} finished events. Filter by region and stage, or compare them side by side.`) +
    `<div class="card"><div class="filters">
      <div><label>Region</label><select id="cfr"><option value="">All regions</option>${regs.map(r => `<option ${r === CF.region ? "selected" : ""}>${r}</option>`).join("")}</select></div>
      <div><label>Stage</label><select id="cfs"><option value="">All stages</option>${stages.map(([k, l]) => `<option value="${k}" ${k === CF.stage ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div style="flex:0 0 auto"><label>Compare</label><div class="seg" id="cfb">${[["none", "Range"], ["region", "By region"], ["stage", "By stage"]].map(([k, l]) => `<button data-b="${k}" class="${k === CF.by ? "on" : ""}">${l}</button>`).join("")}</div></div></div></div><div id="cbody"></div>`;
  const draw = () => {
    destroyCharts();
    const evs = ev.filter(e => (!CF.region || e.region === CF.region) && (!CF.stage || e.stage === CF.stage));
    if (!evs.length) { $("#cbody").innerHTML = '<div class="card empty">No events match these filters.</div>'; return; }
    const t = cutStats(evs), ranks = Object.keys(t).map(Number).sort((a, b) => a - b), m = r => t[r] ? nf(t[r].median) : "-";
    const stageName = k => (STAGES.find(s => s[0] === k) || [k, k || "unknown"])[1];
    const gname = g => CF.by === "stage" ? stageName(g) : g;
    const groupKey = CF.by === "region" ? (e => e.region) : CF.by === "stage" ? (e => e.stage || "unknown") : null;
    const order = CF.by === "region" ? REGIONS : STAGES.map(s => s[0]).concat("unknown");
    const groups = groupKey ? order.map(g => [g, evs.filter(e => groupKey(e) === g)]).filter(([, v]) => v.length) : [];
    $("#cbody").innerHTML = `<div class="kpis">${kpi("Events", evs.length)}${kpi("Median top 1", m(1))}${kpi("Median top 100", m(100), "", "hero")}${kpi("Median top 1,000", m(1000))}${kpi("Median top 5,000", m(5000))}</div>
      <div class="grid g2">${chartCard("cf", groupKey ? "Median points at each rank, by " + CF.by : "Points needed at each rank", groupKey ? "one line per " + CF.by : "range across the selected events", { cls: "tall", table: false, zoom: true })}${chartCard("cc", "Cutoffs across events", "oldest to newest · click a point to open that event", { cls: "tall", table: false })}</div>
      <div id="ctake"></div>
      <div class="card"><div class="hd"><h2>Points needed to reach each rank</h2></div>${table(["Rank", "Events", "Min", "25%", "Median", "75%", "Max"], ranks.map(r => ["Top " + r.toLocaleString(), t[r].n, nf(t[r].min), nf(t[r].p25), `<b>${nf(t[r].median)}</b>`, nf(t[r].p75), nf(t[r].max)]), ["", "n", "n", "n", "n", "n", "n"])}</div>
      <div class="card"><div class="hd"><h2>Events</h2><span class="sub">${evs.length}</span></div>${table(["Ended", "Region", "Stage", "Event", "#1", "#100", "#1000"], evs.slice().reverse().map(e => [fmt(e.end), e.region, stageName(e.stage), link(e.window_id, e.name), nf(e.cutoffs[1]), nf(e.cutoffs[100]), nf(e.cutoffs[1000])]), ["", "", "", "", "n", "n", "n"])}</div>`;
    const logX = { type: "logarithmic", ticks: { maxRotation: 0, autoSkip: false, callback: v => [1, 10, 100, 500, 1000, 2000, 5000, 10000].includes(v) ? v.toLocaleString() : "" }, title: { text: "Rank (log scale)" } };
    const tip = { title: c => "Top " + nf(c[0].parsed.x), label: c => `${c.dataset.label}: ${nf(c.parsed.y)}` };
    if (!groupKey) {
      const P = k => ranks.map(r => ({ x: r, y: t[r][k] }));
      mk($("#cf"), { type: "line", zoom: "x", data: { datasets: [
        { label: "Min", data: P("min"), borderColor: "transparent", pointRadius: 0, fill: false },
        { label: "Min – max", data: P("max"), borderColor: "transparent", backgroundColor: withAlpha(SER(0), .12), pointRadius: 0, fill: "-1" },
        { label: "25%", data: P("p25"), borderColor: "transparent", pointRadius: 0, fill: false },
        { label: "25 – 75%", data: P("p75"), borderColor: "transparent", backgroundColor: withAlpha(SER(0), .25), pointRadius: 0, fill: "-1" },
        { label: "Median", data: P("median"), borderColor: SER(0), backgroundColor: SER(0), borderWidth: 3, pointRadius: 3 }] },
        options: { interaction: { mode: "nearest", axis: "x", intersect: false }, scales: { x: logX, y: { title: { text: "Points" } } }, plugins: { legend: { labels: { filter: i => !["Min", "25%"].includes(i.text) } }, tooltip: { callbacks: tip } } } });
      $("#ctake").innerHTML = "";
    } else {
      const gs = groups.map(([g, v]) => [g, cutStats(v), v.length]);
      mk($("#cf"), { type: "line", zoom: "x", data: { datasets: gs.map(([g, st, n]) => ({ label: `${gname(g)} (${n})`, data: ranks.filter(r => st[r] && st[r].n >= 2).map(r => ({ x: r, y: st[r].median })), borderColor: SER(order.indexOf(g)), backgroundColor: SER(order.indexOf(g)), borderWidth: 2.5, pointRadius: 3 })) }, options: { interaction: { mode: "nearest", axis: "x", intersect: false }, scales: { x: logX, y: { title: { text: "Median points" } } }, plugins: { tooltip: { callbacks: tip } } } });
      const at = [100, 1000].map(r => {
        const v = gs.filter(([, st]) => st[r] && st[r].n >= 2).map(([g, st]) => [g, st[r].median]).sort((a, b) => b[1] - a[1]);
        return v.length > 1 ? `At top ${r.toLocaleString()}, <b>${esc(gname(v[0][0]))}</b> needs the most (<b>${nf(v[0][1])}</b>) and <b>${esc(gname(v[v.length - 1][0]))}</b> the least (<b>${nf(v[v.length - 1][1])}</b>), a gap of ${pc(v[0][1] / v[v.length - 1][1] - 1)}.` : "";
      }).filter(Boolean);
      $("#ctake").innerHTML = at.length ? take("", at.join(" ")) : "";
    }
    mk($("#cc"), { type: "line", click: hit => { const e = evs[hit.index]; if (e) location.hash = "#/t/" + encodeURIComponent(e.window_id); }, data: { labels: evs.map(e => e.region + " " + new Date(e.end * 1000).toLocaleDateString([], { month: "short", day: "numeric" })),
      datasets: [1, 100, 1000, 5000].map((r, i) => ({ label: "Top " + r.toLocaleString(), data: evs.map(e => e.cutoffs[r] ?? null), borderColor: SER(i), backgroundColor: SER(i), pointRadius: 2 })) }, options: { scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 } }, y: { title: { text: "Points" } } } } });
  };
  const save = () => { store.set("classf", CF); draw(); };
  $("#cfr").onchange = () => { CF.region = $("#cfr").value; save(); };
  $("#cfs").onchange = () => { CF.stage = $("#cfs").value; save(); };
  $$("#cfb button").forEach(b => b.onclick = () => { CF.by = b.dataset.b; $$("#cfb button").forEach(x => x.classList.toggle("on", x === b)); save(); });
  draw();
}

// ---------------------------------------------------------------- Players
async function players() {
  app.innerHTML = head("Players", "Look up anyone who reached the top 1,000 of a collected event.") + `<div class="card"><div class="row"><div><label>Search by name</label><input id="pq" placeholder="player name"></div>
    <div style="flex:0"><button id="pb">Search</button></div></div><div id="pr" style="margin-top:10px"></div></div><div class="card"><div class="hd"><h2>Strongest players so far</h2><span class="sub">average finishing share of the field, at least 3 events</span></div><div id="tp">${skel(1, 200)}</div></div>`;
  const search = async () => {
    const q = $("#pq").value.trim(); if (!q) return;
    const r = await j("/api/players?q=" + encodeURIComponent(q));
    $("#pr").innerHTML = (r.error || !r.length) ? '<p class="mut">No player found. Names are collected gradually for top finishers.</p>' : table(["Player", "Events"], r.map(p => [`<a href="#/player/${p.id}">${esc(p.name)}</a>`, p.events]), ["", "n"]);
  };
  $("#pb").onclick = search; $("#pq").onkeydown = e => { if (e.key === "Enter") search(); };
  const t = await j("/api/players");
  $("#tp").innerHTML = (t.error || !t.length) ? '<p class="mut">Not enough data yet.</p>' : table(["#", "Player", "Events", "Avg top %", "Best"], t.map((p, i) => [i + 1, `<a href="#/player/${p.id}">${esc(p.name)}</a>`, p.events, p.avg_top_pct + "%", "#" + p.best]), ["", "", "n", "n", "n"]);
}
// "My results": the same data as a player page, for the account added in the top bar, with how you are trending
async function myPage() {
  if (!ACCT) { app.innerHTML = head("My results", "Your finishes across every collected event, and how you are trending.") + `<div class="card empty">Add your Epic account once (top right) and your results appear here.<br><br><button id="ap-open2">Add my account</button></div>`; $("#ap-open2").onclick = e => { e.stopPropagation(); acctPop(); }; return; }
  return playerPage(ACCT.id, true);
}
async function playerPage(id, mine) {
  const d = await j("/api/player?id=" + encodeURIComponent(id));
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const ev = d.events.slice().reverse();
  if (mine && !ev.length) { app.innerHTML = head("My results", esc(d.name)) + `<div class="card empty">No top-1,000 finishes recorded yet for ${esc(d.name)}.<br>The site stores ranks 1 to 1,000 of every collected event, so results appear once you finish that high. Your live rank in a current event shows on the event page.</div>`; return; }
  const ppg = e => e.games ? e.points / e.games : null, avg = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : null;
  const recent = ev.slice(-5).map(ppg).filter(x => x != null), before = ev.slice(-10, -5).map(ppg).filter(x => x != null);
  const trend = recent.length >= 2 && before.length >= 2 ? avg(recent) - avg(before) : null;
  const mineKpis = mine ? `<div class="kpis">${kpi("Finishes", d.events.length, "top 1,000 in collected events", "hero")}${kpi("Best rank", "#" + nf(Math.min(...ev.map(e => e.rank))))}${kpi("Median rank", "#" + nf(med(ev.map(e => e.rank).sort((a, b) => a - b))))}${kpi("Points per game, last 5", nd(avg(recent)), trend == null ? "" : (trend >= 0 ? "+" : "") + nd(trend) + " vs the 5 before", trend != null && trend >= 0 ? "good" : trend != null ? "bad" : "")}${kpi("Wins", ev.reduce((s, e) => s + (e.wins || 0), 0))}</div>` : "";
  app.innerHTML = (mine ? "" : `<div class="crumb"><a href="#/players">Players</a> ›</div>`) + head(mine ? "My results" : esc(d.name), mine ? `${esc(d.name)} · ${d.events.length} top-1000 finishes recorded` : `${d.events.length} top-1000 finishes recorded`) + mineKpis +
    `<div class="card"><div class="hd"><h2>By gamemode</h2></div>${table(["Gamemode", "Events", "Best", "Median", "Avg top %", "Pts / game", "Wins", "Elims / game"], d.summary.map(s => [esc(gm(s.category)), s.events, "#" + s.best_rank, "#" + s.median_rank, s.avg_top_pct + "%", s.pts_per_game ?? "-", s.wins, s.elims_per_game ?? "-"]), ["", "n", "n", "n", "n", "n", "n", "n"])}</div>
    <div class="grid g2">${chartCard("pr1", "Finishing rank by event", "higher is better", { table: false })}${chartCard("pr2", "Points per game by event", "", { table: false })}</div>
    <div class="grid g2">${chartCard("pr3", "Eliminations per game by event", "how aggressive", { table: false })}${chartCard("pr4", "Average placement by event", "1 is best", { table: false })}</div>
    <div class="card"><div class="hd"><h2>Events</h2></div>${table(["Date", "Event", "Region", "Gamemode", "Rank", "Points", "Games", "Avg place", "Wins"], d.events.map(e => [fmt(e.end), link(e.window_id, e.name), e.region, esc(gm(e.category)), "#" + e.rank, nf(e.points), e.games, e.avg_place ?? "-", e.wins]), ["", "", "", "", "n", "n", "n", "n", "n"])}</div>`;
  const lab = ev.map(e => new Date(e.end * 1000).toLocaleDateString([], { month: "short", day: "numeric" }));
  mk($("#pr1"), { type: "line", data: { labels: lab, datasets: [{ label: "Rank", data: ev.map(e => e.rank), borderColor: SER(0), backgroundColor: SER(0), pointRadius: 3 }] }, options: { scales: { y: { reverse: true, type: "logarithmic", title: { text: "Rank (log, 1 at the top)" } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => ev[c[0].dataIndex].name, label: c => "Rank #" + nf(c.parsed.y) } } } } });
  mk($("#pr3"), { type: "bar", data: { labels: lab, datasets: [{ label: "Elims per game", data: ev.map(e => e.games ? +(e.elims / e.games).toFixed(2) : null), backgroundColor: SER(1) }] }, options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => ev[c[0].dataIndex].name } } }, scales: { y: { beginAtZero: true } } } });
  mk($("#pr4"), { type: "line", data: { labels: lab, datasets: [{ label: "Average placement", data: ev.map(e => e.avg_place), borderColor: SER(2), backgroundColor: SER(2), pointRadius: 3 }] }, options: { scales: { y: { reverse: true, title: { text: "Placement (1 = best)" } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => ev[c[0].dataIndex].name } } } } });
  mk($("#pr2"), { type: "bar", data: { labels: lab, datasets: [{ label: "Points per game", data: ev.map(e => e.games ? +(e.points / e.games).toFixed(1) : null), backgroundColor: SER(0) }] }, options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => ev[c[0].dataIndex].name } } }, scales: { y: { beginAtZero: true } } } });
}

// ---------------------------------------------------------------- FNCS
async function fncs() {
  const d = await j("/api/fncs");
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const rows = REGION ? d.filter(w => w.region === REGION) : d;
  const groups = {}; rows.forEach(w => (groups[w.name.split(" · ")[0]] ||= []).push(w));
  app.innerHTML = head("FNCS tracker" + (REGION ? " · " + REGION : ""), "Qualifiers → Heats → Last Chance → Final. For each window: the places that advance, the real cutoff once finished, and the predicted cutoff while it runs.") +
    Object.entries(groups).map(([g, ws]) => `<div class="card"><div class="hd"><h2>${esc(g)}</h2></div>${table(["Start", "Region", "Window", "Status", "Games", "Advancement cutoffs", ""], ws.map(w => [fmt(w.begin), w.region, link(w.window_id, w.name.split(" · ").slice(1).join(" · ") || w.name), pill(w.status), w.match_cap || "?",
      w.advance.map(a => `Top ${a.rank}: ${a.actual != null ? `<b>${nf(a.actual)}</b> pts` : a.predicted ? `~<b>${nf(a.predicted.likely)}</b> <small>(${nf(a.predicted.low)}–${nf(a.predicted.safe)})</small>` : "<small>not yet</small>"}`).join("<br>") || "<small>no cutoff</small>", link(w.window_id, "Plan ›", "strategy")]))}</div>`).join("") || '<div class="card empty">Nothing to show.</div>';
}

// ---------------------------------------------------------------- Accuracy
async function accuracy() {
  const d = await j("/api/accuracy");
  if (d.error) return app.innerHTML = `<div class="card err">${esc(d.error)}</div>`;
  const b = d.buckets, list = d.list || [];
  const lab = x => x.progress === 0 ? "Start" : Math.round(x.progress * 100) + "%";
  const evOpt = list.map((e, i) => `<option value="${i}">${esc(e.name)} · ${esc(e.region)} · ${new Date((e.end || 0) * 1000).toLocaleDateString([], { month: "short", day: "numeric" })}</option>`).join("");
  app.innerHTML = head("Prediction accuracy", `Every finished tournament is predicted automatically as of its start, from earlier events only, and every live one is predicted while it runs. Each prediction is compared with the real final cutoff. <b>${d.events}</b> of ${d.finished} finished tournaments scored so far (${d.live_events} also predicted live).`) +
    (b.length ? `<div class="grid g2">${chartCard("ac1", "How far off were the predictions?", "average error and bias, by how far through the event", { table: false })}${chartCard("ac2", "Predicted at different times vs the real end", "the line is what the site predicted as the event went on", { table: false, ctrl: `<label style="margin:0">Tournament</label><select id="acev" style="width:auto;max-width:100%;margin:0">${evOpt}</select><label style="margin:0">Rank</label><select id="acrk" style="width:auto;margin:0"></select>` })}</div>
    <div class="card"><div class="hd"><h2>Details</h2></div>${table(["Point in event", "Tournaments", "Predictions", "Average error", "Typical error (median)", "Bias", "Real result inside range"], b.map(x => [lab(x), x.events, x.n, x.mean_abs_error_pct + "%", x.median_abs_error_pct + "%", (x.bias_pct > 0 ? "+" : "") + x.bias_pct + "%", x.inside_range_pct + "%"]), ["", "n", "n", "n", "n", "n", "n"])}<p class="small">Error = how far the guess was from the real cutoff, as a share of it. Bias above 0 means the site guessed too high on average, below 0 too low. "Start" is the prediction made before the event opened. Range = low to safe, aimed at 90%.</p></div>` : '<div class="card empty">No finished predictions to score yet. They are made automatically while events run and as the history is scored.</div>');
  if (!b.length) return;
  mk($("#ac1"), { type: "bar", data: { labels: b.map(lab), datasets: [{ label: "Average error", data: b.map(x => x.mean_abs_error_pct), backgroundColor: SER(0) }, { label: "Bias (+ = too high)", data: b.map(x => x.bias_pct), backgroundColor: SER(1) }] }, options: { scales: { x: { title: { text: "Share of the event elapsed" } }, y: { title: { text: "% of the real cutoff" } } }, plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y}%` } } } } });
  const draw = () => {
    const e = list[+$("#acev").value]; if (!e) return;
    const rs = Object.keys(e.ranks).map(Number).sort((a, c) => a - c), sel = $("#acrk");
    const keep = sel.value && e.ranks[sel.value] ? sel.value : String(rs.includes(100) ? 100 : rs[0]);
    sel.innerHTML = rs.map(r => `<option value="${r}" ${String(r) === keep ? "selected" : ""}>Top ${nf(r)}</option>`).join("");
    const r = e.ranks[keep]; if (!r) return;
    const pts = r.points, pct = p => Math.round(p * 100);
    const xy = k => pts.map(p => ({ x: pct(p[0]), y: p[k] }));
    mk($("#ac2"), { type: "line", data: { datasets: [
      { label: "Predicted (safe)", data: xy(3), borderColor: SER(2), borderDash: [4, 4], pointRadius: 0, fill: false },
      { label: "Predicted (likely)", data: xy(2), borderColor: SER(0), backgroundColor: SER(0), pointRadius: 3 },
      { label: "Predicted (low)", data: xy(1), borderColor: SER(2), borderDash: [4, 4], pointRadius: 0, fill: "-2", backgroundColor: withAlpha(SER(2), 0.15) },
      { label: "Real final cutoff", data: [{ x: 0, y: r.actual }, { x: 100, y: r.actual }], borderColor: SER(3), borderWidth: 2.5, pointRadius: 0 }] },
      options: { interaction: { mode: "nearest", intersect: false }, scales: { x: { type: "linear", min: 0, max: 100, title: { text: "Share of the event elapsed when the prediction was made" }, ticks: { callback: v => v + "%" } }, y: { beginAtZero: true, title: { text: "Points" } } }, plugins: { tooltip: { callbacks: { title: c => c.length ? c[0].parsed.x + "% through" : "", label: c => `${c.dataset.label}: ${nf(c.parsed.y)} pts` } } } } });
  };
  $("#acev").onchange = () => { $("#acrk").innerHTML = ""; draw(); }; $("#acrk").onchange = draw; draw();
}

// ---------------------------------------------------------------- Status
async function status() {
  const [s, a] = await Promise.all([j("/api/status_full"), j("/api/status")]);
  if (s.error) return app.innerHTML = `<div class="card err">${esc(s.error)}</div>`;
  const c = s.counts || {};
  app.innerHTML = head("Status", "Is the collector running, and is Epic login valid?") + `<div class="kpis">
   ${kpi("Collector last ran", ago(s.last_tick_age_s), "", s.last_tick_age_s != null && s.last_tick_age_s < 150 ? "good" : "bad")}
   ${kpi("Epic login", s.login.logged_in ? "valid" : "needed", "", s.login.logged_in ? "good" : "bad")}
   ${kpi("Events stored", (c.final ?? "-") + " / " + (c.windows ?? "-"))}
   ${kpi("Database", (c.db_mb ?? "-") + " MB")}</div>
  <div class="card"><div class="hd"><h2>Details</h2></div><p class="small">Regions tracked: ${esc((s.regions || []).join(", "))}. Windows: ${esc(JSON.stringify(s.windows_by_status))}.<br>
   Data read out of the database this month ≈ <b>${s.egress_mb_month} MB</b> (free plan allows 5,000 MB). Snapshots ${c.snapshots} · series points ${c.series} · stored predictions ${c.predictions} · player names ${c.names} · events still needing deep thresholds ${c.deep_missing}.</p>
   <h3>Epic login events</h3><pre class="small" style="white-space:pre-wrap">${esc((s.auth_log || []).map(x => new Date(x.at * 1000).toLocaleTimeString() + "  " + x.kind + "  " + x.detail).join("\n") || "none yet")}</pre>
   <h3>Last collector pass</h3><pre class="small" style="white-space:pre-wrap">${esc((s.last_tick || []).map(x => x.join(" ")).join("\n"))}</pre></div>
  <div class="card"><b>Permanent Epic login ${a.permanent ? "(active)" : "(not set up)"}</b><p class="small">${a.permanent ? "The collector logs in by itself with a stored device login, no more pasting codes. Run the steps below again only to replace it." : "Set this up once and the collector never needs a code again. Be logged in to Epic in this browser, then: 1) enter the admin key and press Start, 2) open the link it shows and approve, 3) press Finish."}</p>
   <input id="dkey" type="password" placeholder="Admin key"><div class="chips" style="margin-top:10px"><button id="dst">1) Start</button><button id="dfin" class="sec">3) Finish</button></div><div id="dlm" class="small" style="margin-top:8px"></div></div>
  ${s.login.logged_in ? "" : `<div class="card"><b>Epic login needed</b><p class="small">Log in to Epic in this browser, open <a href="${esc(a.login_url)}" target="_blank">this link</a>, copy the authorizationCode and paste it here.</p>
   <input id="code" placeholder="authorizationCode"><input id="key" type="password" placeholder="Admin key" style="margin-top:6px"><button id="lg" style="margin-top:10px">Save login</button> <span id="lm" class="small"></span></div>`}
  <div class="card"><div class="hd"><h2>Feedback from visitors</h2><span class="sub">owner only</span></div><div class="row"><div><input id="fk" type="password" placeholder="Admin key"></div><div style="flex:0"><button class="sec" id="fkb">Load</button></div></div><div id="fkl" style="margin-top:10px"></div></div>
    <div class="card"><div class="hd"><h2>How the predictions work</h2></div><p class="small">Every player on the live leaderboard is replayed forward. Their remaining games (including the last queue that starts before the cutoff), points per game and chance of catching up come from players in the same spot at the same moment in earlier events <b>of the same gamemode</b> (the closest gamemodes when there is none yet). The result is corrected using a back-test on those past events. Ranks beyond 700 are scaled from the stored thresholds (ranks 1000, 1500 … 10000). Unofficial data; estimates only.</p></div>`;
  $("#fkb").onclick = async () => { const r = await j("/api/feedback", { headers: { "x-admin-key": $("#fk").value } }); $("#fkl").innerHTML = r.error ? `<span class="err">${esc(r.error)}</span>` : (r.length ? table(["When", "Kind", "Page", "Message"], r.map(x => [fmt(x.at), esc(x.kind), esc(x.page), esc(x.text)])) : '<p class="mut">Nothing yet.</p>'); };
  const dcall = async (finish) => {
    $("#dlm").textContent = "Working...";
    const r = await j("/api/login_device", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key: $("#dkey").value, finish }) });
    if (!r.ok) $("#dlm").innerHTML = `<span class="err">${esc(r.error || "failed")}</span>`;
    else if (r.pending) $("#dlm").textContent = "Epic has not seen the approval yet: open the link, approve, then press Finish again.";
    else if (r.url) $("#dlm").innerHTML = `2) Open <a href="${esc(r.url)}" target="_blank">this Epic page</a> (code ${esc(r.user_code || "")}), approve, then press <b>3) Finish</b>. (via ${esc(r.client)})`;
    else $("#dlm").textContent = "Permanent login saved and tested (" + r.client + "). Reload this page.";
  };
  $("#dst").onclick = () => dcall(false);
  $("#dfin").onclick = () => dcall(true);
  const lg = $("#lg");
  if (lg) lg.onclick = async () => {
    const r = await j("/api/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ code: $("#code").value.trim(), key: $("#key").value }) });
    $("#lm").textContent = r.ok ? "Logged in." : (r.error || "failed");
  };
}

// ---------------------------------------------------------------- Router
async function route() {
  clearAll();
  const h = location.hash.replace(/^#\/?/, ""), parts = h.split("/"), p = parts[0];
  const page = p || "home", arg = decodeURIComponent(parts.slice(1).join("/"));
  setNav(page, parts[2]);
  window.scrollTo(0, 0);
  try {
    if (page === "home") { HOME_SIG = ""; await home(); every(30000, () => home(true)); }
    else if (page === "strategy") await strategyHub();
    else if (page === "t") await tournament(decodeURIComponent(parts[1] || ""), parts[2]);
    else if (page === "schedule") await schedule();
    else if (page === "archive") await archive();
    else if (page === "classes") await classes();
    else if (page === "class") await classPage(arg);
    else if (page === "players") await players();
    else if (page === "player") await playerPage(arg);
    else if (page === "me") await myPage();
    else if (page === "drops") await dropsPage(arg);
    else if (page === "map") await mapPage(arg);
    else if (page === "rotations") await rotationsPage(arg);
    else if (page === "fncs") await fncs();
    else if (page === "accuracy") await accuracy();
    else if (page === "status") await status();
    else app.innerHTML = '<div class="card">Page not found.</div>';
  } catch (e) { app.innerHTML = `<div class="card err">Something went wrong: ${esc(e.message)}</div>`; console.error(e); }
}
// live data health: tell visitors when the collector is paused (Epic login expired or no pass for a while)
async function checkHealth() {
  try {
    const s = await j("/api/health"), el = $("#banner"); if (!el || s.error) return;
    const idle = s.idle_s, down = s.logged_in === false || (idle != null && idle > 900);
    el.hidden = !down;
    const lv = $("#live"); if (lv) { lv.classList.toggle("off", down); $("#livet").textContent = down ? "Live data paused" : "Collector live"; $("#livep").textContent = idle != null ? "Last update " + ago(idle) : ""; }
    if (down) el.innerHTML = `<b>Live data is paused.</b> ${s.logged_in === false ? "The Epic login behind the collector needs renewing" : "The collector has not run for " + Math.round(idle / 60) + " minutes"}${idle != null ? " (last update " + ago(idle) + ")" : ""}. Boards and live predictions may be out of date; stored history still works. <a href="#/status">Status</a>`;
  } catch (e) { }
}
checkHealth(); setInterval(checkHealth, 60000);
window.addEventListener("hashchange", route);
route();
