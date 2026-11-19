"""Back-test of the pre-start prediction on finished windows (read-only; run with POSTGRES_URL set to the database).
Usage: python scripts/backtest_prestart.py [N_recent_windows]  -> prints error, bias and band coverage by rank group."""
import math
import pickle
import statistics as st
import sys
import time

from fngameanalyzer import classify, model, storage

N = int(sys.argv[1]) if len(sys.argv) > 1 else 150
RANKS = [1, 10, 50, 100, 300, 500]
CACHE = "bt_all.pkl"
try:
    ALL = pickle.load(open(CACHE, "rb"))
except Exception:
    ALL = storage.windows_all(None)
    pickle.dump(ALL, open(CACHE, "wb"))
ALL = [w for w in ALL if w.get("points")]
fin = sorted([w for w in ALL if w["end"] < time.time() - 3600], key=lambda w: -w["end"])[:N]


def run(label=""):
    rows = []
    for t in fin:
        for wide in (False, True):
            model._ctx.approx = wide
            cls = classify.of(t)
            hist = [w for w in ALL if w["end"] < t["begin"] and w["window_id"] != t["window_id"] and (wide or classify.of(w) == cls)]
            for r in RANKS:
                if any(x[0] == t["window_id"] and x[1] == r for x in rows) or r > len(t["points"]):
                    continue
                try:
                    p = model.predict(t, hist, r, None, None, {})
                except Exception:
                    p = None
                if p and (wide or p.get("prior")):
                    a = t["points"][r - 1]
                    if a > 0:
                        rows.append((t["window_id"], r, p["low"], p["likely"], p["safe"], a))
        model._ctx.approx = False
    le = [math.log1p(x[3]) - math.log1p(x[5]) for x in rows]
    ae = [abs(e) for e in le]
    cov = sum(1 for x in rows if x[2] <= x[5] <= x[4]) / len(rows)
    print(f"{label} n={len(rows)} medAbsLogErr={st.median(ae):.3f} meanAbs={st.mean(ae):.3f} bias={st.median(le):+.3f} p90abs={sorted(ae)[int(.9 * len(ae))]:.3f} cover80={cov:.2f}")
    return rows


if __name__ == "__main__":
    run("current")
