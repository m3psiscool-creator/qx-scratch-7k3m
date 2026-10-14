"use strict";
// The Strategy tab of a tournament: plan, scoring, finishers, pace, safety margin, stop-or-keep-playing.
const CONFS = [[0.5, "Likely (50%)"], [0.8, "Comfortable (80%)"], [0.95, "Safe (95%)"]];
const lerp = (arr, x) => { if (!arr || !arr.length) return 0; const i = clamp(x, 0, arr.length - 1), a = Math.floor(i), b = Math.ceil(i); return arr[a] + (arr[b] - arr[a]) * (i - a); };
const ptsAtPlace = (sc, p) => p < 1 ? sc.placement[0] : p > sc.placement.length ? 0 : lerp(sc.placement, p - 1) + (p <= 1 ? sc.win_bonus : 0);
const ptsAtElims = (sc, e) => lerp(sc.elim, e);
// smallest average placement that still earns `need` placement points (null = impossible)
function placeForPts(sc, need) {
  if (need <= 0) return sc.placement.length + 1;
  if (need > ptsAtPlace(sc, 1)) return null;
  for (let p = 1; p <= sc.placement.length + 1; p += 0.05) if (ptsAtPlace(sc, p) < need) return Math.max(1, p - 0.05);
  return sc.placement.length + 1;
}
let SS = null;                 // state of the open Strategy tab
const own = {};                // charts by section so one section can redraw alone
const put = (sec, c) => { (own[sec] ||= []).push(c); return c; };
const drop = sec => { (own[sec] || []).forEach(c => { try { c.destroy(); } catch (e) { } }); own[sec] = []; };
const saveSS = () => store.set("sp:" + SS.w.window_id, { rank: SS.rank, conf: SS.conf, played: SS.played, pts: SS.pts, aim: SS.aim, like: SS.like });

async function tabStrategy(w, open) {
  const saved = store.get("sp:" + w.window_id, {});
  SS = { w, rank: saved.rank || (w.goal ? w.goal.rank : 100), conf: saved.conf || 0.8, played: saved.played || 0, pts: saved.pts || 0, aim: saved.aim || 0, like: saved.like || "focus", d: {}, name: store.get("epicname", ""), me: null };
  const presets = [...new Set([...(w.goal ? [w.goal.rank] : []), 1, 10, 50, 100, 250, 500, 1000, 2500, 5000])].sort((a, b) => a - b);
  const sec = (n, id, t, s) => `<div class="sec-title" id="${id}"><span class="num">${n}</span><div><h2>${t}</h2><div class="sub">${s}</div></div></div>`;
  $("#panel").innerHTML = `
  <div class="sbar">
    <div class="row">
      <div style="flex:1.1"><label>Target: top…</label><input id="sx" type="number" min="1" max="10000" value="${SS.rank}"></div>
      <div style="flex:1.4"><label>How sure do you want to be?</label><select id="sconf">${CONFS.map(([v, l]) => `<option value="${v}" ${v === SS.conf ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div><label>Games I have played</label><input id="spl" type="number" min="0" max="${w.match_cap || 30}" value="${SS.played}"></div>
      <div><label>My points so far</label><input id="spt" type="number" min="0" value="${SS.pts}"></div>
      <div><label>Aim for (optional)</label><input id="saim" type="number" min="0" placeholder="points" value="${SS.aim || ""}"></div>
      <div style="flex:0"><button id="sgo">Update</button></div>
    </div>
    <div class="row" style="margin-top:10px"><div style="flex:2;min-width:220px"><label>My Epic name <span style="font-weight:500">(reads your points and games from the public leaderboard; no login needed)</span></label><input id="sme" placeholder="Epic display name" value="${esc(SS.name)}"></div><div style="flex:0"><button class="sec" id="smeb">Find me</button></div><div id="smemsg" class="small" style="flex:3;align-self:center;min-width:200px"></div></div>
    <div class="chips" style="margin-top:10px"><small>Quick pick:</small>${presets.map(p => `<button class="chip ${p === SS.rank ? "on" : ""}" data-sr="${p}">${w.goal && w.goal.rank === p ? "★ " : ""}Top ${p.toLocaleString()}</button>`).join("")}</div>

  </div>
    <div class="anchbar"><a href="#s-plan" data-a="s-plan">1 Plan</a><a href="#s-scoring" data-a="s-scoring">2 Scoring</a><a href="#s-fin" data-a="s-fin">3 Finishers</a><a href="#s-pace" data-a="s-pace">4 Pace</a><a href="#s-me" data-a="s-me">5 Your games</a><a href="#s-safe" data-a="s-safe">6 Safety</a><a href="#s-stop" data-a="s-stop">7 Keep playing?</a></div>
  ${sec(1, "s-plan", "Your plan", "How many points to aim for, and the ways to get there")}<div id="p-plan">${skel(2, 160)}</div>
  ${sec(2, "s-scoring", "What the scoring rewards", "Points per placement and per elimination in this event")}<div id="p-scoring">${skel(1, 160)}</div>
  ${sec(3, "s-fin", "What finishers actually did", "Per-game numbers of real players, from the closest finished event of this gamemode")}<div id="p-fin">${skel(2, 200)}</div>
  ${sec(4, "s-pace", "Pace tracker", "Where you should be after each game")}<div id="p-pace">${skel(1, 260)}</div>
  ${sec(5, "s-me", "Your games", "Read from the leaderboard by your Epic name")}<div id="p-me"><div class="card empty">Type your Epic name above and press <b>Find me</b> to load your points and every game you have played here.</div></div>
  ${sec(6, "s-safe", "Safety margin", "How much cushion each level of certainty costs")}<div id="p-safe">${skel(1, 260)}</div>
  ${sec(7, "s-stop", "Keep playing or stop?", "Your chance of reaching the cutoff as you play more games")}<div id="p-stop">${skel(1, 260)}</div>`;
  // controls
  const readPersonal = () => { SS.conf = +$("#sconf").value; SS.played = clamp(+$("#spl").value || 0, 0, 99); SS.pts = Math.max(0, +$("#spt").value || 0); SS.aim = Math.max(0, +$("#saim").value || 0); saveSS(); };
  const apply = async () => { const r = clamp(Math.round(+$("#sx").value || SS.rank), 1, 10000); const changed = r !== SS.rank; SS.rank = r; readPersonal(); $$("[data-sr]").forEach(b => b.classList.toggle("on", +b.dataset.sr === r)); if (changed) await loadRank(); else renderPersonal(); };
  $("#sgo").onclick = apply;
  const goMe = () => { SS.name = $("#sme").value.trim(); store.set("epicname", SS.name); loadMe(); };
  $("#smeb").onclick = goMe; $("#sme").addEventListener("keydown", e => { if (e.key === "Enter") goMe(); });
  ["sx", "sconf", "spl", "spt", "saim"].forEach(id => $("#" + id).addEventListener(id === "sconf" ? "change" : "change", apply));
  $$("[data-sr]").forEach(b => b.onclick = () => { $("#sx").value = b.dataset.sr; apply(); });
  $$(".anchbar a").forEach(a => a.onclick = e => { e.preventDefault(); $("#" + a.dataset.a).scrollIntoView({ behavior: "smooth" }); });
  // data that does not depend on the rank
  j("/api/scoring?window=" + encodeURIComponent(w.window_id)).then(s => { SS.d.scoring = s; renderScoring(); renderPersonal(); });
  j("/api/tempo?window=" + encodeURIComponent(w.window_id)).then(t => { SS.d.tempo = t; renderPersonal(); });
  if (SS.name) loadMe();
  await loadRank();
  if (open) { every(120000, () => loadRank(true)); every(180000, () => { if (SS.me && SS.me.found) loadMe(true); }); }
}

async function loadRank(quiet) {
  const w = SS.w, id = encodeURIComponent(w.window_id), r = SS.rank, mine = ++SS.tok || (SS.tok = 1);
  if (!quiet) ["plan", "fin", "pace", "safe", "stop"].forEach(k => { const e = $("#p-" + k); if (e && !SS.d.safety) e.innerHTML = skel(1, 200); });
  // each part draws as soon as its data arrives: the safety estimate is the slow one
  const pProf = quiet && SS.d.profile ? Promise.resolve() : j(`/api/profile?window=${id}&rank=${Math.min(r, 1000)}`).then(x => { if (SS.tok === mine) { SS.d.profile = x; renderFin(); renderPersonal(); } });
  const safe = await j(`/api/safety?window=${id}&rank=${r}`);
  if (SS.tok !== mine) return;
  const sig = JSON.stringify([r, safe.likely, safe.low, safe.safe, safe.current, safe.error]);
  if (quiet && sig === SS.sig) return;   // nothing moved: leave the charts alone instead of redrawing them
  SS.sig = sig; SS.d.safety = safe; renderPersonal();
  const target = safe && !safe.error ? safe.likely : 0;
  const pace = r <= 1000 ? await j(`/api/pace?window=${id}&rank=${r}${target ? "&target=" + target : ""}`) : { error: "Pace curves need a rank inside the stored top 1,000." };
  await pProf;
  if (SS.tok !== mine) return;
  SS.d.pace = pace; renderPersonal();
}
function renderPersonal() { renderPlan(); renderPace(); renderMe(); renderSafe(); renderStop(); }

// the cutoff to aim for at the chosen certainty
function aimPoints(conf) {
  const s = SS.d.safety;
  if (SS.aim) return SS.aim;
  if (!s || s.error) return null;
  if (s.final) return s.likely;
  const l = s.ladder.find(x => x.conf === (conf ?? SS.conf)); return l ? l.points : s.likely;
}
const capOf = () => SS.w.match_cap || (SS.d.pace && SS.d.pace.cap) || 12;
const confLabel = c => (CONFS.find(x => x[0] === c) || [0, Math.round(c * 100) + "%"])[1];

// ---------------------------------------------------------------- time: how many games really fit
// Game lengths come from /api/tempo: minutes per game (queue + time alive) at each finishing placement.
// Surviving longer scores more per game but leaves room for fewer games, so the plan prices both.
const gMin = p => { const t = SS.d.tempo; return !t || t.error ? null : lerp(t.by_place, clamp(p, 1, t.by_place.length) - 1); };
function timeLeftMin() {
  const w = SS.w, now = Date.now() / 1000, start = w.status === "finished" || w.status === "upcoming" ? w.begin : clamp(now, w.begin, w.end);   // a finished or not yet started event counts as its full window
  let left = (w.end - start) / 60;
  if (w.status === "upcoming" && SS.played > 0) { const g = gMin(typicalPlace()); left -= SS.played * (g || 0); }   // "what if I had played N games": they already used their time
  return Math.max(0, left);
}
// games you can start in the time left if you finish around placement p (a game may start right before the window closes)
const gamesFit = (p, left) => { const T = gMin(p); return T ? Math.min(left, Math.ceil(timeLeftMin() / T)) : left; };
const invElims = (sc, v) => { if (v <= 0) return 0; const top = sc.elim.length - 1; if (v > ptsAtElims(sc, top)) return null; for (let e = 0; e <= top; e += 0.05) if (ptsAtElims(sc, e) >= v) return e; return null; };
function typicalPlace() {
  if (SS.me && SS.me.found && SS.me.games_played >= 3) return SS.me.avg_place;   // your own average finish
  const f = SS.d.profile && !SS.d.profile.error ? SS.d.profile.focus : null; return f ? f.avg_place : 10; }
// where you would finish at your current points-per-game, given the games that fit
function projFinal() {
  const cap = capOf(), remCap = Math.max(0, cap - SS.played), games = SS.played + gamesFit(typicalPlace(), remCap);
  return SS.played > 0 ? { games, pts: SS.pts + SS.pts / SS.played * (games - SS.played) } : null;
}

// ---------------------------------------------------------------- 1 plan
function renderPlan() {
  const el = $("#p-plan"); if (!el) return; drop("plan");
  const sc = SS.d.scoring, pr = SS.d.profile, s = SS.d.safety, tp = SS.d.tempo && !SS.d.tempo.error ? SS.d.tempo : null;
  if (!sc || !pr || !s) return;
  if (sc.error) { el.innerHTML = `<div class="card empty">${esc(sc.error)}</div>`; return; }
  const T = aimPoints(), cap = capOf(), remCap = Math.max(0, cap - SS.played), need = T == null ? null : Math.max(0, T - SS.pts);
  const f = pr && !pr.error ? pr.focus : null, typ = typicalPlace(), Gt = gamesFit(typ, remCap);
  const ppgAt = (n, g) => n == null ? null : g ? n / g : (n > 0 ? Infinity : 0), ppg = ppgAt(need, Gt);
  const fmtMin = m => m == null ? "" : Math.round(m) + " min";
  let head = "";
  if (s.error && !SS.aim) head = `<div class="card flat"><b>No cutoff estimate yet.</b> <span class="mut">${esc(s.error)}</span><br><small>Type a number in "Aim for" above to plan against your own target.</small></div>`;
  const diff = f && ppg != null && isFinite(ppg) ? ppg / f.pts_per_game : null;
  const timeNote = tp && Gt < remCap ? take("warn", `<b>The format has ${remCap} games but only about ${Gt} fit in the time.</b> Surviving to around place ${nd(typ, 0)} takes about <b>${fmtMin(gMin(typ))}</b> a game, and the window leaves ${fmtMin(timeLeftMin())}. Dying early is faster (a bottom-half finish is about ${fmtMin(gMin(Math.max(typ, (tp.lobby || 30) * 0.75)))}), so aggression buys extra games but fewer placement points. The plan below counts only games that fit.`) : "";
  const verdict = diff == null ? "" : diff <= 0.85 ? take("good", `You need <b>${nd(ppg)} points a game</b> over ~${Gt} games, below the <b>${nd(f.pts_per_game)}</b> that players around #${pr.rank} averaged. A steady, safe style is enough.`)
    : diff <= 1.1 ? take("", `You need <b>${nd(ppg)} points a game</b> over ~${Gt} games, about what players around #${pr.rank} averaged (<b>${nd(f.pts_per_game)}</b>). Play like a typical finisher.`)
      : take("warn", `You need <b>${nd(ppg)} points a game</b> over ~${Gt} games, <b>${Math.round((diff - 1) * 100)}% more</b> than players around #${pr.rank} averaged (${nd(f.pts_per_game)}). That takes a win or several deep runs with elims.`);
  const kp = `<div class="kpis">
    ${kpi("Points to aim for", T == null ? "-" : nf(T), SS.aim ? "your own target" : s.final ? "final cutoff" : confLabel(SS.conf).toLowerCase() + " · now " + nf(s.current), "hero")}
    ${kpi("Games that fit", Gt + " <small>of " + remCap + "</small>", tp ? `about ${fmtMin(gMin(typ))} each at place ${nd(typ, 0)} · ${fmtMin(timeLeftMin())} left` : (SS.played ? SS.played + " played" : "format limit; game lengths unknown"), Gt < remCap ? "bad" : "")}
    ${kpi("Points still needed", need == null ? "-" : nf(need), SS.pts ? "you have " + nf(SS.pts) : "start of event")}
    ${kpi("Needed per game", ppg == null ? "-" : isFinite(ppg) ? nd(ppg) : "∞", f ? "finishers: " + nd(f.pts_per_game) : "")}
    ${kpi("Typical finisher", f ? "place " + nd(f.avg_place) : "-", f ? nd(f.elims_per_game) + " elims · wins " + pc(f.win_rate) : "")}</div>`;
  if (!sc.per_elim && sc.placement.length < 3) {
    el.innerHTML = head + kp + timeNote + verdict + `<div class="card"><p>${sc.placement.length === 1 ? "Only a win scores in this event, so the plan is simply: win as many games as you can." : "Eliminations do not score here, so only placement matters."} ${esc(sc.text)}</p></div>`; return;
  }
  const lobby = Math.min(tp ? tp.lobby : sc.placement.length + 1, 45), pGrid = Array.from({ length: lobby * 2 - 1 }, (_, i) => 1 + i * 0.5);
  const maxE = Math.min(Math.max(sc.elim_cap || 8, 3), 12);
  // frontier: for each average placement, the eliminations per game you would need, given the games that fit at that placement
  const line = conf => {
    const t = SS.aim && conf === SS.conf ? SS.aim : (s.ladder || []).find(x => x.conf === conf)?.points ?? (s.final ? s.likely : null);
    if (t == null) return null;
    const n = Math.max(0, t - SS.pts);
    return { conf, data: pGrid.map(p => { const G = gamesFit(p, remCap), g = ppgAt(n, G), e = isFinite(g) ? invElims(sc, g - ptsAtPlace(sc, p)) : null; return { x: e == null ? null : Math.min(e, maxE), y: p, games: G, ppg: g, over: e != null && e > maxE }; }).filter(d => d.x != null) };
  };
  const lines = (SS.aim ? [line(SS.conf)] : [0.5, 0.8, 0.95].map(line)).filter(Boolean);
  const cols = [SER(2), SER(0), SER(3)];
  const ds = lines.map((l, i) => ({ type: "line", label: SS.aim ? "Your aim " + nf(SS.aim) : confLabel(l.conf), data: l.data, borderColor: cols[i], backgroundColor: cols[i], borderWidth: l.conf === SS.conf ? 3 : 1.6, borderDash: l.conf === SS.conf ? [] : [6, 4], pointRadius: 0, pointHoverRadius: 4, spanGaps: false, order: 1 }));
  if (f && pr.focus.scatter) ds.push({ type: "scatter", label: `Finishers around #${pr.rank}`, data: pr.focus.scatter.map(a => ({ x: a[1], y: a[0], pts: a[2] })), backgroundColor: withAlpha(cssv("--tx2"), .45), borderColor: "transparent", pointRadius: 3.5, pointHoverRadius: 6, order: 2 });
  const ex0 = SS.ex || { p: Math.round(clamp(typ, 1, lobby) * 2) / 2, e: Math.round(clamp(f ? f.elims_per_game : 3, 0, maxE) * 4) / 4 };
  ds.push({ type: "scatter", label: "Your playstyle", data: [{ x: ex0.e, y: ex0.p }], backgroundColor: SER(1), borderColor: cssv("--sf"), borderWidth: 2, pointStyle: "rectRot", pointRadius: 9, pointHoverRadius: 11, order: 0 });
  const heatP = [1, 2, 3, 5, 7, 10, 15, 20, 25].filter(p => p <= sc.placement.length), heatE = [0, 1, 2, 3, 4, 5, 6, 8, 10].filter(e => e <= Math.max(3, sc.elim_cap || 10));
  const fp = f ? f.avg_place : null, fe = f ? f.elims_per_game : null;
  const near = (arr, v) => arr.reduce((b, x) => Math.abs(x - v) < Math.abs(b - v) ? x : b, arr[0]);
  const cell = (p, e) => ptsAtPlace(sc, p) + ptsAtElims(sc, e);
  const heat = `<div class="scroll"><div class="heat" style="grid-template-columns:120px repeat(${heatE.length},1fr)"><div class="h">Place · games that fit ↓ &nbsp; Elims →</div>${heatE.map(e => `<div class="h">${e}</div>`).join("")}` +
    heatP.map(p => { const G = gamesFit(p, remCap), need1 = ppgAt(need, G); return `<div class="h" style="text-align:right;padding-right:8px">${p === 1 ? "win" : "top " + p} · ${G}g</div>` + heatE.map(e => {
      const v = cell(p, e), ok = need1 != null && v >= need1, k = need1 ? clamp((v / need1 - 1) / 0.6, 0, 1) : 0, isF = f && p === near(heatP, fp) && e === near(heatE, fe);
      return `<div data-hp="${p}" data-he="${e}" class="${ok ? "yes" : ""} ${isF ? "need" : ""}" style="${ok ? `background:color-mix(in srgb,var(--s1) ${Math.round(45 + k * 55)}%,var(--sf2))` : ""}" title="Average place ${p}, ${e} elims: ${nf(v)} points a game. About ${G} games fit, so ${nf(v * G)} points; you need ${need1 == null ? "?" : nf(need1)} a game">${nf(v)}</div>`;
    }).join(""); }).join("") + `</div></div>`;
  // the worst average placement that still reaches the target with a given elim average (games priced at that placement)
  const recs = [1, 3, 6].filter(e => e <= Math.max(3, sc.elim_cap || 6)).map(e => {
    let best = null;
    if (need != null) for (const p of pGrid) { const G = gamesFit(p, remCap), g = ppgAt(need, G); if (isFinite(g) && cell(p, e) >= g) best = p; }
    const G = best ? gamesFit(best, remCap) : null;
    const txt = need == null ? "-" : need === 0 ? "Any placement" : best == null ? "Not possible" : "Top " + Math.max(1, Math.round(best));
    return `<div class="recipe"><b>Average ${e} elim${e > 1 ? "s" : ""} a game</b><div class="big">${txt}</div><small>${best == null ? "not enough even with a win every game" : need === 0 ? "" : `average finish needed · about ${G} games fit`}</small></div>`;
  }).join("");
  el.innerHTML = head + kp + timeNote + verdict + `
  <div class="grid g3" style="margin-top:16px">${recs}</div>
  ${chartCard("c-front", "Trade-off: elims against placement", "Reach any point on or beyond a line to hit that certainty", { cls: "tall", zoom: true })}
  <div class="card" id="explore"><div class="hd"><h2>Try a playstyle</h2><span class="sub">drag the sliders, click a point on the chart, or click a cell in the grid below</span></div>
    <div class="explore"><div><label>Average placement <span class="rv" id="ex-pv"></span></label><input id="ex-p" type="range" min="1" max="${lobby}" step="0.5"></div><div><label>Average eliminations per game <span class="rv" id="ex-ev"></span></label><input id="ex-e" type="range" min="0" max="${maxE}" step="0.25"></div></div>
    <div class="kpis" id="ex-out" style="margin:14px 0 0"></div></div>
  ${tp ? `<div class="grid g2">${chartCard("c-tm", "How long a game takes", "minutes, including the wait for the lobby", { cls: "short", table: false })}${chartCard("c-gf", "Games that fit in the time", `${fmtMin(timeLeftMin())} left; format allows ${remCap}`, { cls: "short", table: false })}</div>` : ""}
  <div class="card"><div class="hd"><h2>Points per game by playstyle</h2><span class="sub">blue = enough to reach ${T == null ? "your target" : nf(T)} in the games that fit · outlined = typical finisher</span></div>${heat}</div>`;
  if (ds.length) {
    put("plan", mk($("#c-front"), {
      type: "scatter", data: { datasets: ds }, zoom: "xy", clickMode: "nearest", clickIntersect: true,
      click: hit => { const r = hit.element.$context && hit.element.$context.raw; if (r && r.x != null && r.y != null) setEx(r.y, r.x); },
      options: {
        interaction: { mode: "nearest", intersect: true },
        scales: { x: { type: "linear", min: 0, max: maxE, title: { text: "Average eliminations per game needed" } }, y: { type: "linear", reverse: true, min: 1, max: lobby, title: { text: "Average placement (1 = best)" }, ticks: { stepSize: 5 } } },
        plugins: { tooltip: { callbacks: { title: () => "", label: c => c.raw.pts != null ? `A finisher: place ${nd(c.raw.y)}, ${nd(c.raw.x)} elims, ${nd(c.raw.pts)} pts/game` : `${c.dataset.label}: place ${nd(c.raw.y)} with ${nd(c.raw.x)}${c.raw.over ? "+" : ""} elims; about ${c.raw.games} games fit, so ${nd(c.raw.ppg)} points a game` } } },
      }
    }));
    $("#c-front-tbl").innerHTML = table(["Average placement", "Games that fit", ...lines.map(l => confLabel(l.conf) + " (elims)")], [1, 3, 5, 8, 10, 15, 20, 25].filter(p => p <= lobby).map(p => [p, gamesFit(p, remCap), ...lines.map(l => { const d = l.data.find(x => x.y === p); return d ? nd(d.x) + (d.over ? "+" : "") : "not possible"; })]), ["n", "n", ...lines.map(() => "n")]);
    $("#c-front-take").innerHTML = take("", "For every average placement, the line shows the <b>eliminations per game you would need</b>. It bends because surviving longer costs minutes: you play fewer games, so each one has to score more. Dots are real players who finished near your rank.");
  }
  // playstyle explorer: sliders move a marker on the chart and price that style in points, games and chance
  const updEx = () => {
    if (!$("#ex-p")) return;
    const p = +$("#ex-p").value, e = +$("#ex-e").value; SS.ex = { p, e };
    const G = gamesFit(p, remCap), g = ptsAtPlace(sc, p) + ptsAtElims(sc, e), total = SS.pts + g * G, gm = gMin(p);
    let chance = "", cls = "";
    if (T != null) {
      if (!SS.aim && !s.final && s.mu != null) { const c = phi((Math.log1p(total) - s.mu) / s.sd); chance = pc(c); cls = c >= 0.8 ? "good" : c < 0.3 ? "bad" : ""; }
      else { chance = total >= T ? "Yes" : "No"; cls = total >= T ? "good" : "bad"; }
    }
    $("#ex-pv").textContent = p === 1 ? "win every game" : "top " + nd(p, 1); $("#ex-ev").textContent = nd(e, 2);
    $("#ex-out").innerHTML = kpi("Points per game", nd(g), `${nd(ptsAtPlace(sc, p))} placement + ${nd(ptsAtElims(sc, e))} elims`) + kpi("Games that fit", G + " <small>of " + remCap + "</small>", gm ? `about ${Math.round(gm)} min each` : "") + kpi("Expected total", nf(total), T == null ? "" : (total >= T ? "+" : "-") + nf(Math.abs(total - T)) + " vs " + nf(T), "hero") + kpi(!SS.aim && !s.final ? `Chance of top ${nf(SS.rank)}` : "Reaches the target", chance || "-", "", cls);
    const ch = Chart.getChart($("#c-front")), d = ch && ch.data.datasets.find(x => x.label === "Your playstyle");
    if (d) { d.data = [{ x: e, y: p }]; ch.update("none"); }
  };
  window.setEx = (p, e) => { if (!$("#ex-p")) return; $("#ex-p").value = clamp(Math.round(p * 2) / 2, 1, lobby); $("#ex-e").value = clamp(Math.round(e * 4) / 4, 0, maxE); updEx(); };
  if ($("#ex-p")) { $("#ex-p").value = ex0.p; $("#ex-e").value = ex0.e; $("#ex-p").oninput = updEx; $("#ex-e").oninput = updEx; updEx(); }
  $$("[data-hp]").forEach(c => c.onclick = () => { setEx(+c.dataset.hp, +c.dataset.he); $("#explore").scrollIntoView({ behavior: "smooth", block: "center" }); });
  if (tp && $("#c-tm")) {
    const lb = Array.from({ length: Math.min(tp.lobby, 45) }, (_, i) => i + 1);
    put("plan", mk($("#c-tm"), { type: "line", data: { labels: lb, datasets: [{ label: "Minutes per game", data: lb.map(p => tp.by_place[p - 1]), borderColor: SER(0), backgroundColor: withAlpha(SER(0), .14), fill: true, pointRadius: 0 }] }, options: { scales: { x: { title: { text: "Finishing placement" }, ticks: { maxTicksLimit: 10 } }, y: { beginAtZero: true, title: { text: "Minutes" } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => "Place " + c[0].label, label: c => nd(c.parsed.y) + " min per game" } } } } }));
    put("plan", mk($("#c-gf"), { type: "line", data: { labels: lb, datasets: [{ label: "Games that fit", data: lb.map(p => gamesFit(p, remCap)), borderColor: SER(1), backgroundColor: SER(1), stepped: true, pointRadius: 0, borderWidth: 3 }] }, options: { scales: { x: { title: { text: "Average placement" }, ticks: { maxTicksLimit: 10 } }, y: { beginAtZero: true, suggestedMax: remCap + 1, ticks: { stepSize: 1 }, title: { text: "Games" } } }, plugins: { legend: { display: false }, refLines: { lines: [{ axis: "y", value: remCap, label: "format: " + remCap, color: cssv("--tx2"), right: true }] }, tooltip: { callbacks: { title: c => "Average place " + c[0].label, label: c => c.parsed.y + " games fit" } } } } }));
  }
}

// ---------------------------------------------------------------- 2 scoring
function renderScoring() {
  const el = $("#p-scoring"); if (!el) return; drop("scoring");
  const sc = SS.d.scoring;
  if (!sc || sc.error) { el.innerHTML = `<div class="card empty">${esc(sc ? sc.error : "")}</div>`; return; }
  const win = sc.placement[0] + sc.win_bonus, t = n => sc.placement[n - 1] ?? 0;
  const be = n => sc.breakeven.find(b => b.placement === n);
  const elimNote = sc.per_elim && sc.elim_capped ? `Elims score up to ${sc.elim_cap} per game.` : "";
  el.innerHTML = `<div class="kpis">${kpi("Win", nf(win), sc.per_elim ? "= " + nd(win / sc.per_elim) + " elims" : "")}${kpi("Top 5", nf(t(5)), sc.per_elim ? "= " + nd(t(5) / sc.per_elim) + " elims" : "")}${kpi("Top 10", nf(t(10)), sc.per_elim ? "= " + nd(t(10) / sc.per_elim) + " elims" : "")}${kpi("Each elim", sc.per_elim ? "+" + nd(sc.per_elim, sc.per_elim % 1 ? 1 : 0) : "0", elimNote || "no cap")}${kpi("Last scoring place", "#" + sc.last_paid_place, nf(t(sc.last_paid_place)) + " pts")}</div>
  <div class="grid g2">${chartCard("c-place", "Points by placement", "Per game, before eliminations", { cls: "" })}${chartCard("c-mix", "A game's points: placement + eliminations", "Lines for four finishes", {})}</div>`;
  const last = Math.min(sc.placement.length, 30);
  put("scoring", mk($("#c-place"), { type: "bar", data: { labels: sc.placement.slice(0, last).map((_, i) => i + 1), datasets: [{ label: "Points", data: sc.placement.slice(0, last), backgroundColor: SER(0) }] }, options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => "Placement #" + c[0].label } } }, scales: { x: { title: { text: "Placement" } }, y: { title: { text: "Points" }, beginAtZero: true } } } }));
  const marks = [1, 5, 10, 25].filter(p => p <= sc.placement.length), E = Array.from({ length: Math.min(sc.elim.length, 11) }, (_, i) => i);
  put("scoring", mk($("#c-mix"), { type: "line", data: { labels: E, datasets: marks.map((p, i) => ({ label: p === 1 ? "Win" : "Top " + p, data: E.map(e => ptsAtPlace(sc, p) + ptsAtElims(sc, e)), borderColor: SER(i), backgroundColor: SER(i), pointRadius: 3 })) }, options: { scales: { x: { title: { text: "Eliminations in the game" } }, y: { title: { text: "Points in the game" }, beginAtZero: true } }, plugins: { tooltip: { callbacks: { title: c => c[0].label + " elims" } } } } }));
  $("#c-place-tbl").innerHTML = table(["Placement", "Points"], sc.placement.slice(0, last).map((p, i) => ["#" + (i + 1), p]), ["", "n"]);
  $("#c-mix-tbl").innerHTML = table(["Finish", "Equals this many elims"], sc.breakeven.map(b => [b.placement === 1 ? "Win" : "Top " + b.placement, b.elims == null ? "-" : b.reachable ? nd(b.elims) : nd(b.elims) + " (more than the cap)"]), ["", "n"]);
  const top10 = be(10);
  $("#c-mix-take").innerHTML = sc.per_elim ? take("", `A top-10 finish is worth <b>${top10 ? nd(top10.elims) : "-"} eliminations</b>${be(1) && !be(1).reachable ? "; a win cannot be matched by elims alone because they stop scoring at " + sc.elim_cap : be(1) ? " and a win is worth " + nd(be(1).elims) : ""}. ${sc.elim_capped ? "Beyond " + sc.elim_cap + " elims in one game, extra kills add nothing." : ""}`) : "";
}

// ---------------------------------------------------------------- 3 finishers
function renderFin() {
  const el = $("#p-fin"); if (!el) return; drop("fin");
  const pr = SS.d.profile;
  if (!pr || pr.error) { el.innerHTML = `<div class="card empty">${esc(pr ? pr.error : "")}</div>`; return; }
  const f = pr.focus, bands = pr.bands;
  const lab = b => `#${b.from}–${b.to}`, all = [{ ...f, name: `Around #${pr.rank}` }, ...bands.map(b => ({ ...b, name: "Top " + lab(b) }))];
  el.innerHTML = `${pr.clamped ? `<p class="small">Per-game data only exists for the top 1,000, so this shows ranks around #${pr.rank}.</p>` : ""}
  <div class="kpis">${kpi("Around #" + pr.rank, nd(f.pts_per_game), "points per game", "hero")}${kpi("Avg placement", nd(f.avg_place), "top-10 in " + pc(f.top10_rate) + " of games")}${kpi("Elims / game", nd(f.elims_per_game), "elims are " + pc(f.split.elim) + " of points")}${kpi("Win rate", pc(f.win_rate, 1), "top 5 in " + pc(f.top5_rate))}${kpi("Consistency", "± " + nd(f.sd), "points spread per game")}</div>
  <p class="small" style="margin:-4px 0 14px">Source: ${esc(pr.note)} ${f.players} players, ${f.games} games. ${pr.own ? "" : "Scored with this event's rules."}</p>
  <div class="grid g2">${chartCard("c-split", "Where the points come from", "Average points per game, by rank band", {})}${chartCard("c-plc", "How they finish", "Share of games by placement", {})}</div>
  <div class="grid g2">${chartCard("c-eli", "How many elims", "Share of games by eliminations", {})}${chartCard("c-gm", `Points by game number around #${pr.rank}`, "Do finishers tire or warm up?", {})}</div>`;
  const stackOpt = { responsive: true, scales: { x: { stacked: true }, y: { stacked: true } }, elements: { bar: { borderWidth: 2, borderColor: cssv("--sf"), borderRadius: 4 } } };
  put("fin", mk($("#c-split"), { type: "bar", data: { labels: all.map(b => b.name), datasets: [["Placement", "place", 0], ["Eliminations", "elim", 1], ["Wins", "win", 2]].filter(d => d[1] !== "win" || all.some(b => b.split.win > 0.002)).map(([n, k, i]) => ({ label: n, data: all.map(b => +(b.pts_per_game * b.split[k]).toFixed(2)), backgroundColor: SER(i) })) }, options: { ...stackOpt, plugins: { tooltip: { callbacks: { footer: c => "Total " + nd(c.reduce((s, x) => s + x.parsed.y, 0)) + " pts/game" } } }, scales: { x: { stacked: true }, y: { stacked: true, title: { text: "Points per game" } } } } }));
  const ramp = RAMP(7), dist = (hist, labels, key) => labels.map((l, i) => ({ label: l, data: all.map(b => +(b[key][i] * 100).toFixed(1)), backgroundColor: ramp[i] }));
  const hOpt = t => ({ indexAxis: "y", interaction: { mode: "index", axis: "y", intersect: false }, scales: { x: { stacked: true, max: 100, title: { text: "% of games" } }, y: { stacked: true, grid: { display: false } } }, elements: { bar: { borderWidth: 1, borderColor: cssv("--sf"), borderRadius: 3 } }, plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.parsed.x.toFixed(1)}%` } } } });
  put("fin", mk($("#c-plc"), { type: "bar", data: { labels: all.map(b => b.name), datasets: dist(null, pr.place_buckets, "place_hist") }, options: hOpt() }));
  put("fin", mk($("#c-eli"), { type: "bar", data: { labels: all.map(b => b.name), datasets: dist(null, pr.elim_buckets, "elim_hist") }, options: hOpt() }));
  const bg = f.by_game || [];
  put("fin", mk($("#c-gm"), { type: "line", data: { labels: bg.map(g => g.game), datasets: [{ label: "Average points", data: bg.map(g => g.pts), borderColor: SER(0), backgroundColor: withAlpha(SER(0), .15), fill: true, pointRadius: 3 }] }, options: { plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => "Game " + c[0].label, footer: c => bg[c[0].dataIndex] ? bg[c[0].dataIndex].n + " players" : "" } } }, scales: { x: { title: { text: "Game number (by time)" } }, y: { title: { text: "Points" }, beginAtZero: true } } } }));
  const tr = x => x.map(b => [b.name, nd(b.pts_per_game), nd(b.avg_place), nd(b.elims_per_game), pc(b.win_rate, 1), pc(b.top10_rate), pc(b.split.elim)]);
  $("#c-split-tbl").innerHTML = table(["Band", "Pts/game", "Avg place", "Elims/game", "Win rate", "Top 10", "Elim share"], tr(all), ["", "n", "n", "n", "n", "n", "n"]);
  $("#c-plc-tbl").innerHTML = table(["Band", ...pr.place_buckets], all.map(b => [b.name, ...b.place_hist.map(v => pc(v))]), ["", ...pr.place_buckets.map(() => "n")]);
  $("#c-eli-tbl").innerHTML = table(["Band", ...pr.elim_buckets], all.map(b => [b.name, ...b.elim_hist.map(v => pc(v))]), ["", ...pr.elim_buckets.map(() => "n")]);
  $("#c-gm-tbl").innerHTML = table(["Game", "Avg points", "Players"], bg.map(g => [g.game, nd(g.pts), g.n]), ["n", "n", "n"]);
  const top = all[1], elo = bands[bands.length - 1];
  $("#c-split-take").innerHTML = take("", `Around #${pr.rank}, <b>${pc(f.split.elim)}</b> of points come from eliminations and <b>${pc(f.split.place)}</b> from placement${f.split.win > 0.002 ? `, ${pc(f.split.win)} from win bonuses` : ""}. The top ten average <b>${nd(top.pts_per_game)}</b> a game against <b>${nd(f.pts_per_game)}</b> here; the gap is ${nd(top.elims_per_game - f.elims_per_game)} more elims and ${nd(f.avg_place - top.avg_place)} places better per game.`);
  $("#c-plc-take").innerHTML = take("", `Players around #${pr.rank} finish top 10 in <b>${pc(f.top10_rate)}</b> of games and win <b>${pc(f.win_rate, 1)}</b>. Players at #${elo.from}–${elo.to} win ${pc(elo.win_rate, 1)}.`);
}

// ---------------------------------------------------------------- 4 pace
function renderPace() {
  const el = $("#p-pace"); if (!el) return; drop("pace");
  const p = SS.d.pace; if (!p) return;
  if (p.error) { el.innerHTML = `<div class="card empty">${esc(p.error)}</div>`; return; }
  const cap = p.cap, n = p.mid.length, T = aimPoints();
  const expAt = g => g <= 0 ? 0 : g <= n ? lerp([0, ...p.mid], g) : p.mid[n - 1] * g / n;
  const perGame = p.mid[n - 1] / n, played = SS.played, exp = expAt(played), diff = SS.pts - exp;
  const pf = projFinal(), projN = pf ? pf.games : cap, proj = pf ? pf.pts : null, timeCut = projN < cap ? ` (only about ${projN - played} more games fit in the time)` : "";
  const xs = Array.from({ length: n + 1 }, (_, i) => i);
  const dsr = (a) => xs.map(i => ({ x: i, y: i ? a[i - 1] : 0 }));
  const ds = [
    { label: "Slower quarter", data: dsr(p.lo), borderColor: withAlpha(SER(0), .35), borderWidth: 1, pointRadius: 0, fill: false, order: 4 },
    { label: "Middle half of finishers", data: dsr(p.hi), borderColor: withAlpha(SER(0), .35), borderWidth: 1, pointRadius: 0, backgroundColor: withAlpha(SER(0), .14), fill: "-1", order: 4 },
    { label: "Typical finisher", data: dsr(p.mid), borderColor: SER(0), backgroundColor: SER(0), borderWidth: 3, pointRadius: 0, order: 2 },
  ];
  if (played > 0) {
    ds.push({ label: "You so far", data: [{ x: 0, y: 0 }, { x: played, y: SS.pts }], borderColor: SER(1), backgroundColor: SER(1), borderWidth: 3, pointRadius: [0, 6], order: 1 });
    if (played < projN) ds.push({ label: "You at this rate", data: [{ x: played, y: SS.pts }, { x: projN, y: proj }], borderColor: SER(1), borderDash: [6, 5], borderWidth: 2, pointRadius: [0, 4], order: 1 });
  }
  const status = played <= 0 ? take("", `Fill in <b>Games I have played</b> and <b>My points so far</b> above to see where you stand. A typical finisher near #${p.rank} has <b>${nf(expAt(1))}</b> after one game and <b>${nf(p.final_est)}</b> at the end.`)
    : diff >= 0 ? take("good", `You are <b>${nf(diff)} points ahead</b> of a typical finisher near #${p.rank} after ${played} games (≈ ${nd(diff / perGame)} games' worth). At your rate you finish near <b>${nf(proj)}</b>${timeCut}${T ? ` against a target of ${nf(T)}` : ""}.`)
      : take(Math.abs(diff) > 1.5 * perGame ? "bad" : "warn", `You are <b>${nf(-diff)} points behind</b> a typical finisher near #${p.rank} after ${played} games (≈ ${nd(-diff / perGame)} games' worth). At your rate you finish near <b>${nf(proj)}</b>${timeCut}${T ? ` against a target of ${nf(T)}` : ""}.`);
  el.innerHTML = chartCard("c-pace", `Points after each game for finishers near #${p.rank}`, `${p.players} players · ranks ${p.band[0]}–${p.band[1]}${p.scaled ? " · scaled to the predicted cutoff" : ""}`, { cls: "tall", zoom: true });
  put("pace", mk($("#c-pace"), { type: "line", zoom: "x", data: { datasets: ds }, options: { interaction: { mode: "nearest", axis: "x", intersect: false }, scales: { x: { type: "linear", min: 0, max: cap, ticks: { stepSize: 1 }, title: { text: "Games played" } }, y: { beginAtZero: true, title: { text: "Total points" } } }, plugins: { legend: { labels: { filter: i => i.text !== "Slower quarter" } }, tooltip: { callbacks: { title: c => "After game " + c[0].parsed.x, label: c => `${c.dataset.label}: ${nf(c.parsed.y)}` } }, refLines: { lines: T ? [{ axis: "y", value: T, label: "Aim: " + nf(T), color: cssv("--tx"), right: true }] : [] } } } }));
  $("#c-pace-tbl").innerHTML = table(["After game", "Slower quarter", "Typical", "Faster quarter"], p.mid.map((m, i) => [i + 1, nf(p.lo[i]), nf(m), nf(p.hi[i])]), ["n", "n", "n", "n"]);
  $("#c-pace-take").innerHTML = status + (n < cap ? `<p class="small">Per-game history is stored for ${n} of ${cap} games; the end value is extended in a straight line.</p>` : "");
}

// ---------------------------------------------------------------- 5 safety
function renderSafe() {
  const el = $("#p-safe"); if (!el) return; drop("safe");
  const s = SS.d.safety; if (!s) return;
  if (s.error) { el.innerHTML = `<div class="card empty">${esc(s.error)}</div>`; return; }
  if (s.final) { el.innerHTML = `<div class="card"><p>This event has finished. The final cutoff for top ${nf(s.rank)} was <b>${nf(s.likely)}</b> points.</p></div>`; return; }
  const L = s.ladder, g = c => L.find(x => x.conf === c).points, d = s.drift;
  const dl = (v, h) => v == null ? "-" : (v >= 0 ? "+" : "") + nf(v);
  el.innerHTML = `<div class="kpis">${L.map(l => kpi(Math.round(l.conf * 100) + "% sure", nf(l.points), l.conf === SS.conf ? "your choice" : "+" + nf(l.points - g(0.5)) + " vs likely", l.conf === SS.conf ? "hero" : "")).join("")}</div>
  <div class="grid g3" style="margin-bottom:16px">${kpi("Cutoff right now", s.current ? nf(s.current) : "not started", "top " + nf(s.rank) + (s.current ? " today" : ""))}${kpi("Model uncertainty", "± " + nd(s.sd_pct) + "%", s.history_events ? "based on " + s.history_events + " past events" : "")}${kpi("Moved recently", d ? dl(d.h1) + " / hour" : "-", d ? dl(d.h3) + " in 3h · " + dl(d.h6) + " in 6h" : "needs a few snapshots")}</div>
  ${chartCard("c-safe", `Chance that a score is enough for top ${nf(s.rank)}`, `predicted ${nf(s.low)} – ${nf(s.safe)}`, { cls: "", zoom: true })}`;
  const refs = [{ axis: "x", value: g(0.5), label: "50%", color: cssv("--tx2"), row: 0 }, { axis: "x", value: g(0.8), label: "80%", color: cssv("--tx2"), row: 1 }, { axis: "x", value: g(0.95), label: "95%", color: cssv("--tx2"), row: 2 }];
  if (s.current) refs.push({ axis: "x", value: s.current, label: "now " + nf(s.current), color: SER(1), row: 3 });
  const pf = projFinal(); if (pf) refs.push({ axis: "x", value: pf.pts, label: "you ≈ " + nf(pf.pts), color: SER(2), row: 4 });
  put("safe", mk($("#c-safe"), { type: "line", zoom: "x", click: hit => { const x = Math.round(hit.element.$context.parsed.x); if (x > 0) { SS.aim = x; $("#saim").value = x; saveSS(); renderPersonal(); } }, data: { datasets: [{ label: "Chance the cutoff is at or below this score", data: s.curve.map(c => ({ x: c[0], y: c[1] * 100 })), borderColor: SER(0), backgroundColor: withAlpha(SER(0), .14), fill: true, pointRadius: 0 }] }, options: { scales: { x: { type: "linear", title: { text: "Your final points" }, min: s.curve[0][0], max: s.curve[s.curve.length - 1][0] }, y: { min: 0, max: 100, title: { text: "Chance it is enough (%)" }, ticks: { callback: v => v + "%" } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => nf(c[0].parsed.x) + " points", label: c => `${c.parsed.y.toFixed(0)}% chance this is enough` } }, refLines: { lines: refs } } } }));
  $("#c-safe-tbl").innerHTML = table(["Certainty", "Points"], L.map(l => [Math.round(l.conf * 100) + "%", nf(l.points)]), ["", "n"]);
  const extra = g(0.95) - g(0.5);
  $("#c-safe-take").innerHTML = take("", `Going from a coin flip (<b>${nf(g(0.5))}</b>) to <b>95% sure</b> (<b>${nf(g(0.95))}</b>) costs <b>${nf(extra)} more points</b> (${pc(extra / g(0.5), 1)}). ${SS.pts && SS.played ? "" : "Enter your progress above to see where you land on this curve."} <b>Click the curve</b> to use that score as your aim.`);
}

// ---------------------------------------------------------------- 6 keep playing?
// Monte Carlo over the games you still have. Four things are simulated together:
//  1. how well you play (a real finisher's games, or your own pace blended with finishers),
//  2. luck from game to game (games are drawn at random from real results),
//  3. how long each game takes (from where it ended: deep runs last ~17 min, early deaths far less), which
//     decides how many games fit before the window closes,
//  4. where the final cutoff lands (drawn from the model's predicted distribution).
const PRIOR_GAMES = 8;   // how many games of "finisher form" a blend counts before your own results outweigh it
const gauss = r => { let u = 0; while (!u) u = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r()); };
const pct1 = v => v < 10 ? nd(v, 1) : nd(v, 0);
const meanOf = a => a.reduce((s, x) => s + x, 0) / (a.length || 1);
// o.pooled / o.players hold [points, placement] pairs; o.budget is the minutes left (Infinity = ignore time)
function simStop(o) {
  const R = rng(o.seed), S = o.sims, K = o.rem, totals = Array.from({ length: K + 1 }, () => new Float32Array(S)), cuts = new Float32Array(S), done = new Uint8Array(S);
  const pm = meanOf(o.pooled.map(x => x[0])) || 1;
  for (let i = 0; i < S; i++) {
    cuts[i] = o.cut.fixed != null ? o.cut.fixed : Math.expm1(o.cut.mu + o.cut.sd * gauss(R));
    let draw, t = 0, tot = o.pts, g = 0; totals[0][i] = tot;
    if (o.mode !== "band" && o.own && o.own.games && o.own.games.length) {   // your real games, shrunk toward finisher form while you have few
      const og = o.own.games, w = og.length / (og.length + (o.mode === "own" ? 0 : PRIOR_GAMES));
      draw = () => (R() < w ? og[(R() * og.length) | 0] : o.pooled[(R() * o.pooled.length) | 0]);
    }
    else if (o.mode === "band" && o.players.length) { const pl = o.players[(R() * o.players.length) | 0]; draw = () => pl[(R() * pl.length) | 0]; }
    else {
      const n = o.own ? o.own.n : 1, k = o.mode === "own" ? 0 : PRIOR_GAMES, post = (n * (o.own ? o.own.mean : pm) + k * pm) / (n + k), se = o.sd / Math.sqrt(n + k);
      const sc = Math.max(0.15, post + se * gauss(R)) / pm;
      draw = () => { const x = o.pooled[(R() * o.pooled.length) | 0]; return [Math.round(x[0] * sc), x[1]]; };
    }
    for (let k = 1; k <= K; k++) {
      if (t < o.budget) { const x = draw(); tot += x[0]; t += o.gmin ? o.gmin(x[1]) : 0; g++; }   // a game can start while any time is left
      totals[k][i] = tot;
    }
    done[i] = g;
  }
  const P = totals.map(a => { let c = 0; for (let i = 0; i < S; i++) if (a[i] >= cuts[i]) c++; return c / S * 100; });
  const Q = totals.map(a => { const b = Float32Array.from(a).sort(); return [b[Math.floor(S * .1)], b[Math.floor(S * .5)], b[Math.floor(S * .9)]]; });
  const hist = new Array(K + 1).fill(0); done.forEach(g => hist[g]++);
  const d = Array.from(done).sort((a, b) => a - b);
  return { P, Q, hist: hist.map(v => v / S * 100), games: [d[Math.floor(S * .1)], d[Math.floor(S * .5)], d[Math.floor(S * .9)]], most: Math.max(...d) };
}
function renderStop() {
  const el = $("#p-stop"); if (!el) return; drop("stop");
  const pr = SS.d.profile, s = SS.d.safety;
  if (!pr || pr.error || !s) { el.innerHTML = `<div class="card empty">${esc(pr && pr.error || "Waiting for data…")}</div>`; return; }
  if (s.error && !SS.aim) { el.innerHTML = `<div class="card empty">${esc(s.error)}</div>`; return; }
  const mine = SS.me && SS.me.found ? SS.me.games.filter(g => g.points != null).map(g => [g.points, g.placement]) : null;
  const own = SS.played > 0 ? { n: SS.played, mean: SS.pts / SS.played, games: mine && mine.length === SS.played ? mine : null } : null;
  const bands = [{ key: "focus", name: `Players around #${pr.rank}`, b: pr.focus }, ...pr.bands.map(b => ({ key: b.from + "-" + b.to, name: `Top #${b.from}–${b.to}`, b }))];
  const opts = [...(own ? [{ key: "blend", name: `${own.games ? "My real games" : "My pace"} blended with finishers (${nd(own.mean)} pts/game so far)`, mode: "blend" }, { key: "own", name: `Only ${own.games ? "my real games" : "my pace"} so far (${nd(own.mean)} pts/game)`, mode: "own" }] : []), ...bands.map(x => ({ ...x, mode: "band", name: x.name + ` (${nd(x.b.pts_per_game)} pts/game)` }))];
  const def = own && own.n >= 3 ? "blend" : "focus";
  const sel = opts.find(x => x.key === SS.like) || opts.find(x => x.key === def) || opts[0];
  const base = bands.find(x => x.key === "focus").b;                        // the form of finishers near the target
  const pooledFrom = sel.mode === "band" ? sel.b : base;
  const cap = capOf(), left = Math.max(0, cap - SS.played), tp = SS.d.tempo && !SS.d.tempo.error ? SS.d.tempo : null;
  const budget = tp ? timeLeftMin() : Infinity;
  const fixed = SS.aim || (s.final ? s.likely : null);
  const T = aimPoints(), goalName = SS.aim ? `your aim of ${nf(SS.aim)}` : `a top ${nf(SS.rank)} finish`;
  const sim = simStop({ pts: SS.pts, rem: left, mode: sel.mode, players: pooledFrom.players_pts || [], pooled: pooledFrom.sample, own, sd: base.sd || 20, cut: fixed != null ? { fixed } : { mu: s.mu, sd: s.sd }, budget, gmin: tp ? (p => gMin(p)) : null, seed: Math.round(SS.rank * 7 + SS.pts * 3 + SS.played * 13), sims: 6000 });
  const rem = sim.most, P = sim.P.slice(0, rem + 1), Q = sim.Q.slice(0, rem + 1), p0 = P[0], pAll = P[rem], p1 = rem ? P[1] : p0, marg = P.map((v, k) => k ? v - P[k - 1] : 0);
  const sure = P.findIndex(v => v >= 95), dim = marg.findIndex((v, k) => k > 0 && v < 1.5), med = sim.games[1];
  const timeLimited = tp && left > 0 && med < left;
  let cls, head, body;
  if (left === 0 || rem === 0) { cls = "hard"; head = left === 0 ? "No games left" : "No time for another game"; body = `Your ${nf(SS.pts)} points give about a <b>${pct1(p0)}%</b> chance of ${goalName}.`; }
  else if (p0 >= 97) { cls = "stop"; head = "You are very likely already in"; body = `Even with no more games you have about <b>${nd(p0, 0)}%</b> to make ${goalName}. More games only protect against a late jump in the cutoff.`; }
  else if (pAll < 3) { cls = "hard"; head = `Very unlikely: ${pct1(pAll)}%`; body = `In the time you have (about ${med} more game${med === 1 ? "" : "s"}), your median finish is <b>${nf(Q[rem][1])}</b> points, and ${goalName} needs roughly ${nf(T)}. It would take an unusually strong run.`; }
  else if (sure > 0) { cls = "go"; head = `Play ${sure} more game${sure > 1 ? "s" : ""} to be 95% sure`; body = `Your chance of ${goalName} rises from <b>${pct1(p0)}%</b> now to <b>${nd(P[sure], 0)}%</b> after ${sure} more.${sure < rem ? ` After that, each extra game adds ${nd(marg[sure + 1])}% or less.` : ""}`; }
  else if (dim > 1 && dim < rem) { cls = "go"; head = `Strong gains up to game ${dim - 1}, then it flattens`; body = `Your chance climbs from ${nd(p0, 0)}% to <b>${nd(P[dim - 1], 0)}%</b> over the next ${dim - 1} game${dim - 1 === 1 ? "" : "s"}; games after that add under 1.5% each. All ${rem}: <b>${nd(pAll, 0)}%</b>.`; }
  else { cls = "go"; head = `Keep playing: ${nd(pAll, 0)}% with about ${rem} game${rem > 1 ? "s" : ""} left`; body = p1 - p0 < 2 && rem > 1 ? `One game alone adds little (${pct1(p0)}% to ${pct1(p1)}%): the chance builds over the whole set of about ${rem}. Points never go down, so playing on only costs time.` : `The next game lifts your chance from <b>${pct1(p0)}%</b> to <b>${pct1(p1)}%</b>. Points never go down, so playing on only costs time.`; }
  const finalMed = Q[rem][1];
  el.innerHTML = `<div class="ctrl"><label style="margin:0">Play like</label><select id="slike" style="width:auto;max-width:100%;margin:0">${opts.map(x => `<option value="${x.key}" ${x.key === sel.key ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div>
  <div class="verdict ${cls}"><div><div class="big">${head}</div><div>${body}</div></div></div>
  ${timeLimited ? take("warn", `<b>Time, not the format, is your limit.</b> The format allows ${left} more game${left === 1 ? "" : "s"}, but with ${Math.round(budget)} minutes left and games lasting as long as you survive, you will finish about <b>${med}</b> (80% of runs: ${sim.games[0]} to ${sim.games[2]}).`) : ""}
  <div class="kpis" style="margin-top:12px">${kpi("Chance with 0 more games", pct1(p0) + "%", nf(SS.pts) + " points now")}${kpi("Chance with all you can play", nd(pAll, 0) + "%", "of " + goalName, "hero")}${kpi("Games you will finish", med, `80% of runs: ${sim.games[0]} to ${sim.games[2]}${tp ? "" : " (no timing data)"}`, timeLimited ? "bad" : "")}${kpi("Likely final points", nf(finalMed), "range " + nf(Q[rem][0]) + " – " + nf(Q[rem][2]))}${kpi("Cutoff aimed at", nf(T), fixed != null ? "fixed" : "varies ± " + nd(s.sd_pct) + "%")}</div>
  <div class="card"><div class="hd"><h2>What if I play…</h2><span class="sub">drag to see your chance after that many more games</span></div>
    <div class="explore"><div><label>Extra games <span class="rv" id="sk-v"></span></label><input id="sk" type="range" min="0" max="${rem}" step="1"></div><div class="kpis" id="sk-out" style="margin:0"></div></div></div>
  ${chartCard("c-stop", `Chance of ${goalName}, by extra games played`, "6,000 simulated runs · click a point to set the slider", {})}
  <div class="grid g3">${chartCard("c-stop2", "What each extra game adds", "percentage points of chance", { cls: "short", table: false })}${chartCard("c-stop3", "Where your points could end up", "middle 80% of runs", { cls: "short", table: false })}${chartCard("c-stop4", "How many games you get in", "share of runs", { cls: "short", table: false })}</div>`;
  const xs = Array.from({ length: rem + 1 }, (_, k) => k);
  put("stop", mk($("#c-stop"), { type: "line", click: hit => { $("#sk").value = hit.index; updK(); }, data: { labels: xs, datasets: [{ label: "Chance", data: P, borderColor: SER(0), backgroundColor: withAlpha(SER(0), .14), fill: true, pointRadius: 3, borderWidth: 3 }] }, options: { scales: { x: { title: { text: "Extra games played" } }, y: { min: 0, max: 100, title: { text: "Chance (%)" }, ticks: { callback: v => v + "%" } } }, plugins: { legend: { display: false }, refLines: { lines: [{ axis: "y", value: 95, label: "95% sure", right: true }] }, tooltip: { callbacks: { title: c => c[0].label + " more games", label: c => `${c.parsed.y.toFixed(0)}% chance` } } } } }));
  const updK = () => {
    const k = clamp(+$("#sk").value, 0, rem); SS.sk = k; $("#sk-v").textContent = k;
    $("#sk-out").innerHTML = kpi("Chance", pct1(P[k]) + "%", k ? (P[k] - P[0] >= 0 ? "+" : "") + nd(P[k] - P[0]) + " vs now" : "no more games", "hero") + kpi("Likely total", nf(Q[k][1]), nf(Q[k][0]) + " – " + nf(Q[k][2]));
    const ch = Chart.getChart($("#c-stop")); if (ch) { ch.options.plugins.refLines.lines = [{ axis: "y", value: 95, label: "95% sure", right: true }, { axis: "x", value: k, label: k + " more", color: SER(1) }]; ch.update("none"); }
  };
  $("#sk").value = clamp(SS.sk ?? rem, 0, rem); $("#sk").oninput = updK; updK();
  put("stop", mk($("#c-stop2"), { type: "bar", data: { labels: xs.slice(1), datasets: [{ label: "Added chance", data: marg.slice(1).map(v => +v.toFixed(1)), backgroundColor: marg.slice(1).map(v => v < 1.5 ? withAlpha(SER(0), .4) : SER(0)) }] }, options: { scales: { x: { title: { text: "Game" } }, y: { title: { text: "Percentage points" } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => "Game " + c[0].label, label: c => "+" + c.parsed.y + " points of chance" } } } } }));
  const cutLines = fixed != null ? [{ axis: "y", value: fixed, label: "cutoff " + nf(fixed), color: cssv("--tx"), right: true }] : [{ axis: "y", value: Math.round(Math.expm1(s.mu)), label: "likely cutoff " + nf(Math.expm1(s.mu)), color: cssv("--tx"), right: true }, { axis: "y", value: s.ladder.find(x => x.conf === 0.95).points, label: "95%: " + nf(s.ladder.find(x => x.conf === 0.95).points), color: cssv("--tx2"), right: true, dash: [2, 4] }];
  put("stop", mk($("#c-stop3"), { type: "line", data: { labels: xs, datasets: [{ label: "10%", data: Q.map(q => q[0]), borderColor: "transparent", pointRadius: 0, fill: false }, { label: "Middle 80% of runs", data: Q.map(q => q[2]), borderColor: "transparent", backgroundColor: withAlpha(SER(0), .2), pointRadius: 0, fill: "-1" }, { label: "Median", data: Q.map(q => q[1]), borderColor: SER(0), backgroundColor: SER(0), borderWidth: 3, pointRadius: 2 }] }, options: { scales: { x: { title: { text: "Extra games played" } }, y: { title: { text: "Your total points" } } }, plugins: { legend: { labels: { filter: i => i.text !== "10%" } }, refLines: { lines: cutLines }, tooltip: { callbacks: { title: c => c[0].label + " more games", label: c => `${c.dataset.label === "Middle 80% of runs" ? "90th percentile" : c.dataset.label === "10%" ? "10th percentile" : c.dataset.label}: ${nf(c.parsed.y)}` } } } } }));
  put("stop", mk($("#c-stop4"), { type: "bar", data: { labels: xs, datasets: [{ label: "Share of runs", data: sim.hist.slice(0, rem + 1).map(v => +v.toFixed(1)), backgroundColor: SER(1) }] }, options: { scales: { x: { title: { text: "Games finished" } }, y: { title: { text: "% of runs" }, ticks: { callback: v => v + "%" } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => c[0].label + " games", label: c => c.parsed.y + "% of runs" } } } } }));
  $("#c-stop-tbl").innerHTML = table(["Extra games", "Chance", "Adds", "10%", "Median", "90%"], xs.map(k => [k, nd(P[k], 0) + "%", k ? "+" + nd(marg[k]) : "", nf(Q[k][0]), nf(Q[k][1]), nf(Q[k][2])]), ["n", "n", "n", "n", "n", "n"]);
  $("#c-stop-take").innerHTML = take("", `Each run picks how well you play, plays games from real results (each one lasting as long as that finish really takes), stops when the window closes, and compares your total with a cutoff drawn from the prediction${fixed != null ? "" : ` (±${nd(s.sd_pct)}%)`}. ${sel.mode === "band" ? "Players are real finishers from the selected group, so it includes strong and weak runs." : sel.mode === "blend" ? `Your ${own.n} games count against ${PRIOR_GAMES} games of finisher form, so a short hot or cold start does not dominate.` : "Only your own games so far set your pace, so a short start can mislead."} It assumes you start the next game right away.`);
  $("#slike").onchange = e => { SS.like = e.target.value; saveSS(); renderStop(); };
}

// ---------------------------------------------------------------- 5 your games (read by Epic name from the public leaderboard)
async function loadMe(quiet) {
  const msg = $("#smemsg"), mine = ++SS.metok || (SS.metok = 1);
  if (!SS.name) { if (msg) msg.textContent = "Type your Epic name first."; return; }
  if (msg && !quiet) msg.innerHTML = '<span class="mut">Looking you up on the leaderboard… this can take up to 20 seconds.</span>';
  let d;
  try { d = await j(`/api/me?window=${encodeURIComponent(SS.w.window_id)}&name=${encodeURIComponent(SS.name)}`); } catch (e) { d = { error: "Could not reach the site." }; }
  if (SS.metok !== mine || !$("#sme")) return;
  if (d.error) { if (msg) msg.innerHTML = `<span class="err">${esc(d.error)}</span>`; return; }
  SS.me = d;
  if (d.found) {
    SS.played = d.games_played; SS.pts = Math.round(d.points); $("#spl").value = SS.played; $("#spt").value = SS.pts; saveSS();
    if (msg) msg.innerHTML = `<span class="ok">Found ${esc(d.name)}: rank #${nf(d.rank)}, ${nf(d.points)} points, ${d.games_played} games. Read ${hm(d.updated)}.</span>`;
  } else if (msg) msg.innerHTML = `<span class="mut">${esc(d.message || "Not found.")}</span>`;
  renderPersonal();
}
function renderMe() {
  const el = $("#p-me"); if (!el) return; drop("me");
  const m = SS.me;
  if (!m) return;
  if (!m.found) { el.innerHTML = `<div class="card empty">${esc(m.message || "Not found.")}<br><small>You can still type your games played and points in the bar above.</small></div>`; return; }
  const pr = SS.d.profile, f = pr && !pr.error ? pr.focus : null, T = aimPoints();
  const rem = Math.max(0, capOf() - m.games_played), Gt = gamesFit(typicalPlace(), rem), need = T == null ? null : Math.max(0, T - m.points), ppg = need == null ? null : Gt ? need / Gt : null;
  const gs = m.games, minutes = gs.map(g => g.gap_min).filter(x => x != null), avgMin = minutes.length ? minutes.reduce((a, b) => a + b, 0) / minutes.length : null;
  const mismatch = m.rules_total != null && Math.abs(m.rules_total - m.points) > 1;
  el.innerHTML = `<div class="kpis">${kpi("Rank right now", "#" + nf(m.rank), m.team && m.team.length ? "with " + esc(m.team.join(", ")) : esc(m.name), "hero")}${kpi("Points", nf(m.points), nd(m.pts_per_game) + " per game" + (f ? " · finishers " + nd(f.pts_per_game) : ""))}${kpi("Games played", m.games_played, rem + " left in the format")}${kpi("Avg placement", nd(m.avg_place), f ? "finishers " + nd(f.avg_place) : "")}${kpi("Elims per game", nd(m.elims_per_game), f ? "finishers " + nd(f.elims_per_game) : "")}${kpi("Wins", m.wins, avgMin ? "about " + Math.round(avgMin) + " min between games" : "")}</div>
  <div class="grid g2">${chartCard("c-me", "Points in each of your games", ppg ? "dashed line: what you need from here, per game" : "", { cls: "short", table: false })}${chartCard("c-me2", "Where you finished", "1 is a win", { cls: "short", table: false })}</div>
  <div id="me-take"></div>
  <div class="card" style="margin-top:16px"><div class="hd"><h2>Game by game</h2><span class="sub">read ${hm(m.updated)} from the leaderboard${mismatch ? " · points do not add up exactly to this event's scoring, so per-game points are approximate" : ""}</span></div>${table(["Game", "Finished", "Elims", "Points", "Ended", "Minutes since previous"], gs.map(g => [g.n, g.win ? "🏆 win" : "#" + g.placement, g.elims, g.points == null ? "-" : g.points, g.end ? hm(g.end) : "-", g.gap_min == null ? "-" : nd(g.gap_min)]), ["n", "", "n", "n", "n", "n"])}</div>`;
  const lab = gs.map(g => g.n), ref = [];
  if (ppg) ref.push({ axis: "y", value: ppg, label: "need " + nd(ppg) + " / game", color: cssv("--tx"), right: true });
  if (f) ref.push({ axis: "y", value: f.pts_per_game, label: "finishers " + nd(f.pts_per_game), color: cssv("--tx2"), right: true, dash: [2, 4] });
  put("me", mk($("#c-me"), { type: "bar", data: { labels: lab, datasets: [{ label: "Points", data: gs.map(g => g.points), backgroundColor: SER(0) }] }, options: { scales: { x: { title: { text: "Game" } }, y: { beginAtZero: true, title: { text: "Points" } } }, plugins: { legend: { display: false }, refLines: { lines: ref }, tooltip: { callbacks: { title: c => "Game " + c[0].label, label: c => `${c.parsed.y} points · finished #${gs[c.dataIndex].placement}, ${gs[c.dataIndex].elims} elims` } } } } }));
  put("me", mk($("#c-me2"), { type: "line", data: { labels: lab, datasets: [{ label: "Placement", data: gs.map(g => g.placement), borderColor: SER(1), backgroundColor: SER(1), pointRadius: 4, borderWidth: 2.5 }] }, options: { scales: { x: { title: { text: "Game" } }, y: { reverse: true, min: 1, title: { text: "Placement (1 = best)" } } }, plugins: { legend: { display: false }, refLines: { lines: f ? [{ axis: "y", value: f.avg_place, label: "finishers " + nd(f.avg_place), color: cssv("--tx2"), right: true, dash: [2, 4] }] : [] }, tooltip: { callbacks: { title: c => "Game " + c[0].label, label: c => "Finished #" + c.parsed.y } } } } }));
  const better = f && m.pts_per_game >= f.pts_per_game;
  $("#me-take").innerHTML = f ? take(better ? "good" : "", `You are averaging <b>${nd(m.pts_per_game)}</b> points a game against <b>${nd(f.pts_per_game)}</b> for finishers around #${pr.rank}${ppg ? `, and you need <b>${nd(ppg)}</b> from here over about ${Gt} more games` : ""}. Your average finish is <b>${nd(m.avg_place)}</b> with <b>${nd(m.elims_per_game)}</b> elims a game (finishers: ${nd(f.avg_place)} and ${nd(f.elims_per_game)}). Plan, pace and the keep-playing simulation now use your real games.`) : "";
}
