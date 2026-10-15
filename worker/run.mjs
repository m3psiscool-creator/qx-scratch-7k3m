// Turns the replays of one tournament window into Dropspots data.
//   node run.mjs <window_id> [--limit 50] [--maxms 240000] [--dry]
// env: ADMIN_KEY (required), SITE, LANDINGS_DLL (path of the built landings tool), DOTNET (dotnet executable),
//      MAP_BOUNDS "minX,maxX,minY,maxY" (world units, default -55000,55000,-55000,55000)
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { buildReplay } from './replay.mjs';

const SITE = process.env.SITE || 'https://fn-game-analyzer.vercel.app';
const KEY = process.env.ADMIN_KEY;
const DLL = process.env.LANDINGS_DLL || join(import.meta.dirname, 'landings', 'out', 'landings.dll');
const DOTNET = process.env.DOTNET || 'dotnet';
const [minX, maxX, minY, maxY] = (process.env.MAP_BOUNDS || '-55000,55000,-55000,55000').split(',').map(Number);
const BASE = 128;

const args = process.argv.slice(2);
const windowId = args[0];
const opt = (name, d) => { const i = args.indexOf(`--${name}`); return i >= 0 ? Number(args[i + 1]) : d; };
const LIMIT = opt('limit', 50), MAXMS = opt('maxms', 240000), DRY = args.includes('--dry');
if (!windowId || !KEY) { console.error('usage: ADMIN_KEY=... node run.mjs <window_id> [--limit N] [--maxms MS] [--dry]'); process.exit(2); }

const api = async (path, init = {}) => {
  const r = await fetch(SITE + path, { ...init, headers: { 'x-admin-key': KEY, 'content-type': 'application/json', ...(init.headers || {}) } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error(`${path}: ${j.error || r.status}`);
  return j;
};

// world coordinates -> 0..1 across the map picture (north up: +X is north, +Y is east)
const toUnit = (x, y) => [(y - minY) / (maxY - minY), (maxX - x) / (maxX - minX)];
const inside = ([u, v]) => u >= 0 && u <= 1 && v >= 0 && v <= 1;

const listing = await api(`/api/admin/matches?window=${encodeURIComponent(windowId)}`);
const done = new Set(listing.done);
// A tournament has thousands of matches. Alternate between the matches with the most qualifying teams (the ones that
// answer "where did the qualifiers land") and a random draw (so "everyone else" is not skewed towards qualifiers).
const TOP = opt('top', 1000);
const pending = listing.sessions.filter((s) => !done.has(s.session));
const byQual = [...pending].sort((a, b) => b.teams.filter((t) => t.rank <= TOP).length - a.teams.filter((t) => t.rank <= TOP).length);
const shuffled = [...pending].sort(() => Math.random() - 0.5);
const todo = [], seen = new Set();
for (let i = 0; todo.length < Math.min(LIMIT, pending.length); i++) {
  for (const s of [byQual[i], shuffled[i]]) if (s && !seen.has(s.session) && todo.length < LIMIT) { seen.add(s.session); todo.push(s); }
}
const started = Date.now();
console.log(`${windowId}: ${listing.sessions.length} matches, ${done.size} done, processing ${todo.length}`);
if (!todo.length) process.exit(0);

const dir = mkdtempSync(join(tmpdir(), 'replays-'));
const files = [];
let next = 0, failed = 0;
async function worker() {
  while (next < todo.length) {
    const s = todo[next++];
    try {
      const { buffer } = await buildReplay(s.session, KEY, { maxMs: MAXMS });
      const f = join(dir, `${s.session}.replay`);
      writeFileSync(f, buffer);
      files.push({ s, f });
    } catch (e) { failed++; console.warn(`skip ${s.session}: ${e.message}`); }
  }
}
await Promise.all([worker(), worker()]);

const rows = [], cells = new Map(), finished = [];
let noMatch = 0;
for (let i = 0; i < files.length; i += 20) {
  const part = files.slice(i, i + 20);
  const run = spawnSync(DOTNET, [DLL, ...part.map((p) => p.f)], { encoding: 'utf8', maxBuffer: 1 << 29 });
  if (run.status !== 0) { console.warn('parser failed', (run.stderr || '').slice(0, 300)); continue; }
  const out = run.stdout.split('\n').filter(Boolean).map((l) => JSON.parse(l.replace(/^﻿/, '')));
  for (const res of out) {
    const { s } = part.find((p) => res.file === `${p.s.session}.replay`) || {};
    if (!s || res.error) { console.warn(`parse error ${res.file}: ${res.error}`); continue; }
    finished.push(s.session);
    const byTeam = new Map();
    for (const p of res.players) if (p.x != null) (byTeam.get(p.team) || byTeam.set(p.team, []).get(p.team)).push(p);
    for (const t of s.teams) {
      const mine = new Set(t.accounts.map((a) => a.toLowerCase()));
      const found = [...byTeam.values()].find((ps) => ps.some((p) => mine.has(p.epic.toLowerCase())));
      if (!found) { noMatch++; continue; }
      const x = found.reduce((a, p) => a + p.x, 0) / found.length, y = found.reduce((a, p) => a + p.y, 0) / found.length;
      const u = toUnit(x, y);
      if (!inside(u)) continue;
      rows.push({ game: t.game, team: t.accounts.map((a) => a.toLowerCase()).join('+'), x: u[0], y: u[1], placement: t.placement || 0,
        points: t.points ?? undefined, elims: t.elims, rank: t.rank || 0, win: !!t.win });
    }
    for (const [x, y] of res.trail || []) {
      const u = toUnit(x, y);
      if (!inside(u)) continue;
      const k = Math.min(BASE - 1, Math.floor(u[1] * BASE)) * BASE + Math.min(BASE - 1, Math.floor(u[0] * BASE));
      cells.set(k, (cells.get(k) || 0) + 1);
    }
  }
}
rmSync(dir, { recursive: true, force: true });
console.log(`landings for ${rows.length} teams from ${finished.length} matches (${failed} downloads failed, ${noMatch} teams not found in the replay) in ${((Date.now() - started) / 1000).toFixed(0)}s`);

if (DRY) { console.log(JSON.stringify(rows.slice(0, 5))); process.exit(0); }
const code = (listing.playlist || '').match(/SourSpawn|BlastBerry|DashBerry|PiperBoot|JumpBear/i)?.[0] || '';
const kind = listing.game_type === 'reload' || /reload/i.test(listing.playlist || '') ? 'Reload map' : 'Battle Royale island';
for (let i = 0; i < Math.max(rows.length, 1); i += 4000) {
  const chunk = rows.slice(i, i + 4000);
  const last = i + 4000 >= rows.length;
  const res = await api('/api/admin/drops', { method: 'POST', body: JSON.stringify({
    window_id: windowId, append: true, coords: 'unit', drops: chunk,
    map: { name: code ? `${kind} (${code})` : kind, credit: 'Map drawn from where players moved in the replays', base: last ? { size: BASE, cells: [...cells] } : undefined },
    sessions_done: last ? finished : undefined }) });
  console.log('stored', res.stored, 'skipped', res.skipped);
}
