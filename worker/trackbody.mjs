// Builds the body for POST /api/admin/tracks from the landing tool's TRACKS=1 output (shared by run.mjs and tracks.mjs).
//   trackBody(windowId, s, res, [minX, maxX, minY, maxY], partial)
// partial = the early-game replay run.mjs already downloaded for the landings (first ~4 minutes, nothing extra is fetched): only players
// on the leaderboard are kept (a few per match, so thousands of matches stay small), only samples on the ground / low in the air and
// inside the map, and all times are shifted so the first sample is at 0:00.
const SC = 10000;
const WIDE = [-800, 10800];   // a little beyond the map edge, like the landings

export function trackBody(windowId, s, res, [minX, maxX, minY, maxY], partial = false) {
  const u = (x, y) => [Math.round((y - minY) / (maxY - minY) * SC), Math.round((maxX - x) / (maxX - minX) * SC)];   // same frame as the landings
  const rad = (r) => Math.round(r / (maxY - minY) * SC);
  const lb = new Set();
  for (const t of s.teams) for (const a of t.accounts) lb.add(String(a).toLowerCase());
  let list = res.tracks || [];
  if (partial) list = list.filter((p) => lb.has(String(p.epic).toLowerCase()));
  let tracks = list.map((p) => ({
    epic: p.epic, team: p.team, placement: p.placement, kills: p.kills,
    death: p.death ? [...u(p.death[0], p.death[1]), p.death[2]] : null,
    p: p.p.map(([t, x, y, z]) => [t, ...u(x, y), z])
      .filter((q) => !partial || (q[3] <= 400 && q[1] > WIDE[0] && q[1] < WIDE[1] && q[2] > WIDE[0] && q[2] < WIDE[1])),
  })).filter((p) => p.p.length >= 2);
  if (!tracks.length) return null;
  let shift = 0, duration = res.duration;
  if (partial) {
    shift = Math.max(0, Math.min(...tracks.map((p) => p.p[0][0])) - 4);
    for (const p of tracks) { for (const q of p.p) q[0] -= shift; if (p.death) p.death[2] -= shift; }
    duration = Math.max(...tracks.map((p) => p.p[p.p.length - 1][0]));
  }
  return {
    session: s.session, duration,
    storm: (res.storm || []).filter((z) => z[4] > 0).map(([t, lr, lx, ly, nr, nx, ny, st, fi]) => [t - shift, rad(lr), ...u(lx, ly), rad(nr), ...u(nx, ny), st - shift, fi - shift]),
    teams: s.teams.map((t) => ({ accounts: t.accounts, rank: t.rank, game: t.game, placement: t.placement, points: t.points, elims: t.elims })),
    tracks,
  };
}
