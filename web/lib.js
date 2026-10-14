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
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>',
};
const icon = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[n] || ""}</svg>`;

// ---------------------------------------------------------------- charts
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const SER = i => cssv("--s" + ((((i % 8) + 8) % 8) + 1));
const RAMP = n => Array.from({ length: n }, (_, i) => cssv("--r" + (1 + Math.round(i * 6 / Math.max(1, n - 1)))));
let charts = [];
const destroyCharts = () => { charts.forEach(c => { try { c.destroy(); } catch (e) { } }); charts = []; };
const withAlpha = (c, a) => { const d = document.createElement("canvas").getContext("2d"); d.fillStyle = c; const v = d.fillStyle; if (v[0] === "#") { const n = parseInt(v.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; } return v.replace(/rgba?\(([^)]+)\)/, (_, p) => `rgba(${p.split(",").slice(0, 3).join(",")},${a})`); };

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
  D.animation = { duration: 220 };
}
// mk(canvas, config) -> Chart with the site look. config.options is merged over the defaults.
function mk(canvas, cfg) {
  if (!canvas || !window.Chart) return null;
  themeChart();
  const grid = cssv("--grid"), mut = cssv("--mut");
  const axis = { grid: { color: grid, drawTicks: false }, border: { color: cssv("--axis") }, ticks: { color: mut, padding: 6, callback: v => typeof v === "number" ? v.toLocaleString() : v } };
  const base = {
    responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
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
  Object.values(out.options.scales).forEach(s => { if (s.title && s.title.text) { s.title.display = true; s.title.color = cssv("--mut"); s.title.font = { size: 11, weight: "600" }; } });
  const c = new Chart(canvas, out); charts.push(c); return c;
}
// A titled chart card with an optional table view (accessibility + exact numbers).
function chartCard(id, title, sub, o = {}) {
  return `<div class="card"><div class="hd"><h2>${title}</h2><span class="sub">${sub || ""}</span></div>${o.ctrl ? `<div class="ctrl" id="${id}-ctrl">${o.ctrl}</div>` : ""}
    <div class="cv ${o.cls || ""}"><canvas id="${id}"></canvas></div><div id="${id}-take"></div>${o.table !== false ? `<details class="tv"><summary>Show as table</summary><div id="${id}-tbl"></div></details>` : ""}</div>`;
}
const take = (kind, html) => `<div class="takeaway ${kind || ""}">${icon("info")}<div>${html}</div></div>`;
function table(head, rows, cls = []) {
  return `<div class="scroll"><table><tr>${head.map((h, i) => `<th class="${cls[i] || ""}">${h}</th>`).join("")}</tr>` +
    rows.map(r => `<tr>${r.map((c, i) => `<td class="${cls[i] || ""}">${c}</td>`).join("")}</tr>`).join("") + "</table></div>";
}
const kpi = (l, v, d, c) => `<div class="kpi ${c || ""}"><div class="l">${l}</div><div class="v">${v}</div>${d ? `<div class="d">${d}</div>` : ""}</div>`;
const skel = (n = 1, h = 120) => Array.from({ length: n }, () => `<div class="skel" style="height:${h}px;margin:0 0 16px"></div>`).join("");
// deterministic random numbers so a simulation does not flicker between renders
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
