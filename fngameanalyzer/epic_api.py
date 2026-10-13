import re
from datetime import datetime, timezone

from . import config, rules


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

    def leaderboard(self, event_id, window_id, max_rank=1000):
        """Points, games and per-game [placement, elims, win] by rank (index 0 = rank 1)."""
        points, games, sessions, players = [], [], [], []
        p, total, per = 0, 1, 0
        while p < total and len(points) < max_rank:
            d = self.page(event_id, window_id, p)
            total = d.get("totalPages", 1) or 1
            ents = sorted(d.get("entries", []), key=lambda e: e.get("rank", 0))
            per = per or len(ents)
            for e in ents:
                points.append(float(e.get("pointsEarned", e.get("score", 0)) or 0))
                hist = e.get("sessionHistory") or []
                games.append(len(hist))
                sessions.append([[(s.get("trackedStats") or {}).get(k, 0) for k in rules.STATS]
                                 + [round(parse_time(s["endTime"])) if s.get("endTime") else 0]
                                 for s in hist])
                players.append(e.get("teamAccountIds") or [])
            p += 1
            if not ents:
                break
        entrants = len(points)
        if total > p and per:  # truncated: estimate from last page
            last = self.page(event_id, window_id, total - 1)
            entrants = (total - 1) * per + len(last.get("entries", []))
        return {"points": points, "games": games, "sessions": sessions, "players": players,
                "entrants": entrants, "total_pages": total}

    @staticmethod
    def finished(w, now=None):
        return w["end"] < (now or datetime.now(timezone.utc).timestamp())
