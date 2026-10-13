import re
from datetime import datetime, timezone

from . import config


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def classify(text):
    """Return (family, region) from event id text; family None if not FNCS/Cash Cup."""
    t = text.lower()
    family = next((f for f, kws in config.FAMILIES.items() if any(k in t for k in kws)), None)
    region = next((r for r in config.REGIONS
                   if re.search(rf"(^|[^a-z]){r.lower()}([^a-z]|$)", t)), "ALL")
    return family, region


class Epic:
    def __init__(self, session):
        self.s = session

    def raw_events(self, region="EU"):
        return self.s.get(f"{config.EVENTS}/events/Fortnite/download/{self.s.account_id}",
                          region=region, platform="Windows", teamAccountIds=self.s.account_id)

    def windows(self, region="EU", raw=None):
        """List recognised FNCS/Cash Cup windows."""
        raw = raw or self.raw_events(region)
        out = []
        for ev in raw.get("events", []):
            fam, reg = classify(ev.get("eventId", ""))
            for w in ev.get("eventWindows", []):
                f2, r2 = classify(w.get("eventWindowId", ""))
                fam2 = fam or f2
                if not fam2:
                    continue
                out.append({
                    "window_id": w["eventWindowId"], "event_id": ev["eventId"],
                    "family": fam2, "region": reg if reg != "ALL" else r2,
                    "begin": parse_time(w["beginTime"]), "end": parse_time(w["endTime"]),
                })
        return out

    def page(self, event_id, window_id, page=0):
        return self.s.get(
            f"{config.EVENTS}/leaderboards/Fortnite/{event_id}/{window_id}/{self.s.account_id}",
            page=page, rank=0, appId="Fortnite", showLiveSessions="true")

    def leaderboard(self, event_id, window_id, max_rank=1000):
        """Points and games by rank (index 0 = rank 1), plus entrants estimate."""
        points, games = [], []
        p, total, per = 0, 1, 0
        while p < total and len(points) < max_rank:
            d = self.page(event_id, window_id, p)
            total = d.get("totalPages", 1) or 1
            ents = sorted(d.get("entries", []), key=lambda e: e.get("rank", 0))
            per = per or len(ents)
            for e in ents:
                points.append(float(e.get("pointsEarned", e.get("score", 0)) or 0))
                games.append(len(e.get("sessionHistory") or []))
            p += 1
            if not ents:
                break
        entrants = len(points)
        if total > p and per:  # truncated: estimate from last page
            last = self.page(event_id, window_id, total - 1)
            entrants = (total - 1) * per + len(last.get("entries", []))
        return {"points": points, "games": games, "entrants": entrants, "total_pages": total}

    @staticmethod
    def finished(w, now=None):
        return w["end"] < (now or datetime.now(timezone.utc).timestamp())
