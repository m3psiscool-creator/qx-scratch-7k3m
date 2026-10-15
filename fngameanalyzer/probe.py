"""Owner-only probe: what does a leaderboard entry contain, and does Epic's replay storage answer for a session id?
Runs on the server only (it uses the production Epic login)."""
import requests

from . import auth, storage
from .epic_api import Epic

STORE = "https://datastorage-public-service-live.ol.epicgames.com/api/v1/access"


def run(window_id, rank=1):
    w = storage.get_window(window_id)
    if not w:
        raise ValueError("Unknown window")
    sess = auth.Session()
    d = Epic(sess).page(w["event_id"], window_id, (rank - 1) // 100)
    entries = sorted(d.get("entries", []), key=lambda e: e.get("rank", 0))
    e = next((x for x in entries if x.get("rank") == rank), entries[0])
    hist = e.get("sessionHistory") or []
    out = {"entry_keys": sorted(e.keys()), "session_keys": sorted(hist[0].keys()) if hist else [],
           "first_session": hist[0] if hist else None, "tries": []}
    sid = (hist[0] or {}).get("sessionId") if hist else None
    if not sid:
        return out
    tok = sess.bearer()
    for path in (f"/fnreplaysmetadata/public/{sid}", f"/fnreplays/public/{sid}", f"/fnreplays/public/{sid}/header",
                 f"/fnreplaysmetadata/{sid}", f"/fnreplays/{sid}"):
        try:
            r = requests.get(STORE + path, headers={"Authorization": "Bearer " + tok}, timeout=20)
            kind = r.headers.get("content-type") or ""
            out["tries"].append({"path": path, "status": r.status_code, "type": kind, "len": len(r.content),
                                 "head": r.text[:300] if "json" in kind or r.status_code >= 400 else ""})
        except Exception as ex:
            out["tries"].append({"path": path, "error": str(ex)[:150]})
    # follow the links: what does the metadata hold, how big is the header, what files does the match have?
    out["follow"] = {}
    for path in (f"/fnreplaysmetadata/public/{sid}", f"/fnreplays/public/{sid}", f"/fnreplays/public/{sid}/header"):
        try:
            r = requests.get(STORE + path, headers={"Authorization": "Bearer " + tok}, timeout=20).json()
            for name, f in (r.get("files") or {}).items():
                link = f.get("readLink")
                info = {"keys": sorted(f.keys()), "size": f.get("size"), "file": name}
                if link:
                    got = requests.get(link, timeout=30, stream=True)
                    body = got.raw.read(4000, decode_content=True)
                    info.update(status=got.status_code, type=got.headers.get("content-type"), total=got.headers.get("content-length"),
                                head=body[:1500].decode("utf-8", "replace") if body[:1] in (b"{", b"[") else body[:48].hex())
                out["follow"][path] = info
        except Exception as ex:
            out["follow"][path] = {"error": str(ex)[:200]}
    # the path the open-source downloaders use for the chunk list
    try:
        r = requests.get(STORE.replace("/access", "/data") + f"/fnreplaysmetadata/public/{sid}.json", headers={"Authorization": "Bearer " + tok}, timeout=20)
        out["data_meta"] = {"status": r.status_code, "len": len(r.content), "head": r.text[:1800]}
        meta = r.json() if r.status_code == 200 else {}
        # chunk links: POST {files: [...]} to the match folder
        names = ["header.bin"] + [f"{c['Id']}.bin" for k in ("DataChunks", "Events", "Checkpoints") for c in (meta.get(k) or [])][:3]
        p = requests.post(f"{STORE}/fnreplays/public/{sid}/", json={"files": names}, headers={"Authorization": "Bearer " + tok}, timeout=20)
        out["links"] = {"status": p.status_code, "names": names, "head": p.text[:600]}
        if p.status_code == 200:
            fl = (p.json().get("files") or {}).get("header.bin") or {}
            if fl.get("readLink"):
                g = requests.get(fl["readLink"], timeout=30)
                out["header"] = {"status": g.status_code, "len": len(g.content), "first": g.content[:32].hex()}
        out["meta_keys"] = sorted(meta.keys())
        out["meta_counts"] = {k: len(meta[k]) for k in meta if isinstance(meta[k], list)}
    except Exception as ex:
        out["data_meta"] = {"error": str(ex)[:200]}
    return out


def scan(q="", regions=None):
    """Owner only: every event Epic lists (not only the types the site tracks) whose id or type matches q."""
    import re
    from . import config
    from .epic_api import classify, parse_time
    epic = Epic(auth.Session())
    seen = {}
    for region in regions or config.ALL_REGIONS:
        try:
            raw = epic.raw_events(region)
        except Exception as ex:
            seen[f"error:{region}"] = str(ex)[:120]
            continue
        for ev in raw.get("events", []):
            eid = ev.get("eventId", "")
            ttype = (ev.get("metadata") or {}).get("tournamentType")
            text = f"{eid} {ttype} {(ev.get('metadata') or {}).get('minimumAccountLevel', '')}"
            if q and not re.search(q, text, re.I):
                continue
            fam, _ = classify(eid)
            row = seen.setdefault(eid, {"event_id": eid, "tournamentType": ttype, "tracked": bool(config.TOURNAMENT_TYPES.get(ttype) or (fam and not ttype)),
                                        "regions": [], "windows": []})
            row["regions"].append(region)
            for w in ev.get("eventWindows", []):
                if w["eventWindowId"] not in row["windows"] and len(row["windows"]) < 12:
                    row["windows"].append(w["eventWindowId"])
            row["begin"] = ev.get("beginTime")
            row["end"] = ev.get("endTime")
    return sorted(seen.values(), key=lambda r: r.get("begin") or "", reverse=True) if all(isinstance(v, dict) for v in seen.values()) else seen


def sync_test(region="NAC"):
    """Owner only: run the window parser for one region and say what it returns or where it fails."""
    epic = Epic(auth.Session())
    raw = epic.raw_events(region)
    out = {"events": len(raw.get("events", [])), "windows": 0, "by_family": {}, "errors": []}
    try:
        ws = epic.windows(region, raw)
        out["windows"] = len(ws)
        from . import classify
        for w in ws:
            out["by_family"][w["family"]] = out["by_family"].get(w["family"], 0) + 1
            if w["family"] == "WORKSHOP" and "sample" not in out:
                try:
                    out["sample"] = {"id": w["window_id"], "category": classify.of(w), "meta": {k: w["meta"].get(k) for k in ("playlist", "mode", "game_type", "match_cap", "lobby")}}
                except Exception:
                    import traceback
                    out["errors"].append("classify: " + traceback.format_exc()[-500:])
    except Exception as ex:
        import traceback
        out["errors"].append(traceback.format_exc()[-900:])
    # which workshop events fail on their own
    from . import epic_api
    for ev in raw.get("events", []):
        if (ev.get("metadata") or {}).get("tournamentType") == "WorkshopCup":
            for w in ev.get("eventWindows", [])[:2]:
                try:
                    epic_api.window_meta(raw, ev, w)
                except Exception:
                    import traceback
                    out["errors"].append(ev["eventId"] + ": " + traceback.format_exc()[-600:])
    return out
