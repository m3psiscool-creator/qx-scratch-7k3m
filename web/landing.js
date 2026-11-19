"use strict";
// Signed-out home and site sign-in (Google). The rest of the site is only shown to signed-in visitors.
let SESSION = store.get("sess", null);   // { token, user: {name, first, picture} }
function sessionOk() {
  if (!SESSION || !SESSION.token) return false;
  try { const p = JSON.parse(atob(SESSION.token.split(".")[0].replace(/-/g, "+").replace(/_/g, "/"))); return p.exp * 1000 > Date.now(); } catch (e) { return false; }
}
function applySessionUi() {
  const out = !sessionOk();
  document.body.classList.toggle("signedout", out);
  const so = $("#signout"); if (so) so.hidden = out;
}
function setSession(r) { SESSION = { token: r.token, user: r.user }; store.set("sess", SESSION); applySessionUi(); location.hash = "#/"; route(); }
function signOut() { SESSION = null; store.set("sess", null); applySessionUi(); location.hash = "#/"; route(); }
// a session the server no longer accepts (changed secret, expired) is dropped
async function checkSession() {
  if (!sessionOk()) return;
  try { const r = await fetch("/api/auth/me", { headers: { authorization: "Bearer " + SESSION.token } }); if (r.status === 401) signOut(); } catch (e) { /* offline: keep */ }
}

let GCFG = null;
function loadScriptOnce(src) { return new Promise((ok, no) => { if ($(`script[src="${src}"]`)) return ok(); const s = document.createElement("script"); s.src = src; s.async = true; s.onload = ok; s.onerror = no; document.head.appendChild(s); }); }
async function googleSlots() {
  const slots = $$(".gslot"); if (!slots.length) return;
  if (!GCFG) { try { GCFG = await j("/api/auth/config"); } catch (e) { GCFG = {}; } }
  if (!GCFG.google_client_id) { slots.forEach(s => { s.innerHTML = '<div class="lp-note">Google sign-in is being set up. Check back soon.</div>'; }); return; }
  try { await loadScriptOnce("https://accounts.google.com/gsi/client"); } catch (e) { slots.forEach(s => { s.innerHTML = '<div class="lp-note">Could not reach Google. Check your connection and reload.</div>'; }); return; }
  google.accounts.id.initialize({
    client_id: GCFG.google_client_id,
    callback: async resp => {
      const r = await fetch("/api/auth/google", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ credential: resp.credential }) });
      const d = await r.json();
      if (d.token) setSession(d); else { const m = $("#lp-msg"); if (m) m.textContent = d.error || "Sign-in failed."; }
    },
  });
  slots.forEach(s => {
    s.innerHTML = '<div class="gbtn"><span class="gface"><svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z"/><path fill="#FBBC05" d="M10.5 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7l-7.9-6.1C.9 16.4 0 20.1 0 24s.9 7.6 2.6 10.8l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z"/></svg>Continue with Google</span><div class="ghit"></div></div>';
    google.accounts.id.renderButton(s.querySelector(".ghit"), { type: "standard", theme: "filled_black", size: "large", text: "continue_with", width: 280 });
  });
}

// ---------------------------------------------------------------- the signed-out page
function landing() {
  destroyCharts();
  const FEAT = [["target", "Strategy plan", "Points to aim for, checkpoints for each game, finisher profiles and a safety margin."], ["map", "Dropspots", "Landing heatmaps and which drops qualified, for every map."], ["pin", "Chest map", "Every chest and container with how often it was opened early."], ["route", "Rotations", "Pick a tournament and a player, then replay each game's drop and rotations."]];
  app.innerHTML = `<div class="lp">
  <section class="lp-hero">
    <div>
      <div class="lp-eye">FNCS · Cash Cups · Skin Cups · NAC &amp; EU</div>
      <h1>Know the cutoff <em>before it happens</em></h1>
      <p class="lp-lead">Live leaderboards, predicted final cutoffs and a game plan for every tournament. See where teams landed, how they rotated, and what it took to qualify.</p>
      <div class="gslot"></div>
      <p class="small" id="lp-msg" style="margin-top:10px;color:var(--bad)"></p>
      <p class="small" style="margin-top:4px">Free. Sign in once with Google.</p>
    </div>
    <div class="lp-demo art" data-art="S43_TriosCashCup_Event2_EU" data-fam="CASHCUP">
      <div class="lp-demo-top"><b>EU Trios Cash Cup · Event 2</b><span class="pill live">live</span></div>
      <div class="small">Goal: Top 500 · 62% of the window played · example numbers</div>
      <div class="lp-est"><div><span>Low</span><b>480</b></div><div class="mid"><span>MOST LIKELY</span><b>520</b></div><div><span>Safe</span><b>560</b></div></div>
    </div>
  </section>

  <section class="lp-sec" id="lp-try">
    <div class="lp-eye">Try it, no account needed</div>
    <h2>Four questions the site answers during a tournament</h2>
    <p class="lp-sub">Move the sliders. These are small versions of the real tools, with example numbers.</p>
    <div class="lp-try">
      <div class="card" id="s1"><h3>Will I make the cutoff?</h3><p class="small">Top 500, 10 games, projected cutoff 520 points.</p>
        <div class="lp-ctl"><label for="s1p">Points so far</label><input id="s1p" type="range" min="0" max="500" value="260" step="5"><output id="s1po"></output>
          <label for="s1g">Games played</label><input id="s1g" type="range" min="1" max="9" value="5"><output id="s1go"></output></div>
        <div class="lp-res"><div class="big" id="s1r"></div><div class="small" id="s1s"></div><div class="lp-bar"><i id="s1b"></i></div></div></div>
      <div class="card" id="s2"><h3>How many games can I still fit?</h3><p class="small">A game ends when you do, so dying early frees the clock for another.</p>
        <div class="lp-ctl"><label for="s2t">Time left</label><input id="s2t" type="range" min="10" max="180" value="75" step="5"><output id="s2to"></output>
          <label for="s2p">Typical finish</label><select id="s2p"><option value="13">Out early (13 min)</option><option value="19" selected>Mid-game (19 min)</option><option value="25">Deep run (25 min)</option></select><span></span></div>
        <div class="lp-res"><div class="big" id="s2r"></div><div class="small" id="s2s"></div></div></div>
      <div class="card" id="s3"><h3>Where should I land?</h3><p class="small">Brighter squares had more qualifying teams (example island).</p>
        <div class="lp-map"><div class="lp-grid" id="s3g" role="group" aria-label="Map grid"></div><div class="lp-res" id="s3r"></div></div></div>
      <div class="card" id="s4"><h3>Which play style fits my goal?</h3><p class="small">How past finishers who reached Top 500 got their points.</p>
        <div class="lp-prof" id="s4b" role="group" aria-label="Play style"></div><div class="lp-rows" id="s4r"></div><div class="lp-res" id="s4s"></div></div>
    </div>
  </section>

  <section class="lp-sec">
    <div class="lp-eye">Inside, after you sign in</div>
    <h2>Everything for the live window, in one place</h2>
    <div class="lp-feats">${FEAT.map(([ic, t, d]) => `<div class="lp-feat"><div class="ic">${icon(ic)}</div><b>${t}</b><span>${d}</span></div>`).join("")}</div>
  </section>

  <section class="lp-final"><h2>Get the cutoff before your next cup</h2><p class="lp-sub" style="margin-inline:auto">Sign in with Google and the full site opens.</p><div class="gslot" style="display:flex;justify-content:center;margin-top:20px"></div></section>
  <p class="lp-foot">Unofficial fan site, not affiliated with Epic Games. Predictions are estimates, not guarantees.</p></div>`;
  googleSlots(); landingScenarios();
}

function landingScenarios() {
  const CUT = 520, TOTAL = 10;
  const s1 = () => {
    const p = +$("#s1p").value, g = +$("#s1g").value; $("#s1po").textContent = p; $("#s1go").textContent = g;
    const proj = Math.round(p + (TOTAL - g) * (p / g) * 0.92), chance = Math.round(100 / (1 + Math.exp(-1.7 * (proj - CUT) / 34)));
    $("#s1r").innerHTML = `${chance}% <span class="${chance >= 60 ? "good" : chance >= 35 ? "warn" : "bad"}" style="font-size:1rem;font-weight:650">${chance >= 60 ? "on track" : chance >= 35 ? "close" : "behind"}</span>`;
    $("#s1s").textContent = `On this pace you finish near ${proj} points. Expected cutoff ${CUT} (480–560).`; $("#s1b").style.width = chance + "%";
  };
  const s2 = () => {
    const t = +$("#s2t").value, m = +$("#s2p").value, n = Math.min(Math.ceil(t / m), 6);
    $("#s2to").textContent = t + " min"; $("#s2r").textContent = n + (n === 1 ? " game" : " games");
    $("#s2s").textContent = `About ${t} minutes at ${m} per game. From 300 points you would need ${Math.round((CUT - 300) / n * 10) / 10} per game to reach ${CUT}.`;
  };
  const COLS = "ABCDEFGHIJ", heat = []; let seed = 7, sel = -1; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let r = 0; r < 10; r++) for (let c = 0; c < 10; c++) { const dx = (c - 5.3) / 3.8, dy = (r - 4.4) / 3.4, land = dx * dx + dy * dy < 1.15, base = land ? Math.max(0, 1 - (dx * dx + dy * dy) * .55) : 0; const teams = land ? Math.round(base * 60 + rnd() * 14) : 0; heat.push({ land, teams, q: land ? Math.round(38 + rnd() * 36 - (teams > 40 ? 8 : 0)) : 0 }); }
  const best = heat.map((h, i) => ({ ...h, i })).filter(h => h.land && h.teams >= 18).sort((a, b) => b.q - a.q)[0];
  const s3 = () => {
    if (sel < 0) sel = best.i;
    const g = $("#s3g"); g.innerHTML = "";
    heat.forEach((h, i) => { const b = document.createElement("button"); b.type = "button"; b.disabled = !h.land; b.className = "lp-sq"; b.style.background = h.land ? `color-mix(in srgb,var(--ac) ${Math.round((.12 + Math.min(h.teams, 60) / 60 * .85) * 100)}%,var(--sf2))` : "var(--sf3)"; b.style.opacity = h.land ? 1 : .45; b.setAttribute("aria-label", COLS[i % 10] + (Math.floor(i / 10) + 1)); b.setAttribute("aria-pressed", i === sel); b.onclick = () => { sel = i; s3(); }; g.appendChild(b); });
    const h = heat[sel], name = COLS[sel % 10] + (Math.floor(sel / 10) + 1);
    $("#s3r").innerHTML = `<div class="small">Square</div><div class="big">${name}</div><div class="small">${h.teams} teams landed here</div><div class="small">${h.q}% of them qualified</div><div class="lp-bar"><i style="width:${h.q}%"></i></div>${sel === best.i ? '<div class="small good" style="margin-top:4px">Best qualify rate among busy squares</div>' : ""}`;
  };
  const STY = { Fragger: { place: 9.1, elims: 4.6, per: [["Elims", 64], ["Placement", 36]], txt: "Highest ceiling, but 4 in 10 runs end below the cutoff." }, Balanced: { place: 5.8, elims: 2.4, per: [["Elims", 44], ["Placement", 56]], txt: "Most finishers who reached Top 500 played this way." }, Survivor: { place: 3.2, elims: 1.1, per: [["Elims", 22], ["Placement", 78]], txt: "Steady points, but needs a deep run in most games." } };
  let sty = "Balanced";
  const s4 = () => {
    $("#s4b").innerHTML = Object.keys(STY).map(k => `<button type="button" aria-pressed="${k === sty}" data-k="${k}">${k}</button>`).join("");
    $$("#s4b button").forEach(b => b.onclick = () => { sty = b.dataset.k; s4(); });
    const s = STY[sty];
    $("#s4r").innerHTML = s.per.map(([l, v]) => `<div class="r"><span>${l}</span><div class="lp-bar" style="margin:0"><i style="width:${v}%"></i></div><b>${v}%</b></div>`).join("");
    $("#s4s").innerHTML = `<div class="big">Place ${s.place} · ${s.elims} elims</div><div class="small">Average per game. ${s.txt}</div>`;
  };
  ["s1p", "s1g"].forEach(i => $("#" + i).oninput = s1); ["s2t", "s2p"].forEach(i => $("#" + i).oninput = s2);
  s1(); s2(); s3(); s4();
}
