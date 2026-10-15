# FN Game Analyzer

Hosted site that predicts the points needed for any rank (1-10,000) in Fortnite FNCS, Cash Cup and Skin Cup (ShopCup) windows, live and before they start. Production: https://fn-game-analyzer.vercel.app (Vercel, project `fn-game-analyzer`, team james-projects-996f2671, Hobby plan). Repo: github.com/m3psiscool-creator/fn-game-analyzer.

## User preferences
- Short answers; list every step; critique own answer; ask for missing info rather than guess.
- User is on Windows (PowerShell). Use the full python path (`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`) in non-fresh shells.
- User does NOT want to run commands on their computer: everything runs on Vercel.

## Architecture
- `index.py` FastAPI entrypoint. Serves `web/` (index.html, style.css, lib.js = helpers + chart theme, strategy.js = Strategy tab, app.js = pages + router; hash-routed SPA, Chart.js from cdnjs) and `/api/*`. New static files need a route in index.py.
- `fngameanalyzer/`: `config` (regions, lobby sizes, DEEP_RANKS), `auth` (rolling Epic refresh token in DB, lock), `epic_api` (events + leaderboards, parallel pages, deep thresholds), `classify` (event class), `rules` (scoring rules, rescoring), `storage` (sqlite local) / `storage_pg` (Neon Postgres, chosen by POSTGRES_URL), `collector` (tick), `model`/`sim` (prediction), `service`/`insights` (API logic), `strategy` (scoring values, finisher profiles, pace curves, safety margin, rank ladder; feeds the Strategy tab via /api/scoring, /profile, /pace, /safety, /ladder).
- Tick: `/api/tick` (header `x-admin-key` or Vercel cron bearer). cron-job.org calls it every minute; one pass takes <25s (Hobby cron is daily only). Each pass: sync event list (every 10 min, all regions), snapshot live windows (until end + 25 min, because games started before the end still count), store finals (backfill newest first), deep thresholds backfill, stored predictions, player-name backfill.
- Storage per window: top-1000 points/games/per-game sessions (placement, elims, win, end time)/players, plus points at ranks 1000,1500..10000 (`deep`). Snapshots also write compact `series`. Full snapshots of finished windows are pruned after 3 days.

## Model
- Events are classified (`classify.py`): reload|br, zb, solo|duo|trio|squads, mobile. History is only used within the same class (checkbox `approx` allows nearby classes explicitly), and the same format (game count + scoring). Same-region events come first and carry the most weight; other regions of the same gamemode and format are added only when the region has fewer than `model.MIN_SAME_REGION` (4) previous events (`model.comparable`, `strategy.peers`, strategy `_refs`).
- Live: player-by-player simulation (`sim.py`) using comparable players at the same moment in same-class past events (games played, points/game, pace scaling), with back-test bias correction. Ranks >700 scale from rank 500; ranks never predicted below current.
- No history for a class = explicit "no history" message.

## Operations
- Secrets live in Vercel env (ADMIN_KEY, CRON_SECRET) and the Neon DB; Epic login is done on the Status page. Re-login only if the collector is idle >8h.
- Deploy: `npx vercel deploy --prod --scope james-projects-996f2671` (CLI is logged in as m3psisgood-2280), also pushes to GitHub.
- Known limits: Epic endpoints are unofficial; only the top 1000 players are stored per event (ranks 1001-10000 are thresholds only); sessionHistory is capped (11 games on some events).
