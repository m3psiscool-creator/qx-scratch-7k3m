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
  SS = { w, rank: saved.rank || (w.goal ? w.goal.rank : 100), conf: saved.conf || 0.8, played: saved.played || 0, pts: saved.pts || 0, aim: saved.aim || 0, like: saved.like || "focus", d: {} };
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
    <div class="chips" style="margin-top:10px"><small>Quick pick:</small>${presets.map(p => `<button class="chip ${p === SS.rank ? "on" : ""}" data-sr="${p}">${w.goal && w.goal.rank === p ? "★ " : ""}Top ${p.toLocaleString()}</button>`).join("")}</div>
    <div class="anch"><a href="#s-plan" data-a="s-plan">1 Plan</a><a href="#s-scoring" data-a="s-scoring">2 Scoring</a><a href="#s-fin" data-a="s-fin">3 Finishers</a><a href="#s-pace" data-a="s-pace">4 Pace</a><a href="#s-safe" data-a="s-safe">5 Safety</a><a href="#s-stop" data-a="s-stop">6 Keep playing?</a></div>
  </div>
  ${sec(1, "s-plan", "Your plan", "How many points to aim for, and the ways to get there")}<div id="p-plan">${skel(2, 160)}</div>
  ${sec(2, "s-scoring", "What the scoring rewards", "Points per placement and per elimination in this event")}<div id="p-scoring">${skel(1, 160)}</div>
  ${sec(3, "s-fin", "What finishers actually did", "Per-game numbers of real players, from the closest finished event of this class")}<div id="p-fin">${skel(2, 200)}</div>
  ${sec(4, "s-pace", "Pace tracker", "Where you should be after each game")}<div id="p-pace">${skel(1, 260)}</div>
  ${sec(5, "s-safe", "Safety margin", "How much cushion each level of certainty costs")}<div id="p-safe">${skel(1, 260)}</div>
  ${sec(6, "s-stop", "Keep playing or stop?", "Your chance of reaching the cutoff as you play more games")}<div id="p-stop">${skel(1, 260)}</div>`;
  // controls
  const readPersonal = () => { SS.conf = +$("#sconf").value; SS.played = clamp(+$("#spl").value || 0, 0, 99); SS.pts = Math.max(0, +$("#spt").value || 0); SS.aim = Math.max(0, +$("#saim").value || 0); saveSS(); };
  const apply = async () => { const r = clamp(Math.round(+$("#sx").value || SS.rank), 1, 10000); const changed = r !== SS.rank; SS.rank = r; readPersonal(); $$("[data-sr]").forEach(b => b.classList.toggle("on", +b.dataset.sr === r)); if (changed) await loadRank(); else renderPersonal(); };
  $("#sgo").onclick = apply;
  ["sx", "sconf", "spl", "spt", "saim"].forEach(id => $("#" + id).addEventListener(id === "sconf" ? "change" : "change", apply));
  $$("[data-sr]").forEach(b => b.onclick = () => { $("#sx").value = b.dataset.sr; apply(); });
  $$(".anch a").forEach(a => a.onclick = e => { e.preventDefault(); $("#" + a.dataset.a).scrollIntoView({ behavior: "smooth" }); });
  // data that does not depend on the rank
  j("/api/scoring?window=" + encodeURIComponent(w.window_id)).then(s => { SS.d.scoring = s; renderScoring(); renderPersonal(); });
  await loadRank();
  if (open) every(120000, () => loadRank(true));
}

async function loadRank(quiet) {
  const w = SS.w, id = encodeURIComponent(w.window_id), r = SS.rank, mine = ++SS.tok || (SS.tok = 1);
  if (!quiet) ["plan", "fin", "pace", "safe", "stop"].forEach(k => { const e = $("#p-" + k); if (e && !SS.d.safety) e.innerHTML = skel(1, 200); });
  // each part draws as soon as its data arrives: the safety estimate is the slow one
  const pProf = j(`/api/profile?window=${id}&rank=${Math.min(r, 1000)}`).then(x => { if (SS.tok === mine) { SS.d.profile = x; renderFin(); renderPersonal(); } });
  const safe = await j(`/api/safety?window=${id}&rank=${r}`);
  if (SS.tok !== mine) return;
  SS.d.safety = safe; renderPersonal();
  const target = safe && !safe.error ? safe.likely : 0;
  const pace = r <= 1000 ? await j(`/api/pace?window=${id}&rank=${r}${target ? "&target=" + target : ""}`) : { error: "Pace curves need a rank inside the stored top 1,000." };
  await pProf;
  if (SS.tok !== mine) return;
  SS.d.pace = pace; renderPersonal();
}
function renderPersonal() { renderPlan(); renderPace(); renderSafe(); renderStop(); }

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

// ---------------------------------------------------------------- 1 plan
function renderPlan() {
  const el = $("#p-plan"); if (!el) return; drop("plan");
  const sc = SS.d.scoring, pr = SS.d.profile, s = SS.d.safety;
  if (!sc || !pr || !s) return;
  if (sc.error) { el.innerHTML = `<div class="card empty">${esc(sc.error)}</div>`; return; }
  const T = aimPoints(), cap = capOf(), rem = Math.max(0, cap - SS.played), need = T == null ? null : Math.max(0, T - SS.pts), ppg = need == null ? null : rem ? need / rem : (need > 0 ? Infinity : 0);
  const f = pr && !pr.error ? pr.focus : null;
  let head = "";
  if (s.error && !SS.aim) head = `<div class="card flat"><b>No cutoff estimate yet.</b> <span class="mut">${esc(s.error)}</span><br><small>Type a number in "Aim for" above to plan against your own target.</small></div>`;
  const diff = f && ppg != null && isFinite(ppg) ? ppg / f.pts_per_game : null;
  const verdict = diff == null ? "" : diff <= 0.85 ? take("good", `You need <b>${nd(ppg)} points a game</b>, below the <b>${nd(f.pts_per_game)}</b> that players around #${pr.rank} averaged. A steady, safe style is enough.`)
    : diff <= 1.1 ? take("", `You need <b>${nd(ppg)} points a game</b>, about what players around #${pr.rank} averaged (<b>${nd(f.pts_per_game)}</b>). Play like a typical finisher.`)
      : take("warn", `You need <b>${nd(ppg)} points a game</b>, <b>${Math.round((diff - 1) * 100)}% more</b> than players around #${pr.rank} averaged (${nd(f.pts_per_game)}). That takes a win or several deep runs with elims.`);
  const kp = `<div class="kpis">
    ${kpi("Points to aim for", T == null ? "-" : nf(T), SS.aim ? "your own target" : s.final ? "final cutoff" : confLabel(SS.conf).toLowerCase() + " · now " + nf(s.current), "hero")}
    ${kpi("Games left", rem + " <small>of " + cap + "</small>", SS.played ? SS.played + " played" : "none played yet")}
    ${kpi("Points still needed", need == null ? "-" : nf(need), SS.pts ? "you have " + nf(SS.pts) : "start of event")}
    ${kpi("Needed per game", ppg == null ? "-" : isFinite(ppg) ? nd(ppg) : "∞", f ? "finishers: " + nd(f.pts_per_game) : "")}
    ${kpi("Typical finisher", f ? "place " + nd(f.avg_place) : "-", f ? nd(f.elims_per_game) + " elims · wins " + pc(f.win_rate) : "")}</div>`;
  if (!sc.per_elim && sc.placement.length < 3) {
    el.innerHTML = head + kp + verdict + `<div class="card"><p>${sc.placement.length === 1 ? "Only a win scores in this event, so the plan is simply: win as many games as you can." : "Eliminations do not score here, so only placement matters."} ${esc(sc.text)}</p></div>`; return;
  }
  // frontier: average elims per game -> the average placement you must reach
  const maxE = Math.min(Math.max(sc.elim_cap || 8, 3), 12), xs = Array.from({ length: maxE * 4 + 1 }, (_, i) => i / 4);
  const line = (conf, i) => {
    const t = SS.aim && conf === SS.conf ? SS.aim : (s.ladder || []).find(x => x.conf === conf)?.points ?? (s.final ? s.likely : null);
    if (t == null) return null;
    const pg = rem ? Math.max(0, t - SS.pts) / rem : 0;
    return { conf, data: xs.map(e => { const p = placeForPts(sc, pg - ptsAtElims(sc, e)); return p == null ? { x: e, y: null } : { x: e, y: Math.min(p, sc.placement.length + 1) }; }) };
  };
  const lines = (SS.aim ? [line(SS.conf)] : [0.5, 0.8, 0.95].map(line)).filter(Boolean);
  const cols = [SER(2), SER(0), SER(3)];
  const ds = lines.map((l, i) => ({ type: "line", label: SS.aim ? "Your aim " + nf(SS.aim) : confLabel(l.conf), data: l.data, borderColor: cols[i], backgroundColor: cols[i], borderWidth: l.conf === SS.conf ? 3 : 1.6, borderDash: l.conf === SS.conf ? [] : [6, 4], pointRadius: 0, pointHoverRadius: 4, spanGaps: false, order: 1 }));
  if (f && pr.focus.scatter) ds.push({ type: "scatter", label: `Finishers around #${pr.rank}`, data: pr.focus.scatter.map(a => ({ x: a[1], y: a[0], pts: a[2] })), backgroundColor: withAlpha(cssv("--tx2"), .45), borderColor: "transparent", pointRadius: 3.5, pointHoverRadius: 6, order: 2 });
  const heatP = [1, 2, 3, 5, 7, 10, 15, 20, 25].filter(p => p <= sc.placement.length), heatE = [0, 1, 2, 3, 4, 5, 6, 8, 10].filter(e => e <= Math.max(3, sc.elim_cap || 10));
  const fp = f ? f.avg_place : null, fe = f ? f.elims_per_game : null;
  const near = (arr, v) => arr.reduce((b, x) => Math.abs(x - v) < Math.abs(b - v) ? x : b, arr[0]);
  const cell = (p, e) => ptsAtPlace(sc, p) + ptsAtElims(sc, e);
  const heat = `<div class="scroll"><div class="heat" style="grid-template-columns:90px repeat(${heatE.length},1fr)"><div class="h">Place ↓ · Elims →</div>${heatE.map(e => `<div class="h">${e}</div>`).join("")}` +
    heatP.map(p => `<div class="h" style="text-align:right;padding-right:8px">${p === 1 ? "1st (win)" : "top " + p}</div>` + heatE.map(e => {
      const v = cell(p, e), ok = ppg != null && v >= ppg, k = ppg ? clamp((v / ppg - 1) / 0.6, 0, 1) : 0, isF = f && p === near(heatP, fp) && e === near(heatE, fe);
      return `<div class="${ok ? "yes" : ""} ${isF ? "need" : ""}" style="${ok ? `background:color-mix(in srgb,var(--s1) ${Math.round(45 + k * 55)}%,var(--sf2))` : ""}" title="Average place ${p}, ${e} elims: ${nf(v)} points a game, ${nf(v * rem)} over ${rem} games">${nf(v)}</div>`;
    }).join("")).join("") + `</div></div>`;
  const recs = [1, 3, 6].filter(e => e <= Math.max(3, sc.elim_cap || 6)).map(e => {
    const p = ppg == null || !isFinite(ppg) ? null : placeForPts(sc, ppg - ptsAtElims(sc, e));
    const txt = ppg == null ? "-" : p == null ? "Not possible" : p > sc.placement.length ? "Any placement" : "Top " + Math.max(1, Math.round(p));
    return `<div class="recipe"><b>Average ${e} elim${e > 1 ? "s" : ""} a game</b><div class="big">${txt}</div><small>${p == null ? "even a win every game falls short" : "average finish needed"}</small></div>`;
  }).join("");
  el.innerHTML = head + kp + verdict + `
  <div class="grid g3" style="margin-top:16px">${recs}</div>
  ${chartCard("c-front", "Trade-off: elims against placement", "Reach any point above or on a line to hit that certainty", { cls: "tall" })}
  <div class="card"><div class="hd"><h2>Points per game by playstyle</h2><span class="sub">blue = enough to reach ${T == null ? "your target" : nf(T)} · outlined = typical finisher</span></div>${heat}</div>`;
  if (ds.length) {
    const c = put("plan", mk($("#c-front"), {
      type: "scatter", data: { datasets: ds },
      options: {
        interaction: { mode: "nearest", intersect: true },
        scales: { x: { type: "linear", min: 0, max: maxE, title: { text: "Average eliminations per game" } }, y: { type: "linear", reverse: true, min: 1, max: Math.min(sc.placement.length + 1, 30), title: { text: "Average placement (1 = best)" }, ticks: { stepSize: 5 } } },
        plugins: { tooltip: { callbacks: { title: () => "", label: c => c.raw.pts != null ? `A finisher: place ${nd(c.raw.y)}, ${nd(c.raw.x)} elims, ${nd(c.raw.pts)} pts/game` : `${c.dataset.label}: ${nd(c.raw.x)} elims → average place ${nd(c.raw.y)}` } } },
      }
    }));
    $("#c-front-tbl").innerHTML = table(["Elims / game", ...lines.map(l => confLabel(l.conf))], [0, 1, 2, 3, 4, 6, 8].filter(e => e <= maxE).map(e => [e, ...lines.map(l => { const p = l.data.find(d => d.x === e)?.y; return p == null ? "not possible" : p > sc.placement.length ? "any" : "place " + nd(p); })]), ["n", "n", "n", "n"]);
    $("#c-front-take").innerHTML = take("", "Each line shows the <b>average placement you must reach</b> for a given number of eliminations per game. Higher on the chart is better placement. Dots are real players who finished near your rank, so you can see which style they used. This treats an average game, so a single win-heavy run can beat it.");
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
  const mine = played > 0 ? SS.pts / played : null, proj = mine != null ? SS.pts + mine * (cap - played) : null;
  const xs = Array.from({ length: n + 1 }, (_, i) => i);
  const dsr = (a) => xs.map(i => ({ x: i, y: i ? a[i - 1] : 0 }));
  const ds = [
    { label: "Slower quarter", data: dsr(p.lo), borderColor: withAlpha(SER(0), .35), borderWidth: 1, pointRadius: 0, fill: false, order: 4 },
    { label: "Middle half of finishers", data: dsr(p.hi), borderColor: withAlpha(SER(0), .35), borderWidth: 1, pointRadius: 0, backgroundColor: withAlpha(SER(0), .14), fill: "-1", order: 4 },
    { label: "Typical finisher", data: dsr(p.mid), borderColor: SER(0), backgroundColor: SER(0), borderWidth: 3, pointRadius: 0, order: 2 },
  ];
  if (played > 0) {
    ds.push({ label: "You so far", data: [{ x: 0, y: 0 }, { x: played, y: SS.pts }], borderColor: SER(1), backgroundColor: SER(1), borderWidth: 3, pointRadius: [0, 6], order: 1 });
    if (played < cap) ds.push({ label: "You at this rate", data: [{ x: played, y: SS.pts }, { x: cap, y: proj }], borderColor: SER(1), borderDash: [6, 5], borderWidth: 2, pointRadius: [0, 4], order: 1 });
  }
  const status = played <= 0 ? take("", `Fill in <b>Games I have played</b> and <b>My points so far</b> above to see where you stand. A typical finisher near #${p.rank} has <b>${nf(expAt(1))}</b> after one game and <b>${nf(p.final_est)}</b> at the end.`)
    : diff >= 0 ? take("good", `You are <b>${nf(diff)} points ahead</b> of a typical finisher near #${p.rank} after ${played} games (≈ ${nd(diff / perGame)} games' worth). At your rate you finish near <b>${nf(proj)}</b>${T ? ` against a target of ${nf(T)}` : ""}.`)
      : take(Math.abs(diff) > 1.5 * perGame ? "bad" : "warn", `You are <b>${nf(-diff)} points behind</b> a typical finisher near #${p.rank} after ${played} games (≈ ${nd(-diff / perGame)} games' worth). At your rate you finish near <b>${nf(proj)}</b>${T ? ` against a target of ${nf(T)}` : ""}.`);
  el.innerHTML = chartCard("c-pace", `Points after each game for finishers near #${p.rank}`, `${p.players} players · ranks ${p.band[0]}–${p.band[1]}${p.scaled ? " · scaled to the predicted cutoff" : ""}`, { cls: "tall" });
  put("pace", mk($("#c-pace"), { type: "line", data: { datasets: ds }, options: { interaction: { mode: "nearest", axis: "x", intersect: false }, scales: { x: { type: "linear", min: 0, max: cap, ticks: { stepSize: 1 }, title: { text: "Games played" } }, y: { beginAtZero: true, title: { text: "Total points" } } }, plugins: { legend: { labels: { filter: i => i.text !== "Slower quarter" } }, tooltip: { callbacks: { title: c => "After game " + c[0].parsed.x, label: c => `${c.dataset.label}: ${nf(c.parsed.y)}` } }, refLines: { lines: T ? [{ axis: "y", value: T, label: "Aim: " + nf(T), color: cssv("--tx"), right: true }] : [] } } } }));
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
  ${chartCard("c-safe", `Chance that a score is enough for top ${nf(s.rank)}`, `predicted ${nf(s.low)} – ${nf(s.safe)}`, { cls: "" })}`;
  const refs = [{ axis: "x", value: g(0.5), label: "50%", color: cssv("--tx2"), row: 0 }, { axis: "x", value: g(0.8), label: "80%", color: cssv("--tx2"), row: 1 }, { axis: "x", value: g(0.95), label: "95%", color: cssv("--tx2"), row: 2 }];
  if (s.current) refs.push({ axis: "x", value: s.current, label: "now " + nf(s.current), color: SER(1), row: 3 });
  if (SS.pts && SS.played) { const cap = capOf(), pr = SS.pts + SS.pts / SS.played * (cap - SS.played); refs.push({ axis: "x", value: pr, label: "you ≈ " + nf(pr), color: SER(2), row: 4 }); }
  put("safe", mk($("#c-safe"), { type: "line", data: { datasets: [{ label: "Chance the cutoff is at or below this score", data: s.curve.map(c => ({ x: c[0], y: c[1] * 100 })), borderColor: SER(0), backgroundColor: withAlpha(SER(0), .14), fill: true, pointRadius: 0 }] }, options: { scales: { x: { type: "linear", title: { text: "Your final points" }, min: s.curve[0][0], max: s.curve[s.curve.length - 1][0] }, y: { min: 0, max: 100, title: { text: "Chance it is enough (%)" }, ticks: { callback: v => v + "%" } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: c => nf(c[0].parsed.x) + " points", label: c => `${c.parsed.y.toFixed(0)}% chance this is enough` } }, refLines: { lines: refs } } } }));
  $("#c-safe-tbl").innerHTML = table(["Certainty", "Points"], L.map(l => [Math.round(l.conf * 100) + "%", nf(l.points)]), ["", "n"]);
  const extra = g(0.95) - g(0.5);
  $("#c-safe-take").innerHTML = take("", `Going from a coin flip (<b>${nf(g(0.5))}</b>) to <b>95% sure</b> (<b>${nf(g(0.95))}</b>) costs <b>${nf(extra)} more points</b> (${pc(extra / g(0.5), 1)}). ${SS.pts && SS.played ? "" : "Enter your progress above to see where you land on this curve."}`);
}

// ---------------------------------------------------------------- 6 keep playing?
function renderStop() {
  const el = $("#p-stop"); if (!el) return; drop("stop");
  const pr = SS.d.profile, s = SS.d.safety;
  if (!pr || pr.error || !s) { el.innerHTML = `<div class="card empty">${esc(pr && pr.error || "Waiting for data…")}</div>`; return; }
  if (s.error && !SS.aim) { el.innerHTML = `<div class="card empty">${esc(s.error)}</div>`; return; }
  const bands = [{ key: "focus", name: `Players around #${pr.rank}`, b: pr.focus }, ...pr.bands.map(b => ({ key: b.from + "-" + b.to, name: `Top #${b.from}–${b.to}`, b }))];
  const sel = bands.find(x => x.key === SS.like) || bands[0], samp = sel.b.sample;
  const cap = capOf(), rem = Math.max(0, cap - SS.played), mean = sel.b.pts_per_game;
  const cuts = SS.aim ? [{ n: "Your aim", v: SS.aim, c: SER(0) }] : s.final ? [{ n: "Final cutoff", v: s.likely, c: SER(0) }] : [{ n: "Likely cutoff", v: s.ladder.find(x => x.conf === 0.5).points, c: SER(0) }, { n: "Comfortable (80%)", v: s.ladder.find(x => x.conf === 0.8).points, c: SER(1) }, { n: "Safe (95%)", v: s.ladder.find(x => x.conf === 0.95).points, c: SER(2) }];
  const SIMS = 6000, rnd = rng(Math.round(SS.rank * 7 + SS.pts + SS.played * 13)), hit = cuts.map(() => new Array(rem + 1).fill(0));
  for (let i = 0; i < SIMS; i++) { let t = SS.pts; for (let k = 0; k <= rem; k++) { if (k) t += samp[(rnd() * samp.length) | 0]; cuts.forEach((c, ci) => { if (t >= c.v) hit[ci][k]++; }); } }
  const P = hit.map(h => h.map(x => x / SIMS * 100));
  const mi = Math.max(0, cuts.findIndex(c => c.v === aimPoints())), key = mi < 0 ? 0 : mi;
  const pAll = P[key][rem], p0 = P[key][0], p1 = rem ? P[key][1] : p0;
  let cls, head, body;
  if (p0 >= 99) { cls = "stop"; head = "You are already above this cutoff"; body = `Your ${nf(SS.pts)} points already beat ${nf(cuts[key].v)}. More games cannot lower your rank, but they add little unless the cutoff moves higher than predicted.`; }
  else if (rem === 0) { cls = "hard"; head = "No games left"; body = `You have played all ${cap} games. Your ${nf(SS.pts)} points are ${SS.pts >= cuts[key].v ? "above" : "below"} ${nf(cuts[key].v)}.`; }
  else if (pAll < 3) { cls = "hard"; head = `Very unlikely (${nd(pAll)}%)`; body = `Even playing all ${rem} remaining games like ${sel.name.toLowerCase()}, you reach ${nf(cuts[key].v)} in only ${nd(pAll)}% of simulations. You need ${nf(Math.max(0, cuts[key].v - SS.pts))} more points, but such players earn about ${nf(mean * rem)} in ${rem} games.`; }
  else if (p1 - p0 < 1 && rem > 1) { cls = "go"; head = `Keep going: ${nd(pAll)}% over ${rem} games`; body = `One more game barely moves the odds (${nd(p0)}% → ${nd(p1)}%); the chance builds over the full set of games.`; }
  else { cls = "go"; head = `Keep playing: ${nd(pAll)}% chance with ${rem} games left`; body = `The next game alone lifts your chance from ${nd(p0)}% to ${nd(p1)}%. Points never go down, so playing on only costs time.`; }
  el.innerHTML = `<div class="ctrl"><label style="margin:0">Play like</label><select id="slike" style="width:auto;margin:0">${bands.map(x => `<option value="${x.key}" ${x.key === sel.key ? "selected" : ""}>${esc(x.name)} (${nd(x.b.pts_per_game)} pts/game)</option>`).join("")}</select></div>
  <div class="verdict ${cls}"><div><div class="big">${head}</div><div>${body}</div></div></div>
  <div class="kpis">${kpi("Still needed", nf(Math.max(0, cuts[key].v - SS.pts)), "to reach " + nf(cuts[key].v), "hero")}${kpi("Expected in " + rem + " games", nf(mean * rem), nd(mean) + " per game")}${kpi("Spread (1 sd)", "± " + nf(sel.b.sd * Math.sqrt(rem)), "over " + rem + " games")}${kpi("Next game adds", rem ? "+" + nd(p1 - p0) + "%" : "-", "to your chance")}</div>
  ${chartCard("c-stop", "Chance to reach the cutoff by extra games played", `${SIMS.toLocaleString()} simulated runs, drawing each game from real results`, {})}`;
  put("stop", mk($("#c-stop"), { type: "line", data: { labels: Array.from({ length: rem + 1 }, (_, k) => k), datasets: cuts.map((c, i) => ({ label: `${c.n} · ${nf(c.v)}`, data: P[i], borderColor: c.c, backgroundColor: c.c, pointRadius: 3, borderWidth: i === key ? 3 : 1.8 })) }, options: { scales: { x: { title: { text: "Extra games played" } }, y: { min: 0, max: 100, title: { text: "Chance of reaching it (%)" }, ticks: { callback: v => v + "%" } } }, plugins: { tooltip: { callbacks: { title: c => c[0].label + " more games", label: c => `${c.dataset.label}: ${c.parsed.y.toFixed(0)}%` } } } } }));
  $("#c-stop-tbl").innerHTML = table(["Extra games", ...cuts.map(c => c.n)], P[0].map((_, k) => [k, ...P.map(r => nd(r[k], 0) + "%")]), ["n", ...cuts.map(() => "n")]);
  $("#c-stop-take").innerHTML = take("", `Based on ${SIMS.toLocaleString()} simulated runs. The cutoffs are the predicted <i>final</i> values, so they already allow for other players still playing. It assumes you play about like ${esc(sel.name.toLowerCase())}; pick a different group above if that is too optimistic.`);
  $("#slike").onchange = e => { SS.like = e.target.value; saveSS(); renderStop(); };
}
