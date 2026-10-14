"""The phone remote (/app) and the StandBy clock (/standby): two small pages that poll /api/live every two
seconds and press buttons through /api/act. Signed in like the settings page; add either to the phone's
home screen. StandBy is for a phone or tablet on a stand: a big clock, the weather, timers counting down,
red and dim in quiet hours, and a big Stop when something rings.
"""

_JS = r"""
const $=s=>document.querySelector(s);let L=null,T0=0;
async function act(what,arg,which){const b=new URLSearchParams({what,arg:arg||'',which:which||''});
 try{await fetch('/api/act',{method:'POST',body:b,credentials:'same-origin'})}catch(e){} poll()}
function mmss(s){s=Math.max(0,Math.round(s));const h=Math.floor(s/3600),m=Math.floor(s/60)%60,x=s%60;
 return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(x).padStart(2,'0')}
function left(t){return t.state=='waiting'?t.left_s-(Date.now()/1000-T0):t.left_s}
const STATE={asleep:'Asleep',listening:'Listening',speaking:'Speaking',working:'Working…',needs_setup:'Needs setup',starting:'Starting'};
const SKY={0:'☀',1:'🌤',2:'⛅',3:'☁',45:'🌫',48:'🌫',51:'🌦',53:'🌦',55:'🌧',61:'🌦',63:'🌧',65:'🌧',71:'🌨',73:'🌨',75:'❄',80:'🌦',81:'🌧',82:'⛈',95:'⛈',96:'⛈',99:'⛈'};
async function poll(){try{const r=await fetch('/api/live',{credentials:'same-origin'});if(r.redirected||!r.ok){location='/login';return}
 L=await r.json();T0=Date.now()/1000;draw()}catch(e){}}
setInterval(poll,2000);setInterval(()=>L&&tick(),250);poll();
"""

APP = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#0b0b10"><title>Kevin</title>
<style>
:root{color-scheme:dark;--bg:#0b0b10;--card:rgba(255,255,255,.06);--line:rgba(255,255,255,.09);--dim:rgba(235,235,245,.6);
 --brand:linear-gradient(135deg,#2f8cff,#5e5ce6 52%,#a65cf0);--red:#ff453a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:radial-gradient(120% 60% at 10% -10%,rgba(94,92,230,.35),transparent 60%),var(--bg);color:#f5f5f7;
 font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;min-height:100vh}
main{max-width:520px;margin:auto;padding:max(18px,env(safe-area-inset-top)) 16px 40px}
.top{display:flex;align-items:center;justify-content:space-between;margin:6px 0 16px}
h1{font-size:28px;margin:0}.pill{font-size:13px;padding:5px 11px;border-radius:999px;background:rgba(255,255,255,.1)}
.card{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:16px;margin:12px 0}
.card h2{font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);margin:0 0 10px}
button{border:0;border-radius:14px;padding:12px 14px;font:inherit;font-weight:600;color:#fff;background:rgba(255,255,255,.1);cursor:pointer}
button.go{background:var(--brand)}button.stop{background:var(--red)}
.talk{width:100%;padding:22px;font-size:20px;border-radius:22px;background:var(--brand);display:flex;gap:12px;align-items:center;justify-content:center}
.talk.on{background:var(--red)}.talk i{width:12px;height:12px;border-radius:50%;background:#fff;opacity:.85}
.talk.on i{animation:p 1s infinite}@keyframes p{50%{transform:scale(1.6);opacity:.4}}
.t{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line)}.t:first-child{border-top:0}
.t .n{flex:1;min-width:0}.t .n b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.t .n span{color:var(--dim);font-size:13px}
.t .c{font:600 26px/1 ui-rounded,-apple-system,system-ui;font-variant-numeric:tabular-nums}
.t.ring{animation:r 1s infinite}@keyframes r{50%{background:rgba(255,69,58,.18)}}
.row{display:flex;gap:8px;flex-wrap:wrap}.row button{flex:1}.dim{color:var(--dim)}
.wx{display:flex;align-items:center;gap:14px}.wx .big{font-size:44px}.wx .tmp{font:600 34px/1 -apple-system,system-ui}
a{color:#a8a5ff;text-decoration:none}
</style><main>
<div class="top"><h1 id="nm">Kevin</h1><span class="pill" id="st">…</span></div>
<button class="talk" id="talk" onclick="act('talk')"><i></i><span id="tt">Talk</span></button>
<div class="card"><h2>Timers &amp; alarms</h2><div id="tl"></div>
 <div class="row" style="margin-top:10px"><button onclick="act('quick_timer',1)">1 min</button><button onclick="act('quick_timer',5)">5</button>
 <button onclick="act('quick_timer',10)">10</button><button onclick="act('quick_timer',25)">25</button></div></div>
<div class="card" id="mc"><h2>Music</h2><div id="mt" class="dim">Nothing playing — say “play Radio Paradise”.</div>
 <div class="row" id="mb" style="margin-top:10px;display:none"><button onclick="act('music','pause')" id="pp">Pause</button>
 <button onclick="act('music','next')">Next</button><button onclick="act('music','quieter')">−</button><button onclick="act('music','louder')">+</button>
 <button class="stop" onclick="act('music','stop')">Stop</button></div></div>
<div class="card" id="wc" style="display:none"><h2>Weather</h2><div class="wx"><span class="big" id="wi"></span><span class="tmp" id="wt"></span>
 <span class="dim" id="wd"></span></div></div>
<p class="dim" style="text-align:center"><a href="/standby">StandBy clock</a> · <a href="/">Settings</a></p>
</main><script>""" + _JS + r"""
function draw(){$('#nm').textContent=L.name;$('#st').textContent=STATE[L.state]||L.state;
 const on=['listening','speaking','working'].includes(L.state);$('#talk').classList.toggle('on',on);$('#tt').textContent=on?'Stop':'Talk';
 $('#tl').innerHTML=L.timers.length?'':'<div class="dim">None set.</div>';
 for(const t of L.timers){const d=document.createElement('div');d.className='t'+(t.state=='ringing'?' ring':'');d.dataset.id=t.id;
  const btns=t.state=='ringing'?`<button class="stop" onclick="act('timer','stop',${t.id})">Stop</button><button onclick="act('timer','snooze',${t.id})">Snooze</button>`
   :t.kind=='alarm'?`<button onclick="act('timer','cancel',${t.id})">✕</button>`
   :`<button onclick="act('timer','${t.state=='paused'?'resume':'pause'}',${t.id})">${t.state=='paused'?'▶':'❚❚'}</button><button onclick="act('timer','add1',${t.id})">+1</button><button onclick="act('timer','cancel',${t.id})">✕</button>`;
  d.innerHTML=`<div class="n"><b></b><span>${t.kind=='alarm'?'in '+mmss(t.left_s).replace(/:\d\d$/,'').replace(':','h ')+'m':(t.state=='paused'?'Paused':'Ends '+t.due)}</span></div><div class="c"></div>${btns}`;
  d.querySelector('b').textContent=t.name;$('#tl').appendChild(d)}
 const m=L.music||{};$('#mb').style.display=m.playing?'flex':'none';
 $('#mt').textContent=m.playing?((m.title||'')+(m.source&&m.source!=m.title?' — '+m.source:'')):'Nothing playing — say “play Radio Paradise”.';
 $('#pp').textContent=m.paused?'Play':'Pause';$('#pp').onclick=()=>act('music',m.paused?'resume':'pause');
 const w=L.weather;$('#wc').style.display=w?'block':'none';
 if(w){$('#wi').textContent=SKY[w.now.code]||'';$('#wt').textContent=Math.round(w.now.temp_c)+'°';
  $('#wd').textContent=w.now.sky+' · '+Math.round(w.today.low_c)+'–'+Math.round(w.today.high_c)+'° · rain '+w.today.rain_chance_pct+'%'}tick()}
function tick(){document.querySelectorAll('.t').forEach(d=>{const t=L.timers.find(x=>x.id==d.dataset.id);if(t)d.querySelector('.c').textContent=t.state=='ringing'?'⏰':t.kind=='alarm'?'⏰ '+t.due:mmss(left(t))})}
</script></html>"""

STANDBY = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#000"><title>Kevin StandBy</title>
<style>
*{box-sizing:border-box}html,body{margin:0;height:100%;background:#000;color:#fff;overflow:hidden;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;-webkit-user-select:none;user-select:none}
.wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2vh;padding:env(safe-area-inset-top) 4vw}
#clock{font:200 min(34vw,46vh)/0.9 ui-rounded,-apple-system,system-ui;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
#date{font-size:min(5vw,5vh);opacity:.7}#wx{font-size:min(4.4vw,4.4vh);opacity:.75}
#timers{display:flex;gap:4vw;flex-wrap:wrap;justify-content:center}.tm{text-align:center}.tm b{display:block;font:500 min(9vw,10vh)/1 -apple-system,system-ui;font-variant-numeric:tabular-nums}
.tm span{opacity:.6;font-size:min(3.4vw,3.6vh)}
#ring{position:fixed;inset:0;display:none;flex-direction:column;align-items:center;justify-content:center;gap:4vh;background:#2a0000;animation:f 1s infinite}
@keyframes f{50%{background:#5a0000}}#ring h1{font-size:min(10vw,10vh);margin:0}#ring button{font-size:min(7vw,7vh);padding:2vh 8vw;border:0;border-radius:99px;background:#ff453a;color:#fff;font-weight:700}
#ring .sn{background:rgba(255,255,255,.18);font-size:min(4.5vw,4.5vh)}
#talk{position:fixed;bottom:max(3vh,env(safe-area-inset-bottom));right:4vw;width:min(16vw,16vh);height:min(16vw,16vh);border-radius:50%;border:0;
 background:rgba(255,255,255,.12);color:#fff;font-size:min(6vw,6vh)}#talk.on{background:#ff453a}
body.night{color:#ff3b30}body.night .wrap{opacity:.55}body.night #talk{background:rgba(255,59,48,.18);color:#ff3b30}
</style><div class="wrap" onclick="document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen().catch(()=>{})">
<div id="clock">--:--</div><div id="date"></div><div id="wx"></div><div id="timers"></div></div>
<div id="ring"><h1 id="rn">Time's up</h1><button onclick="act('timer','stop')">Stop</button><button class="sn" onclick="act('timer','snooze')">Snooze 9 min</button></div>
<button id="talk" onclick="act('talk')" aria-label="Talk">🎙</button>
<script>""" + _JS + r"""
function draw(){document.body.classList.toggle('night',!!L.quiet);
 const on=['listening','speaking','working'].includes(L.state);$('#talk').classList.toggle('on',on);
 const w=L.weather;$('#wx').textContent=w?((SKY[w.now.code]||'')+' '+Math.round(w.now.temp_c)+'°  '+w.now.sky+'  ·  '+Math.round(w.today.low_c)+'–'+Math.round(w.today.high_c)+'°'):'';
 const r=L.timers.find(t=>t.state=='ringing');$('#ring').style.display=r?'flex':'none';if(r)$('#rn').textContent=r.name;
 $('#timers').innerHTML='';for(const t of L.timers.filter(t=>t.state!='ringing').slice(0,3)){const d=document.createElement('div');d.className='tm';d.dataset.id=t.id;
  d.innerHTML='<b></b><span></span>';d.querySelector('span').textContent=(t.kind=='alarm'?'⏰ ':'')+t.name;$('#timers').appendChild(d)}tick()}
function tick(){const n=new Date();$('#clock').textContent=String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0');
 $('#date').textContent=n.toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long'});
 document.querySelectorAll('.tm').forEach(d=>{const t=L.timers.find(x=>x.id==d.dataset.id);if(t)d.querySelector('b').textContent=t.kind=='alarm'?t.due:mmss(left(t))})}
</script></html>"""
