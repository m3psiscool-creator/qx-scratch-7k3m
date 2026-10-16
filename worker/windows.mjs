// Prints the tournament windows the scheduled worker should work on next, one id per line.
// Replays are only kept for about 1-2 weeks, so: finished windows from the last 20 days, those with the fewest landings first.
//   node windows.mjs [count=4] [cap=3000]
const SITE = process.env.SITE || 'https://fn-game-analyzer.vercel.app';
const count = Number(process.argv[2] || 4), cap = Number(process.argv[3] || 3000);
const j = async (p) => (await fetch(SITE + p)).json();
const [wins, have] = await Promise.all([j('/api/windows'), j('/api/drops/events')]);
const now = Date.now() / 1000;
const list = wins
  .filter((w) => w.final && w.end > now - 20 * 86400 && w.end < now - 1800 && ((have[w.window_id] || {}).landings || 0) < cap)
  .sort((a, b) => ((have[a.window_id] || {}).landings || 0) - ((have[b.window_id] || {}).landings || 0) || b.end - a.end)
  .slice(0, count);
for (const w of list) console.log(w.window_id);
