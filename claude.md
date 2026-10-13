# FN Game Analyzer

Predicts the points needed for any rank (top X) in Fortnite FNCS and Cash Cup event windows. The user opens a local web page, picks a window, types X, and gets Low / Most likely / Safe (~95%) numbers. Works before an event (from past results) and live (from the current leaderboard).

## User preferences
- Keep answers short. Give step-by-step instructions with every step listed.
- Critique your own answer before giving it.
- Ask the user for missing information instead of guessing.
- The user is on Windows (PowerShell). Use `python` or `py`, and Windows-safe commands.

## Status (read this first)
All code was written in a cloud sandbox that could NOT reach Epic's servers. Only the model is tested (synthetic data, `python -m unittest discover tests`). The Epic login, API client and response parsing have never run against real Epic data. Parser field names are best guesses from community docs: `pointsEarned`, `sessionHistory`, `totalPages`, `entries`, `eventWindows`.

**Next step on the user's PC:** run `login`, then `probe`, and fix any parsing mismatches using the saved raw JSON in `~/.fngameanalyzer/probe_events.json` and `probe_leaderboard.json`. Then `collect`, `serve`.

## Commands
- `pip install -r requirements.txt`
- `python -m fngameanalyzer login` — one-time. User opens the printed link while logged in to Epic and pastes the `authorizationCode`. The user must do this step; do not try to automate it.
- `python -m fngameanalyzer probe` — dumps raw Epic JSON and reports how many FNCS/Cash Cup windows were recognised.
- `python -m fngameanalyzer collect [--regions ...] [--max-rank N]` — stores final leaderboards of finished windows.
- `python -m fngameanalyzer watch [--interval S]` — polls live windows and stores snapshots (needed to train the live predictor).
- `python -m fngameanalyzer serve [--port 8765]` — web UI at http://localhost:8765
- `python -m fngameanalyzer predict <window_id> <top> [--entrants N]`
- Tests: `python -m unittest discover tests`

## Layout
- `fngameanalyzer/config.py` — paths (`~/.fngameanalyzer/`, override with `FNGA_HOME`), Epic URLs, public auth client, event family keywords.
- `auth.py` — authorization code -> device auth saved to `auth.json`; `Session` refreshes the bearer token.
- `epic_api.py` — events service client. `classify()` decides FNCS/CASHCUP and region from the event id text. `leaderboard()` returns points, games played (length of `sessionHistory`), entrants, total pages.
- `storage.py` — SQLite: `windows` and `snapshots` (points/games stored as JSON arrays by rank).
- `model.py` — prediction (see below).
- `web.py` — stdlib HTTP server and single-page UI.
- `__main__.py` — CLI.

## Model (model.py)
Works in log1p(points). Combines two estimates by inverse variance:
- **Prior:** recency-weighted (decay 0.7) points at rank X from comparable finished windows (same family; same region if at least 3 exist). Entrant adjustment scales the looked-up rank by (past entrants / target entrants)^beta; beta is chosen by leave-one-out over a grid and needs 5+ windows, else 0.
- **Live:** current points at rank X scaled to the end of the window. Progress = games played near rank X when available, else elapsed time. Growth factor learned from past snapshots at the same progress (needs 3+, from `watch`); otherwise naive extrapolation with a wide band.
- Output: `low`/`high` is a 90% interval, `safe` is the upper end (~95% one-sided), `likely` is the median.

## Known limits and risks
- Epic's internal endpoints are unofficial and may change or block access. Use only the user's own account and keep request rates low.
- Past events only have final results, so live growth curves must be learned from `watch` snapshots.
- Event matching depends on event id text; real ids may not match `FAMILIES` keywords in `config.py`.
- Games-played progress depends on Epic returning `sessionHistory`.
- Never commit `auth.json` or the data folder (both are gitignored).

## Git
Develop on branch `claude/dazzling-davinci-t4bu0c`. Do not open a pull request unless the user asks.