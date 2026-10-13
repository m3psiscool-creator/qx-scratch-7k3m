import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import model, storage

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>FN Game Analyzer</title>
<style>body{font:16px system-ui;max-width:640px;margin:2rem auto;padding:0 1rem}
select,input,button{font:inherit;padding:.4rem;margin:.2rem 0;width:100%;box-sizing:border-box}
table{width:100%;border-collapse:collapse;margin-top:1rem}td,th{padding:.4rem;border-bottom:1px solid #8884;text-align:left}
.big{font-size:1.4rem;font-weight:700}</style>
<h1>FN Game Analyzer</h1>
<label>Window <select id=w></select></label>
<label>Top X <input id=x type=number min=1 value=100></label>
<label>Entrants (optional) <input id=e type=number min=1></label>
<button onclick=go()>Predict</button><div id=out></div>
<script>
const $=id=>document.getElementById(id);
fetch('/api/windows').then(r=>r.json()).then(ws=>{
 $('w').innerHTML=ws.map(w=>`<option value="${w.window_id}">${w.family} ${w.region} - ${w.window_id}${w.final?' (finished)':''}</option>`).join('')||'<option>No data - run collect</option>'});
async function go(){
 const q=new URLSearchParams({window:$('w').value,top:$('x').value,entrants:$('e').value});
 const d=await (await fetch('/api/predict?'+q)).json();
 if(d.error){$('out').textContent=d.error;return}
 $('out').innerHTML=`<table><tr><th>Low</th><th>Most likely</th><th>Safe (~95%)</th></tr>
 <tr class=big><td>${d.low}</td><td>${d.likely}</td><td>${d.safe}</td></tr></table>
 <p>Prior: ${d.prior?d.prior.n+' past windows':'none'}. Live: ${d.live?'progress '+(d.live.progress*100).toFixed(0)+'% by '+d.live.basis+(d.live.learned?'':' (naive)'):'no snapshot'}.</p>`}
</script>"""


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
                ws = [{k: w[k] for k in ("window_id", "family", "region", "begin", "end", "final")}
                      for w in storage.windows()]
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
    return r


def serve(port=8765):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler())
    print(f"Open http://localhost:{port}")
    srv.serve_forever()
