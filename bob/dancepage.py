"""The dance screen (/dance): Kevin's face dancing to the beat, full screen, for a TV or the Pi's HDMI output.

It only reads /api/dance (see dance.py), so it is also the example to copy when you make your own: anything that can
fetch that JSON can dance. Transforms and opacity only, so it runs smoothly on a Pi's own browser.
"""

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Kevin dancing</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#05040c;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
#d{position:fixed;inset:0;--h:220;--k:0;--up:0;--sx:1;--sy:1;--rot:0deg;--x:0vw;--per:.5s;--blink:1;--look:0%}
.bg{position:absolute;inset:-10%;background:radial-gradient(ellipse at 50% 60%,hsl(var(--h),70%,32%) 0%,hsl(calc(var(--h) + 70),60%,12%) 45%,#05040c 75%);opacity:calc(.5 + var(--k) * .5);transition:opacity .12s,background 1.5s}
.beams{position:absolute;left:50%;top:-12%;animation:sw 5s ease-in-out infinite alternate}
.beams u{position:absolute;left:-7vw;width:14vw;height:130vh;transform-origin:50% 0;transform:rotate(calc(var(--r) - 150deg));background:linear-gradient(hsla(calc(var(--h) + var(--r)),90%,70%,.22),transparent 80%);opacity:calc(.25 + var(--k) * .6);transition:opacity .15s}
@keyframes sw{from{transform:rotate(-25deg)}to{transform:rotate(25deg)}}
.sn{position:absolute;inset:0;background:radial-gradient(circle,transparent 30%,hsla(calc(var(--h) + 150),95%,70%,.32) 100%);opacity:0;transition:opacity .3s}.sn.hit{opacity:1;transition:none}
.mover{position:absolute;left:50%;bottom:20vh;width:30vh;height:30vh;margin-left:-15vh;transform:translateX(var(--x));transition:transform calc(var(--per) * 4) cubic-bezier(.45,0,.25,1)}
.shadow{position:absolute;left:10%;right:10%;bottom:-4vh;height:4vh;border-radius:50%;background:rgba(0,0,0,.55);transform:scaleX(calc(1 - var(--up) * .35));transition:transform .14s}
.bounce{position:absolute;inset:0;transform-origin:50% 100%;transform:translateY(calc(var(--up) * -9vh)) rotate(var(--rot)) scale(var(--sx),var(--sy));transition:transform .14s cubic-bezier(.3,1.6,.5,1)}
.groove{position:absolute;inset:0;animation:groove calc(var(--per) * 2) ease-in-out infinite;transform-origin:50% 100%}
@keyframes groove{0%,100%{transform:translateY(0) rotate(-4deg)}25%,75%{transform:translateY(-1.5vh) rotate(0deg) scaleY(1.03)}50%{transform:translateY(0) rotate(4deg) scaleY(.97)}}
.tw{position:absolute;inset:0;transform:rotate(var(--tw,0deg)) translateX(var(--sh,0vh));transition:transform .09s ease-out}
.face{position:absolute;inset:0;border-radius:24%;background:linear-gradient(150deg,hsl(var(--h),85%,62%),hsl(calc(var(--h) + 50),80%,45%));box-shadow:0 2vh 6vh hsla(var(--h),90%,50%,.45),inset 0 -1.5vh 3vh rgba(0,0,0,.25);transition:background 1s}
.eyes{position:absolute;left:0;right:0;top:34%;display:flex;justify-content:center;gap:16%;transform:translateX(var(--look));transition:transform .18s}
.eyes i{display:block;width:2.6vh;height:6.2vh;border-radius:2vh;background:#fff;transform:scaleY(var(--blink));transition:transform .08s}
.mouth{position:absolute;left:39%;top:64%;width:22%;height:9%;border-radius:0 0 3vh 3vh;background:rgba(255,255,255,.9);transform:scaleY(calc(.25 + var(--k) * .9));transform-origin:50% 0;transition:transform .1s}
.t{position:absolute;bottom:4vh;left:0;right:0;text-align:center;color:rgba(255,255,255,.7);font-size:2vh}
.idle{position:absolute;inset:0;display:grid;place-items:center;color:rgba(255,255,255,.6);font-size:2.4vh;text-align:center;padding:4vh}
#d:not(.on) .stage{display:none}#d.on .idle{display:none}
</style></head><body><div id="d">
<div class="stage"><div class="bg"></div><div class="beams">__BEAMS__</div><div class="sn"></div>
<div class="mover"><div class="shadow"></div><div class="bounce"><div class="groove"><div class="tw"><div class="face"><div class="eyes"><i></i><i></i></div><div class="mouth"></div></div></div></div></div></div>
<div class="t"></div></div>
<div class="idle">Dance mode is off.<br>Say "Hey Kevin, dance" and put some music on.</div></div>
<script>
const D=document.getElementById('d'),S=(k,v)=>D.style.setProperty(k,v),SPOTS=[0,-22,0,22,-12,12,-26,26];
let lastN=-1,lastSn=-1,lastHt=-1,landT=0,lastK=0,twT=0;
const twitch=(deg,sh,ms)=>{S('--tw',deg+'deg');S('--sh',sh+'vh');clearTimeout(twT);twT=setTimeout(()=>{S('--tw','0deg');S('--sh','0vh')},ms)};
async function tick(){let d={};try{d=await (await fetch('/api/dance',{cache:'no-store'})).json()}catch(e){}
  D.classList.toggle('on',!!d.live);
  if(d.live){S('--h',d.hue);S('--k',(d.kick||0).toFixed(2));S('--per',(60/(d.bpm||120)).toFixed(2)+'s');
    if(d.n!==lastN){if(lastN>=0){S('--up',(0.6+0.5*(d.glow||0)).toFixed(2));S('--sx','.9');S('--sy','1.12');S('--rot',(d.n%2?9:-9)+'deg');
        clearTimeout(landT);landT=setTimeout(()=>{S('--up','0');S('--sx','1.14');S('--sy','.86');setTimeout(()=>{S('--sx','1');S('--sy','1')},120)},Math.max(120,27000/(d.bpm||120)));
        if(d.n%4===0)S('--x',SPOTS[(d.n/4)%SPOTS.length]+'vw')}lastN=d.n}
    const k=d.kick||0;              /* between beats: a hop on bass hits, a lean on snares, a twitch on hi-hats */
    if(d.n===lastN&&k>0.65&&lastK<0.5&&lastN>=0){S('--up','.28');setTimeout(()=>S('--up','0'),110)}
    lastK=k;
    if(d.snares!==lastSn&&lastSn>=0)twitch(d.snares%2?14:-14,d.snares%2?2.5:-2.5,160);
    if(d.hats!==lastHt&&lastHt>=0&&d.snares===lastSn)twitch(d.hats%2?4:-4,0,90);
    if(d.snares!==lastSn){if(lastSn>=0){const sn=D.querySelector('.sn');sn.classList.add('hit');requestAnimationFrame(()=>requestAnimationFrame(()=>sn.classList.remove('hit')));
        S('--blink','.1');setTimeout(()=>S('--blink','1'),110)}lastSn=d.snares}
    if(d.hats!==lastHt){S('--look',((d.hats%3)-1)*14+'%');lastHt=d.hats}
    D.querySelector('.t').textContent=d.bpm?d.bpm+' bpm':''}
  setTimeout(tick,d.live?70:2000)}
tick();
</script></body></html>"""


def page():
    return PAGE.replace('__BEAMS__', ''.join('<u style="--r:%ddeg"></u>' % (i * 60) for i in range(6)))
