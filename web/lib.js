"use strict";
// Shared helpers: formatting, storage, chart theme and chart plugins.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const nf = x => (x == null || isNaN(x)) ? "-" : Math.round(x).toLocaleString();
const nd = (x, d = 1) => (x == null || isNaN(x)) ? "-" : (+x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const pc = (x, d = 0) => (x == null || isNaN(x)) ? "-" : (x * 100).toFixed(d) + "%";
const fmt = t => new Date(t * 1000).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtDay = t => new Date(t * 1000).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
const hm = t => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const ago = s => s == null ? "-" : s < 90 ? s + "s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago";
const dur = s => { s = Math.max(0, Math.round(s)); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + "d " : "") + (h || d ? h + "h " : "") + m + "m " + (s % 60) + "s" };
// readable gamemode name from the internal key ("reload zb duo" -> "Reload Zero Build Duo")
const GM = { reload: "Reload", br: "Battle Royale", zb: "Zero Build", solo: "Solo", duo: "Duo", trio: "Trio", squads: "Squads", mobile: "Mobile" };
const gm = c => String(c || "").split(" ").map(x => GM[x] || x).join(" ");
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } },
};
async function j(url, opt) { const r = await fetch(url, opt); return r.json(); }

// ---------------------------------------------------------------- icons (stroke, 24px grid)
const ICON = {
  home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
  cal: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  trophy: '<path d="M8 4h8v6a4 4 0 0 1-8 0V4z"/><path d="M8 6H4v1a4 4 0 0 0 4 4M16 6h4v1a4 4 0 0 1-4 4M12 14v4M8 21h8M10 18h4"/>',
  archive: '<rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5M3 17.5l9 5 9-5" opacity=".6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
  gauge: '<path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-6"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2.1-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2.1 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-.9c.6.5 1.3.9 2.1 1.2L10 21h4l.5-2.6c.8-.3 1.5-.7 2.1-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"/>',
  more: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  map: '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
  route: '<circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/>',
  pin: '<path d="M12 21s7-6.2 7-11a7 7 0 0 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>',
};
const icon = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[n] || ""}</svg>`;

// ---------------------------------------------------------------- charts
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const SER = i => cssv("--s" + ((((i % 8) + 8) % 8) + 1));
const RAMP = n => Array.from({ length: n }, (_, i) => cssv("--r" + (1 + Math.round(i * 6 / Math.max(1, n - 1)))));
let charts = [];
const destroyCharts = () => { charts.forEach(c => { try { c.destroy(); } catch (e) { } }); charts = []; };
// colour + alpha without creating a canvas (every throw-away canvas context counts against the browser's limit and can blank real charts)
const _al = {};
const withAlpha = (c, a) => {
  const k = c + "|" + a; if (_al[k]) return _al[k];
  let m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c.trim()), r, g, b;
  if (m) { let h = m[1]; if (h.length === 3) h = h.split("").map(x => x + x).join(""); const n = parseInt(h, 16); r = n >> 16; g = n >> 8 & 255; b = n & 255; }
  else { m = /rgba?\(([^)]+)\)/.exec(c); if (!m) return c; [r, g, b] = m[1].split(",").map(x => parseFloat(x)); }
  return _al[k] = `rgba(${r},${g},${b},${a})`;
};

if (window.Chart) {
  // vertical hover line + reference lines (axis 'x'|'y', value, label)
  Chart.register({
    id: "viz",
    afterDatasetsDraw(chart) {
      const o = chart.options.plugins || {}, a = chart.chartArea, c = chart.ctx;
      const refs = (o.refLines && o.refLines.lines) || [];
      c.save(); c.beginPath(); c.rect(a.left, a.top, a.width, a.height); c.clip();
      refs.forEach(r => {
        const sc = chart.scales[r.axis === "y" ? (r.scale || "y") : (r.scale || "x")]; if (!sc || r.value == null) return;
        const px = sc.getPixelForValue(r.value);
        c.strokeStyle = r.color || cssv("--tx2"); c.lineWidth = 1.5; c.setLineDash(r.dash || [5, 4]);
        c.beginPath();
        if (r.axis === "y") { c.moveTo(a.left, px); c.lineTo(a.right, px); } else { c.moveTo(px, a.top); c.lineTo(px, a.bottom); }
        c.stroke(); c.setLineDash([]);
        if (r.label) {
          c.font = "600 11px system-ui,sans-serif"; const w = c.measureText(r.label).width + 10;
          const x = r.axis === "y" ? (r.right ? a.right - w - 4 : a.left + 4) : clamp(px + 4, a.left, a.right - w), y = r.axis === "y" ? px - 18 : a.top + 4 + (r.row || 0) * 20;
          c.fillStyle = cssv("--sf"); c.globalAlpha = .9; c.fillRect(x, y, w, 17); c.globalAlpha = 1;
          c.fillStyle = r.color || cssv("--tx"); c.textBaseline = "middle"; c.fillText(r.label, x + 5, y + 9);
        }
      });
      c.restore();
      if (o.crosshair && o.crosshair.on && chart.tooltip && chart.tooltip._active && chart.tooltip._active.length) {
        const x = chart.tooltip._active[0].element.x;
        c.save(); c.strokeStyle = cssv("--line2"); c.lineWidth = 1; c.beginPath(); c.moveTo(x, a.top); c.lineTo(x, a.bottom); c.stroke(); c.restore();
      }
    },
  });
}
const merge = (a, b) => { for (const k in b) { if (b[k] && typeof b[k] === "object" && !Array.isArray(b[k]) && a[k] && typeof a[k] === "object" && !Array.isArray(a[k])) merge(a[k], b[k]); else a[k] = b[k]; } return a; };
function themeChart() {
  const D = Chart.defaults;
  D.color = cssv("--tx2"); D.borderColor = cssv("--grid"); D.font.family = "system-ui,-apple-system,'Segoe UI',sans-serif"; D.font.size = 12;
  D.animation = false;   // animations clash with the page re-drawing charts while they run (Chart.js 'this._fn' error)
}
// mk(canvas, config) -> Chart with the site look. config.options is merged over the defaults.
function mk(canvas, cfg) {
  if (!canvas || !window.Chart || !canvas.isConnected) return null;
  const prev = Chart.getChart(canvas); if (prev) prev.destroy();   // never two charts on one canvas
  themeChart();
  const grid = cssv("--grid"), mut = cssv("--mut");
  const axis = { grid: { color: grid, drawTicks: false }, border: { color: cssv("--axis") }, ticks: { color: mut, padding: 6, callback: v => typeof v === "number" ? v.toLocaleString() : v } };
  const base = {
    responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
    elements: { line: { borderWidth: 2, tension: 0.2 }, point: { radius: 0, hoverRadius: 5, hitRadius: 14, borderWidth: 2, borderColor: cssv("--sf") }, bar: { borderRadius: 4, borderSkipped: "bottom" } },
    plugins: {
      legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "rectRounded", boxWidth: 8, boxHeight: 8, padding: 14, color: cssv("--tx2") } },
      tooltip: { backgroundColor: cssv("--sf"), titleColor: cssv("--tx"), bodyColor: cssv("--tx2"), borderColor: cssv("--line2"), borderWidth: 1, padding: 10, cornerRadius: 10, boxPadding: 4, usePointStyle: true, titleFont: { weight: "700" } },
      crosshair: { on: cfg.type === "line" },
    },
    scales: { x: JSON.parse(JSON.stringify(axis)), y: JSON.parse(JSON.stringify(axis)) },
  };
  const tickFmt = function (v) { return this.type === "category" ? this.getLabelForValue(v) : typeof v === "number" ? v.toLocaleString() : v; };
  base.scales.x.ticks.callback = tickFmt; base.scales.y.ticks.callback = tickFmt;
  base.scales.x.grid.display = cfg.type === "bar" ? false : true;
  const out = { type: cfg.type, data: cfg.data, options: merge(base, cfg.options || {}) };
  // zoom with ctrl+scroll or a pinch, pan by dragging, double-click to reset
  if (cfg.zoom) { const mode = cfg.zoom === "xy" ? "xy" : "x"; out.options.plugins.zoom = { limits: { x: { min: "original", max: "original" }, y: { min: "original", max: "original" } }, zoom: { wheel: { enabled: true, modifierKey: "ctrl" }, pinch: { enabled: true }, mode }, pan: { enabled: true, mode, threshold: 8 } }; }
  // click a point/bar/line: cfg.click(hit, chart)
  if (cfg.click) {
    out.options.onClick = (evt, els, ch) => { const hit = ch.getElementsAtEventForMode(evt.native || evt, cfg.clickMode || "nearest", { intersect: cfg.clickIntersect === true, axis: cfg.clickAxis || "x" }, true); if (hit.length) setTimeout(() => cfg.click(hit[0], ch), 0); };   // after the chart has finished handling the event, so a click may redraw it
    out.options.onHover = (evt, els, ch) => { ch.canvas.style.cursor = els.length ? "pointer" : "default"; };
  }
  Object.values(out.options.scales).forEach(s => { if (s.title && s.title.text) { s.title.display = true; s.title.color = cssv("--mut"); s.title.font = { size: 11, weight: "600" }; } });
  const c = new Chart(canvas, out); charts.push(c);
  if (cfg.zoom) canvas.addEventListener("dblclick", () => { try { c.resetZoom(); } catch (e) { } });
  return c;
}
// A titled chart card with an optional table view (accessibility + exact numbers).
const TOOL = { reset: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>', png: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>' };
function chartCard(id, title, sub, o = {}) {
  const tool = (act, tip) => `<button class="tool" data-chart-act="${act}" data-for="${id}" data-name="${esc(String(title).replace(/<[^>]*>/g, "").replace(/\W+/g, "-").toLowerCase())}" title="${tip}" aria-label="${tip}"><svg viewBox="0 0 24 24">${TOOL[act]}</svg></button>`;
  return `<div class="card"><div class="hd"><h2>${title}</h2><span class="hr"><span class="sub">${sub || ""}</span><span class="tools">${o.zoom ? tool("reset", "Reset zoom (or double-click the chart)") : ""}${tool("png", "Save as image")}</span></span></div>${o.ctrl ? `<div class="ctrl" id="${id}-ctrl">${o.ctrl}</div>` : ""}
    <div class="cv ${o.cls || ""}"><canvas id="${id}"></canvas></div>${o.zoom ? '<div class="hint">Drag to pan · Ctrl + scroll or pinch to zoom · double-click to reset</div>' : ""}<div id="${id}-take"></div>${o.table !== false ? `<details class="tv"><summary>Show as table</summary><div id="${id}-tbl"></div></details>` : ""}</div>`;
}
const take = (kind, html) => `<div class="takeaway ${kind || ""}">${icon("info")}<div>${html}</div></div>`;
function table(head, rows, cls = []) {
  return `<div class="scroll"><table><tr>${head.map((h, i) => `<th class="${cls[i] || ""}">${h}</th>`).join("")}</tr>` +
    rows.map(r => `<tr>${r.map((c, i) => `<td class="${cls[i] || ""}">${c}</td>`).join("")}</tr>`).join("") + "</table></div>";
}
// Low / Most likely / Safe as one picture. Low and Safe are the 10th and 90th percentile, so the chance that the final cutoff lands
// nearest each of the three numbers follows from the bell curve (log scale): the middle one always carries the most.
const _Phi = z => { const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2), p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - p : p; };
function estimateStrip(d) {
  if (!d || d.final || !(d.safe > d.low)) return "";
  const L = x => Math.log1p(Math.max(x, 0)), m = L(d.likely), sd = Math.max((L(d.safe) - L(d.low)) / (2 * 1.2816), 1e-6);
  const pMid = 2 * _Phi(0.6408) - 1, pSide = (1 - pMid) / 2, core = z => Math.round(Math.expm1(m + z * 0.6745 * sd));
  const lo = L(d.low), hi = L(d.safe), pos = x => 100 * (L(x) - lo) / (hi - lo);
  const c1 = Math.max(core(-1), d.low), c2 = Math.min(core(1), d.safe);
  const pc = p => Math.round(p * 100) + "%";
  return `<div class="est">
    <div class="est-cols">
      <div class="est-c est-side"><div class="l">Low case</div><div class="v">${nf(d.low)}</div><div class="d">${pc(pSide)} chance it ends nearest here</div></div>
      <div class="est-c mid"><div class="l">Most likely</div><div class="v">${nf(d.likely)}</div><div class="d"><b>${pc(pMid)}</b> chance it ends nearest here: the single best bet</div></div>
      <div class="est-c est-side"><div class="l">Safe case</div><div class="v">${nf(d.safe)}</div><div class="d">${pc(pSide)} chance it ends nearest here</div></div>
    </div>
    <div class="est-bar" title="Thin line: the range the cutoff lands in 8 times out of 10. Thick part: even odds (half of the time).">
      <i class="r80"></i><i class="r50" style="left:${pos(c1)}%;width:${Math.max(pos(c2) - pos(c1), 2)}%"></i><i class="pt" style="left:${pos(d.likely)}%"></i>
    </div>
    <div class="est-note small">The cutoff lands between <b>${nf(d.low)}</b> and <b>${nf(d.safe)}</b> about 8 times in 10, and between <b>${nf(c1)}</b> and <b>${nf(c2)}</b> about half of the time.</div>
  </div>`;
}
// grid on/off is remembered across the Dropspots, Map and Rotations maps
const gridPref = def => { try { const v = localStorage.getItem("fga-grid"); return v === null ? def : v === "1"; } catch (e) { return def; } };
const gridSave = on => { try { localStorage.setItem("fga-grid", on ? "1" : "0"); } catch (e) { } };
const kpi = (l, v, d, c) => `<div class="kpi ${c || ""}"><div class="l">${l}</div><div class="v">${v}</div>${d ? `<div class="d">${d}</div>` : ""}</div>`;
const skel = (n = 1, h = 120) => Array.from({ length: n }, () => `<div class="skel" style="height:${h}px;margin:0 0 16px"></div>`).join("");
// deterministic random numbers so a simulation does not flicker between renders
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

// Browsers can throw away canvas contents of a hidden tab or after a graphics reset (the chart turns black).
// Redraw every chart whenever the page comes back, and rebuild the page if a canvas context was really lost.
const redrawCharts = () => charts.forEach(c => { try { c.resize(); c.update("none"); } catch (e) { } });
document.addEventListener("visibilitychange", () => { if (!document.hidden) { redrawCharts(); setTimeout(redrawCharts, 400); } });
window.addEventListener("focus", () => setTimeout(redrawCharts, 100));
window.addEventListener("pageshow", () => setTimeout(redrawCharts, 100));
let _lostAt = 0;
document.addEventListener("contextlost", e => { if (e.target && e.target.tagName === "CANVAS" && Date.now() - _lostAt > 5000) { _lostAt = Date.now(); setTimeout(() => { if (typeof route === "function") route(); }, 150); } }, true);

// chart toolbar buttons (reset zoom, save as image)
function savePng(ch, name) {
  const c = ch.canvas, t = document.createElement("canvas"); t.width = c.width; t.height = c.height;
  const x = t.getContext("2d"); x.fillStyle = cssv("--sf"); x.fillRect(0, 0, t.width, t.height); x.drawImage(c, 0, 0);
  t.toBlob(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = (name || "chart") + ".png"; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 3000); });
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-chart-act]"); if (!b) return;
  const cv = document.getElementById(b.dataset.for), ch = cv && window.Chart && Chart.getChart(cv); if (!ch) return;
  if (b.dataset.chartAct === "reset") { try { ch.resetZoom(); } catch (er) { } } else savePng(ch, b.dataset.name);
});
// normal distribution, for turning a points total into a chance
const erf = x => { const s = Math.sign(x), t = 1 / (1 + 0.3275911 * Math.abs(x)); return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x)); };
const phi = x => 0.5 * (1 + erf(x / Math.SQRT2));

// A container, drawn on a canvas. `s` = half its width in pixels; `ring` (a colour) puts a glow behind it, used to show how often it is
// opened (green = rarely, red = in most games). kind: chest (wood and gold), rare (blue and gold), ammo (green box), produce (crate),
// cash (register), fishing (barrel).
function drawChest(x, cx, cy, s, ring, kind) {
  kind = kind || "chest";
  x.save(); x.translate(cx, cy);
  if (ring) { x.beginPath(); x.arc(0, 0, s * 1.45, 0, 7); x.fillStyle = ring; x.globalAlpha = 0.9; x.fill(); x.globalAlpha = 1; x.lineWidth = Math.max(1, s * 0.16); x.strokeStyle = "rgba(10,12,20,.9)"; x.stroke(); }
  const lw = Math.max(1, s * 0.15); x.lineJoin = "round"; x.lineWidth = lw; x.strokeStyle = "#241407";
  const w = s * 1.7, h = s * 1.15, top = -h * 0.55, lid = h * 0.52;
  if (kind === "ammo" || kind === "produce") {
    const body = kind === "ammo" ? "#5a7a35" : "#b98a4a", band = kind === "ammo" ? "#d8e6a8" : "#7aa83c";
    x.fillStyle = body; x.beginPath(); x.rect(-w / 2, -h * 0.4, w, h * 0.95); x.fill(); x.stroke();
    x.fillStyle = band; x.fillRect(-w / 2, -h * 0.4, w, h * 0.28); x.fillRect(-w * 0.08, -h * 0.4, w * 0.16, h * 0.95);
  } else if (kind === "cash") {
    x.fillStyle = "#8d98a8"; x.beginPath(); x.rect(-w / 2, -h * 0.1, w, h * 0.6); x.fill(); x.stroke();
    x.fillStyle = "#cfd6e2"; x.fillRect(-w * 0.35, -h * 0.55, w * 0.7, h * 0.4); x.strokeRect(-w * 0.35, -h * 0.55, w * 0.7, h * 0.4);
    x.fillStyle = "#4a5568"; x.fillRect(-w * 0.28, -h * 0.47, w * 0.56, h * 0.22);
  } else if (kind === "fishing") {
    x.fillStyle = "#6b4a2b"; x.beginPath(); x.ellipse(0, 0, w * 0.38, h * 0.62, 0, 0, 7); x.fill(); x.stroke();
    x.fillStyle = "#c9a15a"; x.fillRect(-w * 0.38, -h * 0.2, w * 0.76, Math.max(1, s * 0.18)); x.fillRect(-w * 0.38, h * 0.2, w * 0.76, Math.max(1, s * 0.18));
  } else {
    const rare = kind === "rare";
    x.fillStyle = rare ? "#4a6fb5" : "#9a6430"; x.beginPath(); x.rect(-w / 2, top + lid * 0.85, w, h - lid * 0.85); x.fill(); x.stroke();                                    // body
    x.fillStyle = rare ? "#6a8fdc" : "#b9803f"; x.beginPath(); x.moveTo(-w / 2, top + lid); x.quadraticCurveTo(0, top - lid * 0.5, w / 2, top + lid); x.closePath(); x.fill(); x.stroke();   // lid
    x.fillStyle = "#f4c93a"; x.fillRect(-w / 2, top + lid * 0.78, w, Math.max(1, s * 0.2));                                                                                       // gold rim
    x.fillRect(-w * 0.34, top + lid * 0.05, Math.max(1, s * 0.2), h * 0.95); x.fillRect(w * 0.34 - Math.max(1, s * 0.2), top + lid * 0.05, Math.max(1, s * 0.2), h * 0.95);       // gold bands
    x.fillStyle = "#ffe27a"; x.fillRect(-s * 0.2, top + lid * 0.72, s * 0.4, s * 0.45);                                                                                           // lock
  }
  x.restore();
}
