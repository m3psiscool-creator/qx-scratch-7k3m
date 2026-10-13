"""Scoring rules parsed from Epic's scoringRuleSets, and per-game rescoring."""
import hashlib
import json

STATS = ("PLACEMENT_STAT_INDEX", "TEAM_ELIMS_STAT_INDEX", "VICTORY_ROYALE_STAT")


def parse(ruleset):
    """Epic ruleset -> compact JSON-safe list: [stat, matchRule, [[key, points, multiplicative], ...]]."""
    out = []
    for r in ruleset or []:
        tiers = sorted(([t["keyValue"], t["pointsEarned"], bool(t.get("multiplicative"))]
                        for t in r.get("rewardTiers", [])), key=lambda t: t[0])
        out.append([r["trackedStat"], r["matchRule"], tiers])
    return out


def game_points(rules, stats):
    """Points for one game. stats: {stat name: value}."""
    total = 0
    for stat, rule, tiers in rules:
        v = stats.get(stat)
        if v is None:
            continue
        # Tiers are cumulative: every tier that matches pays out (Epic's pointBreakdown shows this).
        for k, p, m in tiers:
            if rule == "lte" and v <= k:
                total += p
            elif rule == "gte" and v >= k:
                total += p * (v // k if m and k > 0 else 1)
            elif rule == "eq" and v == k:
                total += p
    return total


def session_stats(session):
    """Compact stored game [placement, elims, win] -> stats dict."""
    return dict(zip(STATS, session))


def describe(rules, match_cap=None):
    """Short human-readable summary."""
    parts = []
    for stat, rule, tiers in rules:
        if stat == "PLACEMENT_STAT_INDEX":
            runs, prev = [], None
            for k, p, _ in tiers:
                if prev and prev[2] == p:
                    prev[1] = k
                else:
                    prev = [k, k, p]
                    runs.append(prev)
            parts.append("placement: " + ", ".join(
                f"{a}{'' if a == b else '-' + str(b)}={p}" for a, b, p in runs))
        elif stat == "TEAM_ELIMS_STAT_INDEX":
            k, p, m = tiers[0]
            parts.append(f"+{p} per elim" if m else f"{p} pts for {k}+ elims")
        else:
            parts.append(stat)
    head = f"{match_cap} games; " if match_cap else ""
    return head + "; ".join(parts)


def format_key(match_cap, rules):
    blob = json.dumps([match_cap, rules], sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()[:10]
