import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import classify, config, rules


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def classify(text):
    """Return (family, region) from event id text; family None if not FNCS/Cash Cup."""
    t = text.lower()
    family = next((f for f, kws in config.FAMILIES.items() if any(k in t for k in kws)), None)
    region = next((r for r in config.REGIONS
                   if re.search(rf"(^|[^a-z]){r.lower()}([^a-z]|$)", t)), "ALL")
    return family, region


def team_mode(text):
    t = text.lower()
    for key, name in (("solo", "solo"), ("duo", "duos"), ("trio", "trios"), ("squad", "squads")):
        if key in t:
            return name
    return "?"


def window_meta(raw, ev, w):
    """Game count, scoring rules, advancement cutoffs and type of one window."""
    tmpl = next((t for t in raw.get("templates", [])
                 if t.get("eventTemplateId") == w.get("eventTemplateId")), {})
    locs = w.get("scoreLocations") or []
    main = next((l for l in locs if l.get("isMainWindowLeaderboard")), locs[0] if locs else {})
    ld = next((l for l in raw.get("leaderboardDefs", [])
               if l.get("leaderboardDefId") == main.get("leaderboardDefId")), {})
    rsid = ld.get("scoringRuleSetId")
    rs = (raw.get("scoringRuleSets", {}).get(rsid)
          or raw.get("scoreLocationScoringRuleSets", {}).get(rsid))
    parsed = rules.parse(rs)
    advance = []
    for table in raw.get("payoutTables", {}).get(ev.get("eventId"), []) or []:
        if table.get("scoringType") != "rank":
            continue
        for rk in table.get("ranks", []):
            tokens = [p["value"] for p in rk.get("payouts", []) if p.get("rewardType") == "token"]
            if tokens:
                advance.append([rk["threshold"], tokens[0]])
    cap = tmpl.get("matchCap")
    playlist = tmpl.get("playlistId") or ""
    mode = team_mode(ev.get("eventId", ""))
    if mode == "?":
        mode = team_mode(playlist)
    gtype = ("reload" if any(k in (playlist + ev.get("eventId", "")).lower()
                             for k in config.RELOAD_WORDS) else "br")
    return {
        "match_cap": cap, "playlist": playlist, "ruleset": rsid,
        "rules": parsed, "advance": sorted(advance),
        "round_type": (w.get("metadata") or {}).get("RoundType"),
        "mode": mode, "game_type": gtype, "lobby": config.LOBBY.get((gtype, mode)),
        "category": classify.category(ev.get("eventId", ""), w["eventWindowId"], playlist, gtype, mode),
        "stage": "open" if re.search(r"round1|heat", w["eventWindowId"], re.I) else "later",
        "format": rules.format_key(cap, parsed) if parsed else None,
    }


class Epic:
    def __init__(self, session):
        self.s = session

    def display_names(self, ids):
        out = {}
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            r = self.s.get(f"{config.ACCOUNT}/public/account", accountId=chunk)
            for a in r:
                out[a["id"]] = a.get("displayName") or a["id"][:8]
        return out

    def raw_events(self, region="EU"):
        return self.s.get(f"{config.EVENTS}/events/Fortnite/download/{self.s.account_id}",
                          region=region, platform="Windows", teamAccountIds=self.s.account_id)

    def windows(self, region="EU", raw=None):
        """List recognised FNCS/Cash Cup windows."""
        raw = raw or self.raw_events(region)
        out = []
        for ev in raw.get("events", []):
            fam, reg = classify(ev.get("eventId", ""))
            ttype = (ev.get("metadata") or {}).get("tournamentType")
            if ttype:  # Epic labels it: trust that over name guesses
                fam = config.TOURNAMENT_TYPES.get(ttype)
            for w in ev.get("eventWindows", []):
                f2, r2 = classify(w.get("eventWindowId", ""))
                fam2 = fam or (f2 if not ttype else None)
                if not fam2:
                    continue
                out.append({
                    "window_id": w["eventWindowId"], "event_id": ev["eventId"],
                    "family": fam2, "region": reg if reg != "ALL" else r2,
                    "begin": parse_time(w["beginTime"]), "end": parse_time(w["endTime"]),
                    "meta": window_meta(raw, ev, w),
                })
        return out

    def page(self, event_id, window_id, page=0):
        return self.s.get(
            f"{config.EVENTS}/leaderboards/Fortnite/{event_id}/{window_id}/{self.s.account_id}",
            page=page, rank=0, appId="Fortnite", showLiveSessions="true")

    def _entries(self, d):
        return sorted(d.get("entries", []), key=lambda e: e.get("rank", 0))

    def leaderboard(self, event_id, window_id, max_rank=1000, deep=True):
        """Top `max_rank` places (points, games, per-game stats, players) plus the points and
        games at the deep threshold ranks (1000, 1500, ... 10000). Pages are fetched in parallel."""
        first = self.page(event_id, window_id, 0)
        total = first.get("totalPages", 1) or 1
        top_pages = list(range(1, min(total, -(-max_rank // 100))))
        deep_pages = {}
        if deep:
            for r in config.DEEP_RANKS:
                pg = (r - 1) // 100
                if pg < total and pg > (max_rank - 1) // 100:
                    deep_pages[pg] = r
        want = sorted(set(top_pages) | set(deep_pages) | {total - 1} - {0})
        pages = {0: first}
        if want:
            def get(x):
                try:
                    return self.page(event_id, window_id, x)
                except Exception:
                    return None   # a missing deep page only loses that threshold
            with ThreadPoolExecutor(max_workers=6) as ex:
                for pg, d in zip(want, ex.map(get, want)):
                    if d is not None:
                        pages[pg] = d
            if any(pg not in pages for pg in top_pages):
                raise RuntimeError("leaderboard page missing")
        points, games, sessions, players = [], [], [], []
        for pg in sorted(k for k in pages if k < -(-max_rank // 100)):
            for e in self._entries(pages[pg]):
                if len(points) >= max_rank:
                    break
                points.append(float(e.get("pointsEarned", e.get("score", 0)) or 0))
                hist = e.get("sessionHistory") or []
                games.append(len(hist))
                sessions.append([[(s.get("trackedStats") or {}).get(k, 0) for k in rules.STATS]
                                 + [round(parse_time(s["endTime"])) if s.get("endTime") else 0]
                                 for s in hist])
                players.append(e.get("teamAccountIds") or [])
        deep_out = {}
        for r in config.DEEP_RANKS:
            pg = (r - 1) // 100
            if r <= len(points):
                deep_out[str(r)] = {"points": points[r - 1], "games": games[r - 1]}
            elif pg in pages:
                es = [e for e in self._entries(pages[pg]) if e.get("rank") == r]
                if es:
                    deep_out[str(r)] = {"points": float(es[0].get("pointsEarned", 0) or 0),
                                        "games": len(es[0].get("sessionHistory") or [])}
        last = self._entries(pages[total - 1]) if total - 1 in pages else []
        entrants = (total - 1) * 100 + len(last) if last else len(points)
        return {"points": points, "games": games, "sessions": sessions, "players": players,
                "entrants": entrants, "total_pages": total, "deep": deep_out,
                "capped": total >= 100}

    def deep_only(self, event_id, window_id):
        """Deep thresholds only (used to backfill finished events)."""
        return self.leaderboard(event_id, window_id, max_rank=100)["deep"]

    @staticmethod
    def finished(w, now=None):
        return w["end"] < (now or datetime.now(timezone.utc).timestamp())
