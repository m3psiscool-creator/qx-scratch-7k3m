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
const DLL = process.env.LANDINGS_DLL || join(import.meta.dirname, 'landings', 'out', 'LandingsReplayReader.dll');
const DOTNET = process.env.DOTNET || 'dotnet';
let [minX, maxX, minY, maxY] = [-55000, 55000, -55000, 55000];   // Reload maps; the big Battle Royale island is set once the window is known
const BASE = 128;

const args = process.argv.slice(2);
const windowId = args[0];
const opt = (name, d) => { const i = args.indexOf(`--${name}`); return i >= 0 ? Number(args[i + 1]) : d; };
const PURGE = (() => { const i = args.indexOf('--purge-from'); return i >= 0 ? args[i + 1] : null; })();   // map key whose chest atlas holds these matches by mistake
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
const WIDE = [-0.7, 1.7];   // the islands are bigger than the 0-1 square: keep everything, the site crops to the map
const in01 = ([u, v]) => u >= 0 && u <= 1 && v >= 0 && v <= 1;
const inside = ([u, v]) => u >= WIDE[0] && u <= WIDE[1] && v >= WIDE[0] && v <= WIDE[1];

const listing = await api(`/api/admin/matches?window=${encodeURIComponent(windowId)}`);
if (process.env.MAP_BOUNDS) [minX, maxX, minY, maxY] = process.env.MAP_BOUNDS.split(',').map(Number);
else if (listing.game_type === 'br') [minX, maxX, minY, maxY] = [-131072, 131072, -131072, 131072];   // landings reach about +-112,000
const done = new Set(RESET ? [] : listing.done);
const cdone = new Set(listing.cdone || []);   // matches whose containers (chests, ammo boxes...) were already read   // --reset starts this window over: rows, finished matches and chest counts
// A tournament has thousands of matches. Alternate between the matches with the most qualifying teams (the ones that
// answer "where did the qualifiers land") and a random draw (so "everyone else" is not skewed towards qualifiers).
const TOP = opt('top', 1000);
const pending = listing.sessions.filter((s) => PURGE ? (done.has(s.session) && !cdone.has(s.session)) : (!done.has(s.session) || !cdone.has(s.session)));   // --purge-from: only matches already loaded for landings, re-read for their containers
const byQual = [...pending].sort((a, b) => b.teams.filter((t) => t.rank <= TOP).length - a.teams.filter((t) => t.rank <= TOP).length);
const shuffled = [...pending].sort(() => Math.random() - 0.5);
const todo = [], seen = new Set();
for (let i = 0; todo.length < Math.min(LIMIT, pending.length); i++) {
  for (const s of [byQual[i], shuffled[i]]) if (s && !seen.has(s.session) && todo.length < LIMIT) { seen.add(s.session); todo.push(s); }
}
const started = Date.now();
console.log(`${windowId}: ${listing.sessions.length} matches, ${done.size} done, ${cdone.size} with containers, processing ${todo.length}`);
if (!todo.length) process.exit(0);

const CHUNK = opt('chunk', 150);   // a whole tournament can be 20,000 matches: download, parse, post and delete the files chunk by chunk (disk and memory)
let totalFailed = 0, totalMatches = 0;
for (let c = 0; c < todo.length; c += CHUNK) {
const part0 = todo.slice(c, c + CHUNK), firstChunk = c === 0, lastChunk = c + CHUNK >= todo.length;
const dir = mkdtempSync(join(tmpdir(), 'replays-'));
const files = [];
let next = 0, failed = 0;
async function worker() {
  while (next < part0.length) {
    const s = part0[next++];
    try {
      const { buffer } = await buildReplay(s.session, KEY, { maxMs: MAXMS });
      const f = join(dir, `${s.session}.replay`);
      writeFileSync(f, buffer);
      files.push({ s, f });
    } catch (e) { failed++; console.warn(`skip ${s.session}: ${e.message}`); }
  }
}
await Promise.all([worker(), worker(), worker()]);

const rows = [], cells = new Map(), chestCells = new Map(), finished = [], ctnBatch = [], purgeBatch = [];
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
    // containers: every chest the players searched, at the searching player's position (stored frame u, v)
    if (!cdone.has(s.session)) purgeBatch.push({ session: s.session, items: (res.containers || []).map(([n, x, y]) => [n, ...toUnit(x, y)]).filter(([, u, v]) => inside([u, v])) });
    if (!cdone.has(s.session)) ctnBatch.push({ session: s.session, items: (res.containers || []).map(([n, x, y]) => [n, ...toUnit(x, y)]).filter(([, u, v]) => inside([u, v])) });
    if (done.has(s.session)) continue;   // landings of this match are already loaded
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
      if (!in01(u)) continue;
      const k = Math.min(BASE - 1, Math.floor(u[1] * BASE)) * BASE + Math.min(BASE - 1, Math.floor(u[0] * BASE));
      cells.set(k, (cells.get(k) || 0) + 1);
    }
    // chests opened in this match (player-death drops are already removed by the landing tool): one count per cell per match
    const seen = new Set();
    for (const [x, y] of res.chests || []) {
      const u = toUnit(x, y);
      if (!in01(u)) continue;
      chestBursts++;
      seen.add(Math.min(CHEST - 1, Math.floor(u[1] * CHEST)) * CHEST + Math.min(CHEST - 1, Math.floor(u[0] * CHEST)));
    }
    for (const k of seen) chestCells.set(k, (chestCells.get(k) || 0) + 1);
  }
}
rmSync(dir, { recursive: true, force: true });
if (!DRY && PURGE) for (let i = 0; i < purgeBatch.length; i += 8) {   // first take the matches out of the wrong map's atlas
  const res = await api('/api/admin/containers_remove', { method: 'POST', body: JSON.stringify({ map_key: PURGE, matches: purgeBatch.slice(i, i + 8) }) });
  if (i + 8 >= purgeBatch.length) console.log(`removed from ${PURGE}: ${purgeBatch.length} matches; it now holds ${res.matches} matches and ${res.containers} containers`);
}
if (!DRY) for (let i = 0; i < ctnBatch.length; i += 8) {
  const res = await api('/api/admin/containers', { method: 'POST', body: JSON.stringify({ window_id: windowId, matches: ctnBatch.slice(i, i + 8) }) });
  if (i + 8 >= ctnBatch.length) console.log(`containers: ${ctnBatch.length} matches added, ${res.containers} distinct containers on this map so far (${res.matches} matches)`);
}
console.log(`landings for ${rows.length} teams from ${finished.length} matches (${failed} downloads failed, ${synthetic} teams were not on the leaderboard); ${chestBursts} chest openings in ${chestCells.size} map cells, in ${((Date.now() - started) / 1000).toFixed(0)}s`);

if (DRY) {   // (dry run: first chunk only)
  const w = (v, lo, hi) => (lo + v * (hi - lo)).toFixed(0);
  const xs = rows.map((r) => r.x), ys = rows.map((r) => r.y);
  console.log('world extent of landings: east (Y)', w(Math.min(...xs), minY, maxY), 'to', w(Math.max(...xs), minY, maxY), ', north (X)', w(1 - Math.max(...ys), minX, maxX), 'to', w(1 - Math.min(...ys), minX, maxX));
  console.log(JSON.stringify(rows.slice(0, 2)));
  process.exit(0);
}
if (!rows.length && !finished.length) continue;   // nothing new for the landing tables (only containers were read)
const code = (listing.playlist || '').match(/SourSpawn|BlastBerry|DashBerry|PiperBoot|JumpBear/i)?.[0] || '';
const kind = listing.game_type === 'reload' || /reload/i.test(listing.playlist || '') ? 'Reload map' : 'Battle Royale island';
for (let i = 0; i < Math.max(rows.length, 1); i += 4000) {
  const chunk = rows.slice(i, i + 4000);
  const first = i === 0, last = i + 4000 >= rows.length;   // first/last piece of THIS chunk
  const res = await api('/api/admin/drops', { method: 'POST', body: JSON.stringify({
    window_id: windowId, append: !(first && firstChunk && RESET), reset: first && firstChunk && RESET, coords: 'unit', drops: chunk,
    map: { name: code ? `${kind} (${code})` : kind, credit: 'Map drawn from where players moved in the replays', base: last ? { size: BASE, cells: [...cells] } : undefined },
    chests: last ? { size: CHEST, matches: finished.length, cells: [...chestCells] } : undefined,
    sessions_done: last ? finished : undefined }) });
  console.log('stored', res.stored, 'skipped', res.skipped);
}
  totalFailed += failed; totalMatches += finished.length;
  console.log(`chunk ${Math.floor(c / CHUNK) + 1}/${Math.ceil(todo.length / CHUNK)} done (${totalMatches} matches loaded, ${totalFailed} failed, ${((Date.now() - started) / 60000).toFixed(1)} min)`);
  if (process.env.STOP_AFTER_SECONDS && (Date.now() - started) / 1000 > Number(process.env.STOP_AFTER_SECONDS)) { console.log('time budget reached, the rest follows on the next run'); break; }
}
