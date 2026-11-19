import sys, io, contextlib
sys.argv = [sys.argv[0], "250"]
import scripts.backtest_prestart as b
from fngameanalyzer import model
def go(label):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        b.run(label)
    print(buf.getvalue().strip())
go("base")
for d in (0.5, 0.6, 0.8, 0.9):
    model.DECAY = d; go(f"DECAY={d}")
model.DECAY = 0.7
for s in (0.9, 1.0):
    model.BAND_SCALE[0] = (0.0, s); go(f"bandstart={s}")
model.BAND_SCALE[0] = (0.0, 1.15)
for f in (0.05, 0.07, 0.15):
    model.PRIOR_SD_FLOOR = f; go(f"sdfloor={f}")
model.PRIOR_SD_FLOOR = 0.10
for m in (2, 6, 8):
    model.MIN_SAME_REGION = m; go(f"minSame={m}")
