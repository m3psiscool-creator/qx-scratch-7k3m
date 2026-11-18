// Reads FULL replays of a tournament window and stores where every player moved (the rotation viewer).
//   node tracks.mjs <window_id> [--limit 10] [--top 1000] [--dry]
// env: ADMIN_KEY (required), SITE, LANDINGS_DLL, DOTNET, MAP_BOUNDS (same as run.mjs)
// Picks the matches with the most teams that finished in the top N (those are the ones that show how qualifiers rotate).
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { buildReplay } from './replay.mjs';
import { trackBody } from './trackbody.mjs';

const SITE = process.env.SITE || 'https://fn-game-analyzer.vercel.app';
const KEY = process.env.ADMIN_KEY;
const DLL = process.env.LANDINGS_DLL || join(import.meta.dirname, 'landings', 'out', 'LandingsReplayReader.dll');
const DOTNET = process.env.DOTNET || 'dotnet';
let [minX, maxX, minY, maxY] = [-55000, 55000, -55000, 55000];
const args = process.argv.slice(2);
const windowId = args[0];
const opt = (name, d) => { const i = args.indexOf(`--${name}`); return i >= 0 ? Number(args[i + 1]) : d; };
const LIMIT = opt('limit', 10), TOP = opt('top', 1000), DRY = args.includes('--dry');
if (!windowId || !KEY) { console.error('usage: ADMIN_KEY=... node tracks.mjs <window_id> [--limit N] [--top N] [--dry]'); process.exit(2); }
const api = async (path, init = {}) => {
  const r = await fetch(SITE + path, { ...init, headers: { 'x-admin-key': KEY, 'content-type': 'application/json', ...(init.headers || {}) } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error(`${path}: ${j.error || r.status}`);
  return j;
};

const listing = await api(`/api/admin/matches?window=${encodeURIComponent(windowId)}`);
if (process.env.MAP_BOUNDS) [minX, maxX, minY, maxY] = process.env.MAP_BOUNDS.split(',').map(Number);
else if (listing.game_type === 'br') [minX, maxX, minY, maxY] = [-131072, 131072, -131072, 131072];
const tdone = new Set(listing.tdone || []);
const pending = listing.sessions.filter((s) => !tdone.has(s.session))
  .sort((a, b) => b.teams.filter((t) => t.rank <= TOP).length - a.teams.filter((t) => t.rank <= TOP).length)
  .slice(0, LIMIT);
console.log(`${windowId}: ${listing.sessions.length} matches, ${tdone.size} with tracks, reading ${pending.length}`);
if (!pending.length) process.exit(0);

const dir = mkdtempSync(join(tmpdir(), 'tracks-'));
let ok = 0, failed = 0;
for (const s of pending) {
  try {
    const { buffer } = await buildReplay(s.session, KEY, { maxMs: 0 });
    const f = join(dir, `${s.session}.replay`);
    writeFileSync(f, buffer);
    const run = spawnSync(DOTNET, [DLL, f], { encoding: 'utf8', maxBuffer: 1 << 29, env: { ...process.env, TRACKS: '1' } });
    rmSync(f, { force: true });
    if (run.status !== 0) { console.warn('parser failed', (run.stderr || '').slice(0, 200)); failed++; continue; }
    const res = JSON.parse(run.stdout.split('\n').filter(Boolean)[0].replace(/^﻿/, ''));
    if (res.error || !res.tracks || !res.tracks.length) { console.warn(`skip ${s.session}: ${res.error || 'no tracks'}`); failed++; continue; }
    const tb = trackBody(windowId, s, res, [minX, maxX, minY, maxY], false);
    if (!tb) { console.warn(`skip ${s.session}: no usable tracks`); failed++; continue; }
    const body = { window_id: windowId, ...tb };
    if (DRY) { console.log(`${s.session}: ${body.tracks.length} players, ${body.duration}s, ${body.storm.length} storm phases, ${JSON.stringify(body).length} bytes`); ok++; continue; }
    const r = await api('/api/admin/tracks', { method: 'POST', body: JSON.stringify(body) });
    ok++;
    console.log(`stored ${s.session}: ${r.players} players, ${r.bytes} bytes compressed`);
  } catch (e) { failed++; console.warn(`skip ${s.session}: ${e.message}`); }
}
rmSync(dir, { recursive: true, force: true });
console.log(`tracks: ${ok} matches stored, ${failed} failed`);
