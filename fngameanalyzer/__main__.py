import argparse
import json
import time

from . import auth, config, storage
from .epic_api import Epic


def _epic():
    return Epic(auth.Session())


def cmd_login(a):
    print("1. Log in to Epic in your browser.\n2. Open this link:\n  ", config.LOGIN_URL)
    print("3. Copy the value of authorizationCode from the page.")
    code = (a.code or input("authorizationCode: ")).strip().strip('"')
    print("Logged in as", auth.login(code))


def cmd_probe(a):
    e = _epic()
    for region in a.regions:
        raw = e.raw_events(region)
        (config.HOME / f"probe_events_{region}.json").write_text(json.dumps(raw))
        ws = e.windows(region, raw)
        print(f"{region}: {len(raw.get('events', []))} events, {len(ws)} FNCS/Cash Cup windows")
        done = [w for w in ws if e.finished(w)]
        if done:
            w = max(done, key=lambda x: x["end"])
            d = e.page(w["event_id"], w["window_id"])
            (config.HOME / "probe_leaderboard.json").write_text(json.dumps(d))
            print("  sample:", w["window_id"], "entries:", len(d.get("entries", [])),
                  "totalPages:", d.get("totalPages"))
    print("Raw JSON saved in", config.HOME)


def _sync(e, regions):
    out = []
    for region in regions:
        for w in e.windows(region):
            storage.upsert_window(w)
            out.append(w)
    return out


def cmd_collect(a):
    e = _epic()
    have = {w["window_id"] for w in storage.windows(final=True)}
    for w in _sync(e, a.regions):
        if e.finished(w) and w["window_id"] not in have:
            try:
                lb = e.leaderboard(w["event_id"], w["window_id"], a.max_rank)
            except Exception as ex:
                print("skipped", w["window_id"], str(ex)[:120])
                continue
            storage.save_final(w["window_id"], lb)
            print("stored", w["window_id"], len(lb["points"]), "ranks")
            have.add(w["window_id"])


def cmd_watch(a):
    e = _epic()
    while True:
        now = time.time()
        for w in _sync(e, a.regions):
            if w["begin"] <= now <= w["end"]:
                storage.save_snapshot(w["window_id"], e.leaderboard(
                    w["event_id"], w["window_id"], a.max_rank))
                print(time.strftime("%H:%M:%S"), "snapshot", w["window_id"])
        time.sleep(a.interval)


def cmd_serve(a):
    from .web import serve
    serve(a.port)


def cmd_predict(a):
    from .web import run_predict
    print(json.dumps(run_predict(a.window_id, a.top, a.entrants), indent=1))


def main():
    p = argparse.ArgumentParser(prog="fngameanalyzer")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("login")
    s.add_argument("code", nargs="?")
    s.set_defaults(f=cmd_login)
    for name, f in (("probe", cmd_probe), ("collect", cmd_collect), ("watch", cmd_watch)):
        s = sub.add_parser(name)
        s.add_argument("--regions", nargs="+", default=["EU"])
        if name != "probe":
            s.add_argument("--max-rank", type=int, default=1000)
        if name == "watch":
            s.add_argument("--interval", type=int, default=300)
        s.set_defaults(f=f)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(f=cmd_serve)
    s = sub.add_parser("predict")
    s.add_argument("window_id")
    s.add_argument("top", type=int)
    s.add_argument("--entrants", type=int)
    s.set_defaults(f=cmd_predict)
    a = p.parse_args()
    a.f(a)


main()
