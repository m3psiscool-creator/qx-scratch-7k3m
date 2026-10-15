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
const LIMIT = opt('limit', 50), MAXMS = opt('maxms', 240000), DRY = args.includes('--dry'), RESET = args.includes('--reset');
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
const done = new Set(RESET ? [] : listing.done);   // --reset starts this window over: rows, finished matches and chest counts
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

const rows = [], cells = new Map(), chestCells = new Map(), finished = [];
let noMatch = 0, synthetic = 0, chestBursts = 0;
const CHEST = 360;   // chest map: CHEST x CHEST cells over the map square (about 3 m each)
for (let i = 0; i < files.length; i += 20) {
  const part = files.slice(i, i + 20);
  const run = spawnSync(DOTNET, [DLL, ...part.map((p) => p.f)], { encoding: 'utf8', maxBuffer: 1 << 29 });
  if (run.status !== 0) { console.warn('parser failed', (run.stderr || '').slice(0, 300)); continue; }
  const out = run.stdout.split('\n').filter(Boolean).map((l) => JSON.parse(l.replace(/^\uFEFF/, '')));
  for (const res of out) {
    const { s } = part.find((p) => res.file === `${p.s.session}.replay`) || {};
    if (!s || res.error) { console.warn(`parse error ${res.file}: ${res.error}`); continue; }
    finished.push(s.session);
    // every team in the match, not only the ones on the leaderboard (the leaderboard stops at 10,000 teams)
    const byTeam = new Map();
    for (const p of res.players) if (p.x != null) (byTeam.get(p.team) || byTeam.set(p.team, []).get(p.team)).push(p);
    const lb = new Map();
    for (const t of s.teams) for (const a of t.accounts) lb.set(a.toLowerCase(), t);
    for (const ps of byTeam.values()) {
      const t = ps.map((p) => lb.get(p.epic.toLowerCase())).find(Boolean);
      const x = ps.reduce((a, p) => a + p.x, 0) / ps.length, y = ps.reduce((a, p) => a + p.y, 0) / ps.length;
      const u = toUnit(x, y);
      if (!inside(u)) continue;
      if (t) rows.push({ game: t.game, team: t.accounts.map((a) => a.toLowerCase()).join('+'), x: u[0], y: u[1], placement: t.placement || 0,
        points: t.points ?? undefined, elims: t.elims, rank: t.rank || 0, win: !!t.win });
      else {   // a team that is not on the stored leaderboard: no rank, game number unknown (0), points from the replay's own numbers
        noMatch++; synthetic++;
        const place = Math.min(...ps.map((p) => p.placement || 999));
        rows.push({ game: 0, team: ps.map((p) => p.epic.toLowerCase()).sort().join('+'), x: u[0], y: u[1], placement: place === 999 ? 0 : place,
          elims: ps.reduce((a, p) => a + (p.kills || 0), 0), rank: 0, win: place === 1 });
      }
    }
    for (const [x, y] of res.trail || []) {
      const u = toUnit(x, y);
      if (!inside(u)) continue;
      const k = Math.min(BASE - 1, Math.floor(u[1] * BASE)) * BASE + Math.min(BASE - 1, Math.floor(u[0] * BASE));
      cells.set(k, (cells.get(k) || 0) + 1);
    }
    // chests opened in this match (player-death drops are already removed by the landing tool): one count per cell per match
    const seen = new Set();
    for (const [x, y] of res.chests || []) {
      const u = toUnit(x, y);
      if (!inside(u)) continue;
      chestBursts++;
      seen.add(Math.min(CHEST - 1, Math.floor(u[1] * CHEST)) * CHEST + Math.min(CHEST - 1, Math.floor(u[0] * CHEST)));
    }
    for (const k of seen) chestCells.set(k, (chestCells.get(k) || 0) + 1);
  }
}
rmSync(dir, { recursive: true, force: true });
console.log(`landings for ${rows.length} teams from ${finished.length} matches (${failed} downloads failed, ${synthetic} teams were not on the leaderboard); ${chestBursts} chest openings in ${chestCells.size} map cells, in ${((Date.now() - started) / 1000).toFixed(0)}s`);

if (DRY) { console.log(JSON.stringify(rows.slice(0, 3))); process.exit(0); }
const code = (listing.playlist || '').match(/SourSpawn|BlastBerry|DashBerry|PiperBoot|JumpBear/i)?.[0] || '';
const kind = listing.game_type === 'reload' || /reload/i.test(listing.playlist || '') ? 'Reload map' : 'Battle Royale island';
for (let i = 0; i < Math.max(rows.length, 1); i += 4000) {
  const chunk = rows.slice(i, i + 4000);
  const first = i === 0, last = i + 4000 >= rows.length;
  const res = await api('/api/admin/drops', { method: 'POST', body: JSON.stringify({
    window_id: windowId, append: !(first && RESET), reset: first && RESET, coords: 'unit', drops: chunk,
    map: { name: code ? `${kind} (${code})` : kind, credit: 'Map drawn from where players moved in the replays', base: last ? { size: BASE, cells: [...cells] } : undefined },
    chests: last ? { size: CHEST, matches: finished.length, cells: [...chestCells] } : undefined,
    sessions_done: last ? finished : undefined }) });
  console.log('stored', res.stored, 'skipped', res.skipped);
}
