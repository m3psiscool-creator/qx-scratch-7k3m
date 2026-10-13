PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>FN Game Analyzer</title>
<style>
:root{--bg:#0f1115;--card:#181b22;--line:#2a2f3a;--tx:#e8eaf0;--mut:#9aa3b2;--ac:#7c5cff;--ok:#2ecc71;--warn:#f5a623}
@media(prefers-color-scheme:light){:root{--bg:#f5f6fa;--card:#fff;--line:#dfe3ec;--tx:#14171f;--mut:#5b6577}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.45 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:1.3rem;margin:.2rem 0 1rem}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}
label{display:block;color:var(--mut);font-size:.85rem;margin-top:8px}
select,input,button{width:100%;font:inherit;padding:9px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--tx);margin-top:4px}
button{background:var(--ac);border:0;color:#fff;font-weight:600;cursor:pointer}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
table{width:100%;border-collapse:collapse}th,td{padding:7px 6px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:500;font-size:.82rem}.num{font-variant-numeric:tabular-nums}
.big{font-size:1.5rem;font-weight:700}.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:.78rem;font-weight:600;background:var(--line)}
.live{background:var(--ok);color:#06210f}.up{background:var(--warn);color:#2b1c00}
.mut{color:var(--mut)}small{color:var(--mut)}
@media(max-width:520px){.row{grid-template-columns:1fr}}
</style>
<main>
<h1>FN Game Analyzer <small id=status></small></h1>
<div class=card>
 <label>Tournament <select id=w></select></label>
 <div id=info style="margin-top:10px"></div>
 <div class=row>
  <label>Top X <input id=x type=number min=1 value=35></label>
  <label>Entrants (optional) <input id=e type=number min=1 placeholder="auto"></label>
 </div>
 <button onclick="go()">Predict</button>
</div>
<div id=out></div>
<div id=live></div>
<div class=card id=loginbox style="display:none">
 <b>Epic login needed</b><p class=mut>Log in to Epic in this browser, open
 <a id=ll target=_blank>this link</a>, copy the <code>authorizationCode</code> value and paste it here.</p>
 <input id=code placeholder="authorizationCode"><input id=key type=password placeholder="Admin key">
 <button onclick="login()">Save login</button><div id=lmsg class=mut></div>
</div>
</main>
<script>
const $=id=>document.getElementById(id);let WS=[],timer=null;
const fmt=t=>new Date(t*1000).toLocaleString([],{weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
const ago=s=>s==null?'-':s<90?s+'s ago':Math.round(s/60)+' min ago';
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function j(u,o){const r=await fetch(u,o);return r.json()}
function cur(){return WS.find(v=>v.window_id==$('w').value)}
function info(){const w=cur();if(!w){$('info').textContent='';return}
 const cls=w.status=='live'?'live':w.status=='upcoming'?'up':'';
 $('info').innerHTML=`<span class="pill ${cls}">${w.status}</span> ${fmt(w.begin)} &rarr; ${fmt(w.end)}<br>
 <b>${w.family}</b> ${w.region} &middot; ${w.game_type=='reload'?'Reload':'Battle Royale'} ${w.mode} &middot; ${w.match_cap||'?'} games
 &middot; lobby ${w.lobby?w.lobby+(w.mode=='solo'?' players':' teams'):'unknown'}<br>
 <small>${w.scoring||''}</small>${w.advance.length?'<br><small>'+w.advance.map(a=>'Top '+a[0]+' advance').join(', ')+'</small>':''}`;
 live()}
async function status(){const s=await j('/api/status');
 $('status').textContent=s.logged_in?(s.last_tick_age_s!=null?'collector: '+ago(s.last_tick_age_s):'collector: waiting'):'not logged in';
 if(!s.logged_in){$('loginbox').style.display='block';$('ll').href=s.login_url}}
async function load(){WS=await j('/api/windows');
 $('w').innerHTML=WS.map(w=>`<option value="${w.window_id}">[${w.status}] ${fmt(w.begin)} - ${w.window_id}</option>`).join('')||'<option>No tournaments yet</option>';
 const first=WS.find(w=>w.status=='live')||WS.find(w=>w.status=='upcoming');if(first)$('w').value=first.window_id;
 $('w').onchange=info;info();status()}
async function go(){const w=cur();if(!w)return;
 const q=new URLSearchParams({window:w.window_id,top:$('x').value,entrants:$('e').value});
 const d=await j('/api/predict?'+q);
 if(d.error){$('out').innerHTML=`<div class=card>${esc(d.error)}</div>`;return}
 const row=(l,r,b)=>`<tr><td>${l}</td><td class=num>${r.low}</td><td class="num ${b?'big':''}">${r.likely}</td><td class=num>${r.safe}</td></tr>`;
 const lv=d.live;
 $('out').innerHTML=`<div class=card><table><tr><th>Rank</th><th>Low</th><th>Most likely</th><th>Safe (~95%)</th></tr>
 ${row('Top '+d.rank,d,1)}${(d.cutoffs||[]).map(c=>row('Top '+c.rank,c)).join('')}</table>
 <p><small>${d.method?'Method: '+esc(d.method)+'. ':''}${d.prior?d.prior.n+' comparable past windows. ':''}
 ${lv?`Live: ${lv.current} pts now at rank ${d.rank}, ${(lv.progress*100).toFixed(0)}% through (${esc(lv.basis)}${lv.n?', '+lv.n+' past events':''}). Board updated ${ago(d.snapshot_age_s)}.`:'No live board yet.'}</small></p></div>`}
async function live(){const w=cur();if(!w||w.status=='upcoming'||w.status=='finished'){$('live').innerHTML='';return}
 const d=await j('/api/live?window='+encodeURIComponent(w.window_id));
 if(!d.snapshot){$('live').innerHTML='<div class=card><small>Waiting for the first live board...</small></div>';return}
 $('live').innerHTML=`<div class=card><b>Live top ${d.top.length}</b> <small>updated ${ago(d.snapshot.age_s)}, ${d.snapshot.entrants} entrants</small>
 <table><tr><th>#</th><th>Player</th><th>Pts</th><th>Games</th><th>Past top finishes</th></tr>${d.top.map(t=>`<tr><td>${t.rank}</td>
 <td>${t.players.map(p=>esc(p.name)).join(' + ')}</td><td class=num>${t.points}</td><td class=num>${t.games}</td>
 <td><small>${t.players.map(p=>p.events?p.events+' events, best #'+p.best:'new').join(' / ')}</small></td></tr>`).join('')}</table></div>`}
async function login(){const r=await j('/api/login',{method:'POST',headers:{'content-type':'application/json'},
 body:JSON.stringify({code:$('code').value.trim(),key:$('key').value})});
 $('lmsg').textContent=r.ok?'Logged in. The collector will start on its next run.':(r.error||'failed');if(r.ok)status()}
load();setInterval(()=>{status();live();const w=cur();if(w&&w.status=='live')go()},30000);
</script></html>"""
