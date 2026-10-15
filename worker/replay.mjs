// Downloads one tournament match replay from Epic's storage (links come from the site: /api/admin/replay) and
// assembles the chunks into a normal .replay file that fortnite-replay-parser can read.
// Usage: node replay.mjs <sessionId> [outFile]     env: SITE (default production), ADMIN_KEY

import { writeFileSync } from 'node:fs';

const SITE = process.env.SITE || 'https://fn-game-analyzer.vercel.app';

const w32 = (n) => { const b = Buffer.alloc(4); b.writeInt32LE(n); return b; };
const wU32 = (n) => { const b = Buffer.alloc(4); b.writeUInt32LE(n >>> 0); return b; };
const wStr = (s) => {
  s = s || '';
  if (!s) return w32(0);
  return Buffer.concat([w32(s.length + 1), Buffer.from(s, 'utf8'), Buffer.from([0])]);
};

export async function getLinks(session, key = process.env.ADMIN_KEY, maxMs = 0) {
  const r = await fetch(`${SITE}/api/admin/replay?session=${session}${maxMs ? `&max_ms=${maxMs}` : ''}`, { headers: { 'x-admin-key': key } });
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

async function pool(items, size, fn) {
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: size }, async () => {
    while (i < items.length) { const k = i++; out[k] = await fn(items[k], k); }
  }));
  return out;
}

async function fetchBuf(url, tries = 4) {
  for (let t = 0; t < tries; t++) {
    const r = await fetch(url);
    if (r.ok) return Buffer.from(await r.arrayBuffer());
    if (r.status !== 429 && r.status < 500) throw new Error(`download ${r.status}`);
    await new Promise((res) => setTimeout(res, 1000 * (t + 1)));
  }
  throw new Error('download failed');
}

// chunk framing as the game writes it: type (0 header, 1 data, 2 checkpoint, 3 event), size, payload
function chunk(type, payload) { return Buffer.concat([w32(type), w32(payload.length), payload]); }

// opts.maxMs: only the first part of the match (landings happen in the first minutes): data chunks that start before
// maxMs and nothing else, which is a small fraction of the download.
export async function buildReplay(session, key, opts = {}) {
  const { meta: full, files } = await getLinks(session, key, opts.maxMs);
  const meta = opts.maxMs
    ? { ...full, DataChunks: (full.DataChunks || []).filter((c) => c.Time1 < opts.maxMs), Checkpoints: [], Events: [], LengthInMS: Math.min(full.LengthInMS, opts.maxMs) }
    : full;
  const get = (name) => {
    const f = files[name];
    if (!f || !f.url) throw new Error(`no link for ${name}`);
    return fetchBuf(f.url);
  };
  const header = await get('header.bin');
  const data = await pool(meta.DataChunks || [], 8, async (c) => ({ c, b: await get(`${c.Id}.bin`) }));
  const cps = await pool(meta.Checkpoints || [], 8, async (c) => ({ c, b: await get(`${c.Id}.bin`) }));
  const evs = await pool(meta.Events || [], 16, async (c) => ({ c, b: await get(`${c.Id}.bin`) }));

  const ticks = BigInt(new Date(meta.Timestamp).getTime()) * 10000n + 621355968000000000n;
  const ts = Buffer.alloc(8); ts.writeBigUInt64LE(ticks);
  const info = Buffer.concat([
    wU32(0x1CA2E27F), wU32(6),                    // magic, file version 6 (no custom versions)
    wU32(meta.LengthInMS), wU32(meta.NetworkVersion), wU32(meta.Changelist),
    wStr(meta.FriendlyName), w32(meta.bIsLive ? 1 : 0), ts, w32(meta.bCompressed ? 1 : 0),
    w32(0), w32(0),                               // not encrypted, empty key
  ]);
  const parts = [info, chunk(0, header)];
  for (const { c, b } of data.sort((a, z) => a.c.Time1 - z.c.Time1))
    parts.push(chunk(1, Buffer.concat([wU32(c.Time1), wU32(c.Time2), wU32(b.length), wU32(c.SizeInBytes ?? b.length), b])));
  for (const { c, b } of cps)
    parts.push(chunk(2, Buffer.concat([wStr(c.Id), wStr(c.Group), wStr(c.Metadata), wU32(c.Time1), wU32(c.Time2), wU32(b.length), b])));
  for (const { c, b } of evs)
    parts.push(chunk(3, Buffer.concat([wStr(c.Id), wStr(c.Group), wStr(c.Metadata), wU32(c.Time1), wU32(c.Time2), wU32(b.length), b])));
  return { buffer: Buffer.concat(parts), meta, events: evs, checkpoints: cps };
}

// Only the event files (positions, eliminations, zone, summary): much smaller than the whole replay.
export async function getEvents(session, key) {
  const { meta, files } = await getLinks(session, key);
  const evs = await pool(meta.Events || [], 16, async (c) => {
    const f = files[`${c.Id}.bin`];
    return { c, b: f && f.url ? await fetchBuf(f.url) : Buffer.alloc(0) };
  });
  return { meta, events: evs };
}

if (process.argv[1] && process.argv[1].endsWith('replay.mjs')) {
  const [session, out = `${process.argv[2]}.replay`, maxMs = '0'] = process.argv.slice(2);
  const { buffer, meta } = await buildReplay(session, undefined, { maxMs: Number(maxMs) });
  writeFileSync(out, buffer);
  console.log(`wrote ${out}: ${buffer.length} bytes, ${meta.DataChunks?.length} data chunks, ${meta.Checkpoints?.length} checkpoints, ${meta.Events?.length} events`);
}
