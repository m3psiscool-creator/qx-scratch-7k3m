import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import classify as eventclass, config, rules


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



ITEM_TYPES = {"AthenaCharacter": "Outfit", "AthenaPickaxe": "Pickaxe", "AthenaBackpack": "Back Bling",
              "AthenaItemWrap": "Wrap", "AthenaGlider": "Glider", "AthenaMusicPack": "Music",
              "CosmeticVariantToken": "Style", "SparksSong": "Jam Track"}
INTERNAL_TOKEN = re.compile(r"deny|regionlock|lock|ban", re.I)


def _minutes(iso):
    """'PT32M' / 'PT1H' / 'PT1H30M' -> minutes."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso or "")
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0) if m else None


def _words(s):
    s = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=\D)(?=\d)", " ", s.replace("_", " "))
    return s.strip()


def _item(p):
    t, v, q = p.get("rewardType"), str(p.get("value", "")), p.get("quantity", 1)
    if t == "ecomm":
        return {"type": "cash", "label": f"${q:,} {v}".replace(f"${q:,} USD", f"${q:,}"), "usd": q if v == "USD" else 0}
    if t == "game":
        kind, _, ident = v.partition(":")
        name = re.sub(r"^(character|pickaxe|backpack|wrap|glider|spray|emoji|emote|toy|music|loadingscreen|bid|eid)_", "", ident, flags=re.I)
        label = ITEM_TYPES.get(kind, "Emote")
        if kind == "AthenaDance":
            label = "Spray" if ident.lower().startswith("spray") else "Emoticon" if ident.lower().startswith("emoji") else "Emote"
        return {"type": "item", "kind": label, "label": f"{label}: {name.replace('_', ' ').title()}", "id": v}
    if t == "token":
        if INTERNAL_TOKEN.search(v):
            return None
        name = re.sub(r"^S\d+_", "", v)
        name = re.sub(r"_(NAC|NAW|EU|BR|ASIA|ME|OCE)$", "", name)
        return {"type": "advance", "label": "Advance: " + _words(name)}
    return {"type": "other", "label": f"{t}: {v}"}


def reward_info(raw, ev, w, ld):
    """Normalised rewards of a window and when they are paid out (epoch seconds)."""
    cfg = (ld or {}).get("payoutsConfig") or {}
    fmt = cfg.get("payoutTableIdFormat") or ""
    cands = []
    if fmt:
        cands.append(fmt.replace("${windowId}", w["eventWindowId"]).replace("${eventId}", ev["eventId"])
                     .replace("${round}", str(w.get("round", ""))))
    cands += [w["eventWindowId"], ev["eventId"]]
    table = next((raw.get("payoutTables", {}).get(c) for c in cands if raw.get("payoutTables", {}).get(c)), None)
    tiers = []
    for t in table or []:
        kind, prev = t.get("scoringType"), 0
        for r in sorted(t.get("ranks", []), key=lambda x: x["threshold"]):
            items = [i for i in (_item(p) for p in r.get("payouts", [])) if i]
            if items:
                tiers.append({"kind": kind, "from": prev + 1 if kind == "rank" else None, "upto": r["threshold"], "items": items})
            prev = r["threshold"]
    cash = sum(i["usd"] * (t["upto"] - t["from"] + 1) for t in tiers if t["kind"] == "rank"
               for i in t["items"] if i["type"] == "cash")
    end = parse_time(w["endTime"])
    date = cfg.get("payoutDate") or ""
    m = re.fullmatch(r"(windowEnd|eventEnd)\+(PT.+)", date)
    mins = _minutes(m.group(2)) if m else None
    base = parse_time(ev["endTime"]) if m and m.group(1) == "eventEnd" else end
    if mins is None:
        mins = w.get("payoutDelay")
    payout_at = base + mins * 60 if mins is not None else None
    advance = sorted([t["upto"], next(i["label"] for i in t["items"] if i["type"] == "advance")]
                     for t in tiers if t["kind"] == "rank" and any(i["type"] == "advance" for i in t["items"]))
    flags = {"item": any(i["type"] == "item" for t in tiers for i in t["items"]),
             "advance": any(i["type"] == "advance" for t in tiers for i in t["items"])}
    return {"tiers": tiers, "cash_total": cash, "payout_at": payout_at, "flags": flags,
            "payout_rule": date or (f"window end + {mins} min" if mins is not None else None)}, advance


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
    rewards, advance = reward_info(raw, ev, w, ld)
    cap = tmpl.get("matchCap")
    playlist = tmpl.get("playlistId") or ""
    mode = team_mode(ev.get("eventId", ""))
    if mode == "?":
        mode = team_mode(playlist)
    gtype = ("reload" if any(k in (playlist + ev.get("eventId", "")).lower()
                             for k in config.RELOAD_WORDS) else "br")
    return {
        "match_cap": cap, "playlist": playlist, "ruleset": rsid,
        "rules": parsed, "advance": advance, "rewards": rewards,
        "goal": eventclass.goal_of({"rewards": rewards}),
        "round_type": (w.get("metadata") or {}).get("RoundType"),
        "mode": mode, "game_type": gtype, "lobby": config.LOBBY.get((gtype, mode)),
        "category": eventclass.category(ev.get("eventId", ""), w["eventWindowId"], playlist, gtype, mode),
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

    def lookup(self, name):
        """Epic display name -> account id (exact name; the lookup works for any account)."""
        import urllib.parse
        r = self.s.get(f"{config.ACCOUNT}/public/account/displayName/{urllib.parse.quote(name, safe='')}")
        return {"id": r["id"], "name": r.get("displayName") or name}

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
            if ttype:  # Trust a known Epic type; fall back to the event ID for new/custom types.
                fam = config.TOURNAMENT_TYPES.get(ttype) or fam
            for w in ev.get("eventWindows", []):
                f2, r2 = classify(w.get("eventWindowId", ""))
                fam2 = fam or f2
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

    def find_entry(self, event_id, window_id, account_id, chunk=12):
        """One player's leaderboard entry (points, rank, every game), found by reading the board page by page.
        Epic only lets an account read its own history, but the public board lists every entry (top 10,000)."""
        def scan(d):
            return next((e for e in (d or {}).get("entries", []) if account_id in (e.get("teamAccountIds") or [])), None)

        def get(pg):
            try:
                return self.page(event_id, window_id, pg)
            except Exception:
                return None
        first = self.page(event_id, window_id, 0)
        total = first.get("totalPages", 1) or 1
        hit = scan(first)
        if hit:
            return hit, total
        pages = list(range(1, total))
        with ThreadPoolExecutor(max_workers=8) as ex:    # best ranks first, so a strong player is found in the first batch
            for i in range(0, len(pages), chunk):
                for d in ex.map(get, pages[i:i + chunk]):
                    hit = scan(d)
                    if hit:
                        return hit, total
        return None, total

    def deep_only(self, event_id, window_id):
        """Deep thresholds only (used to backfill finished events)."""
        return self.leaderboard(event_id, window_id, max_rank=100)["deep"]

    @staticmethod
    def finished(w, now=None):
        return w["end"] < (now or datetime.now(timezone.utc).timestamp())
