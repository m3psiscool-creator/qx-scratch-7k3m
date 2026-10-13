import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import model, rules, storage

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>FN Game Analyzer</title>
<style>body{font:16px system-ui;max-width:680px;margin:2rem auto;padding:0 1rem}
select,input,button{font:inherit;padding:.4rem;margin:.2rem 0;width:100%;box-sizing:border-box}
table{width:100%;border-collapse:collapse;margin-top:1rem}td,th{padding:.4rem;border-bottom:1px solid #8884;text-align:left}
.big{font-size:1.4rem;font-weight:700}.box{border:1px solid #8884;border-radius:6px;padding:.6rem;margin:.6rem 0}
small{opacity:.75}</style>
<h1>FN Game Analyzer</h1>
<label>Tournament window <select id=w onchange=info()></select></label>
<div id=info class=box></div>
<label>Top X <input id=x type=number min=1 value=35></label>
<label>Entrants in this window (optional - leave blank to use a typical past number) <input id=e type=number min=1></label>
<button onclick=go()>Predict</button><div id=out></div>
<script>
const $=id=>document.getElementById(id);let WS=[];
const fmt=t=>new Date(t*1000).toLocaleString([],{weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
function info(){const w=WS.find(v=>v.window_id==$('w').value);if(!w){$('info').textContent='';return}
 $('info').innerHTML=`<b>${w.status}</b> &middot; ${fmt(w.begin)} &rarr; ${fmt(w.end)}<br>
 ${w.family} ${w.region} ${w.mode} ${w.round_type||''}<br>
 ${w.match_cap?w.match_cap+' games':'games unknown'}<br><small>${w.scoring||''}</small>
 ${w.advance.length?'<br>'+w.advance.map(a=>'Top '+a[0]+' &rarr; '+a[1]).join('<br>'):''}`}
fetch('/api/windows').then(r=>r.json()).then(ws=>{WS=ws;
 $('w').innerHTML=ws.map(w=>`<option value="${w.window_id}">[${w.status}] ${fmt(w.begin)} - ${w.window_id}</option>`).join('')||'<option>No data - run collect</option>';info()});
async function go(){
 const q=new URLSearchParams({window:$('w').value,top:$('x').value,entrants:$('e').value});
 const d=await (await fetch('/api/predict?'+q)).json();
 if(d.error){$('out').textContent=d.error;return}
 const row=(l,r)=>`<tr><td>${l}</td><td>${r.low}</td><td class=big>${r.likely}</td><td>${r.safe}</td></tr>`;
 $('out').innerHTML=`<table><tr><th>Rank</th><th>Low</th><th>Most likely</th><th>Safe (~95%)</th></tr>
 ${row('Top '+d.rank,d)}${(d.cutoffs||[]).map(c=>row('Top '+c.rank+' ('+c.label+')',c)).join('')}</table>
 <p><small>Method: ${d.method}. ${d.prior?d.prior.n+' past windows. Assumed entrants: '+Math.round(d.entrants_used||0)+'.':''}
 ${d.live?' Live: progress '+(d.live.progress*100).toFixed(0)+'% by '+d.live.basis+(d.live.learned?'':' (naive)'):' No live snapshot.'}</small></p>`}
</script>"""


def window_info(w):
    m = w["meta"]
    now = time.time()
    status = "finished" if w["final"] else ("live" if w["begin"] <= now <= w["end"] else
                                            "finished (not collected)" if w["end"] < now else "upcoming")
    return {
        "window_id": w["window_id"], "family": w["family"], "region": w["region"],
        "begin": w["begin"], "end": w["end"], "final": w["final"], "status": status,
        "match_cap": m.get("match_cap"), "mode": m.get("mode"), "round_type": m.get("round_type"),
        "advance": m.get("advance", []),
        "scoring": rules.describe(m["rules"]) if m.get("rules") else None,
    }


def make_handler():
    class H(BaseHTTPRequestHandler):
        def _send(self, body, ctype="application/json", code=200):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/":
                return self._send(PAGE, "text/html")
            if u.path == "/api/windows":
                ws = sorted((window_info(w) for w in storage.windows()),
                            key=lambda w: (w["status"] == "finished", w["begin"]
                                           if w["status"] != "finished" else -w["begin"]))
                return self._send(json.dumps(ws))
            if u.path == "/api/predict":
                try:
                    return self._send(json.dumps(run_predict(
                        q["window"], int(q["top"]), int(q["entrants"]) if q.get("entrants") else None)))
                except Exception as e:  # shown in the UI
                    return self._send(json.dumps({"error": str(e)}))
            self._send("not found", "text/plain", 404)

        def log_message(self, *a):
            pass
    return H


def run_predict(window_id, top, entrants=None):
    target = storage.get_window(window_id)
    if not target:
        raise ValueError("Unknown window")
    finished = [w for w in storage.windows(final=True)]
    snaps = storage.snapshots(window_id)
    snap = snaps[-1] if snaps and not target["final"] else None
    by_win = {w["window_id"]: storage.snapshots(w["window_id"]) for w in finished}
    entrants = entrants or (snap or {}).get("entrants")
    r = model.predict(target, finished, top, entrants, snap, by_win)
    if not r:
        raise ValueError("Not enough data: run collect first")
    r["entrants_used"] = entrants or (r["prior"] or {}).get("entrants") or 0
    r["cutoffs"] = []
    for rank, label in (target["meta"].get("advance") or []):
        if rank != top:
            c = model.predict(target, finished, rank, entrants, snap, by_win)
            if c:
                r["cutoffs"].append({"rank": rank, "label": label, "low": c["low"],
                                     "likely": c["likely"], "safe": c["safe"]})
    return r


def serve(port=8765):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler())
    print(f"Open http://localhost:{port}")
    srv.serve_forever()
