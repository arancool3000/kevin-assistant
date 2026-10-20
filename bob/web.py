"""The settings page (service bob-assistant-web): http://<pi-name>.local:8080 on your home network.

Status, the Gemini key, wake phrase and sensitivity, voice, town, volume, the skills Kevin has made (read or
delete them), updates. Open to anyone on your home network unless you set the optional password (on this page or in
the setup app); nothing here works from outside your network unless you forward the port yourself (don't).
"""
import html
import json
import os
import secrets
import subprocess
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import actions, audio, bedside, config, experts, helper, skills, system, tools, updater, wake
from .webapp import APP, STANDBY

SESSIONS = {}
SESSION_HOURS = 24 * 30
FAILS = {}                              # client address -> recent wrong passwords: at most 10 per 10 minutes each
SETUP_CODE_FILE = os.path.join(config.ETC, 'setup-code')   # old installs only: removed on start, no longer asked for
VOSK_MODEL = os.path.join(config.STATE, 'vosk-model')
VOICES = ['Charon', 'Puck', 'Kore', 'Fenrir', 'Aoede', 'Leda', 'Orus', 'Zephyr']

CSS = """
:root{color-scheme:dark;--bg:#0b0b10;--card:rgba(255,255,255,.06);--line:rgba(255,255,255,.09);--txt:#f5f5f7;--dim:rgba(235,235,245,.6);
 --acc:#8a86ff;--brand:linear-gradient(135deg,#2f8cff,#5e5ce6 52%,#a65cf0)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(120% 60% at 10% -10%,rgba(94,92,230,.35),transparent 60%),var(--bg);
 color:var(--txt);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;min-height:100vh}
main{max-width:640px;margin:auto;padding:24px 16px 60px}h1{font-size:30px;margin:6px 0 2px}.sub{color:var(--dim);margin:0 0 18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:16px;margin:14px 0}
.card h2{font-size:15px;margin:0 0 10px;color:var(--dim);font-weight:600}
label{display:block;font-size:13px;color:var(--dim);margin:10px 0 4px}
input,select{width:100%;padding:11px 12px;border-radius:12px;border:1px solid var(--line);background:rgba(0,0,0,.25);color:var(--txt);font:inherit}
button,.btn{display:inline-block;border:0;border-radius:12px;padding:11px 16px;font:inherit;font-weight:600;color:#fff;background:var(--brand);cursor:pointer;text-decoration:none}
button.plain{background:rgba(255,255,255,.1)}button.bad{background:rgba(255,69,58,.25);color:#ff8a80}
.row{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:9px 0;border-top:1px solid var(--line)}.row:first-of-type{border-top:0}
.pill{font-size:13px;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,.1)}.ok{color:#30d158}.warn{color:#ffd60a}
pre{white-space:pre-wrap;background:rgba(0,0,0,.35);padding:12px;border-radius:12px;font-size:12.5px;overflow:auto;max-height:50vh}
.face{width:64px;height:64px;border-radius:22%;background:var(--brand);display:inline-grid;grid-auto-flow:column;gap:12px;place-content:center;vertical-align:middle;margin-right:12px}
.face i{width:8px;height:18px;border-radius:9px;background:#fff;display:block}
nav.tabs{position:sticky;top:0;z-index:5;display:flex;gap:6px;overflow-x:auto;padding:10px 0;margin:0 -16px;padding-left:16px;padding-right:16px;
 background:linear-gradient(var(--bg) 70%,transparent);scrollbar-width:none}nav.tabs::-webkit-scrollbar{display:none}
nav.tabs a{flex:none;color:var(--txt);text-decoration:none;font-size:14px;font-weight:600;padding:8px 14px;border-radius:999px;background:rgba(255,255,255,.08)}
.card h2.big{font-size:20px;color:var(--txt);margin:0 0 4px}.card{scroll-margin-top:64px}
.dev{display:flex;gap:10px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}.dev:first-child{border-top:0}
.dev .nm{flex:1;min-width:0}.dev .nm b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dev button{padding:8px 12px;font-size:14px}.bars{font-size:12px;color:var(--dim)}
.toggle{display:flex;align-items:center;gap:10px;margin:12px 0 4px;font-size:15px;color:var(--txt)}.toggle input{width:auto}
.savebar{position:sticky;bottom:0;padding:12px 0;background:linear-gradient(transparent,var(--bg) 40%)}.savebar button{width:100%}
.note{font-size:14px;color:var(--dim);min-height:1.2em;margin:8px 0 0}
"""


def page(title, body):
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style><main>%s</main>' % (html.escape(title), CSS, body))


def esc(x):
    return html.escape(str(x if x is not None else ''))


def bob_state():
    try:
        with open(os.path.join(config.STATE, 'state.json')) as f:
            d = json.load(f)
        return d.get('state', '?'), d.get('phrase')
    except (OSError, ValueError):
        return 'starting', None


def _allowed_hosts():
    import socket
    names = {'localhost', '127.0.0.1', socket.gethostname().lower(), socket.gethostname().lower() + '.local'}
    try:
        names.update(subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=3).stdout.split())
    except Exception:
        pass
    return names


def _num(v, lo, hi, default):
    try:
        x = float(v)
        if x != x or x in (float('inf'), float('-inf')):
            return default
        return int(max(lo, min(hi, x)))
    except (TypeError, ValueError):
        return default


def _diff_html(d):
    rows = []
    for line in d.splitlines():
        col = '#2e9e57' if line.startswith('+') and not line.startswith('+++') else (
            '#c94040' if line.startswith('-') and not line.startswith('---') else '')
        rows.append('<span style="color:%s">%s</span>' % (col, esc(line)) if col else esc(line))
    return '<pre>%s</pre>' % '\n'.join(rows)


def _access_html(access):
    risky = set(skills.SENSITIVE)
    return ('<ul style="margin:6px 0 4px 18px;padding:0">%s</ul><p class="sub">%s</p>' % (
        ''.join('<li>%s%s</li>' % (esc(a), ' <span class="pill warn">check</span>' if a in risky else '') for a in access),
        esc(skills.BOUNDARY)))


def password_card(sec):
    """Optional: with no password anyone on the home network can open this page."""
    if sec.get('web_password'):
        return ('<form method="post" action="/password" class="card"><h2>Page password</h2><label>Current password</label>'
                '<input type="password" name="current"><label>New password (leave empty to remove it)</label>'
                '<input type="password" name="password"><p><button class="plain">Change</button></p></form>')
    return ('<form method="post" action="/password" class="card"><h2>Page password</h2><p class="sub">Off: anyone on your home '
            'Wi-Fi can open this page. Set one if others share your network.</p><label>New password</label>'
            '<input type="password" name="password" minlength="6"><p><button class="plain">Set password</button></p></form>')


def pending_cards():
    """Skills waiting for a yes: the exact code (or what changes), what it reaches for, Approve / Reject."""
    out = []
    for d in skills.pending():
        body = ('<p class="sub">What changes from the installed version:</p>' + _diff_html(d['diff'])) if d.get('diff') else (
            '<p class="sub">The code:</p><pre>%s</pre>' % esc(d['code']))
        out.append(
            '<div class="card" style="border:2px solid #d9a400"><h2>Waiting for your yes: %s</h2>'
            '<p><b>What it can reach</b> (read from the code itself):</p>%s%s'
            '<form method="post" action="/skill-approve" style="display:inline"><input type="hidden" name="name" value="%s">'
            '<input type="hidden" name="sha" value="%s"><button>Approve and install</button></form> '
            '<form method="post" action="/skill-reject" style="display:inline"><input type="hidden" name="name" value="%s">'
            '<button class="plain">Reject</button></form></div>' % (
                esc(d['name']), _access_html(d.get('access') or []), body, esc(d['name']), esc(d['sha']), esc(d['name'])))
    return ''.join(out)


def service_enabled(name):
    r = subprocess.run(['systemctl', 'is-enabled', name], capture_output=True, text=True)
    return r.stdout.strip() == 'enabled'


def helper_card():
    """The "Help run KindleHub" switch (bob/helper.py). Off unless the owner turns it on."""
    on = service_enabled('bob-assistant-helper')
    st = helper.read_status() if on else {}
    what = ('<p class="sub">Lend this Pi\'s spare time to KindleHub (free games for e-readers): it plays chess moves '
            'for KindleHub\'s computer opponent, and nothing else. One move at a time, at most half of one CPU core, '
            'lowest priority, so Kevin always comes first. It connects out and opens no ports, and runs as its own user '
            'with no access to Kevin\'s key or your files.</p>'
            '<p class="sub">Perk: link this Pi to your KindleHub account. While it has played moves for KindleHub in '
            '10 different hours of the last week, your account gets KindleTube and KindlePoki as on the Plus plan.</p>')
    if not on:
        return ('<form method="post" action="/helper" class="card"><h2>Help run KindleHub</h2>%s'
                '<div class="row"><span>Status</span><span class="pill">off</span></div>'
                '<input type="hidden" name="on" value="1"><p><button class="plain">Switch on</button></p></form>') % what
    if st.get('connected'):
        state = '<span class="pill ok">helping</span>'
    elif st.get('problem'):
        state = '<span class="pill warn">%s</span>' % esc(st['problem'])
    else:
        state = '<span class="pill warn">connecting</span>'
    link = ''
    if st.get('link_code') and not st.get('linked'):
        link = ('<div class="row"><span>Link code</span><b>%s</b></div><p class="sub">For the perks: in KindleHub open '
                'Settings, then Helper Pi, and enter this code.</p>') % esc(st['link_code'])
    elif st.get('linked'):
        link = '<div class="row"><span>KindleHub account</span><span class="pill ok">linked</span></div>'
    return ('<form method="post" action="/helper" class="card"><h2>Help run KindleHub</h2>%s'
            '<div class="row"><span>Status</span>%s</div>%s'
            '<input type="hidden" name="on" value="0"><p><button class="plain">Switch off</button></p></form>') % (what, state, link)


def service_active(name):
    r = subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True)
    return r.stdout.strip()


class Handler(BaseHTTPRequestHandler):
    server_version = 'bob'

    def log_message(self, *a):
        pass

    # -- helpers --
    def _send(self, code, body, ctype='text/html; charset=utf-8', headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to, headers=None):
        h = {'Location': to}
        h.update(headers or {})
        self._send(303, '', headers=h)

    def _cookie(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'bob':
                return v
        return ''

    def _signed_in(self):
        # No password set = open on the home network. A setup code printed only by the installer locked out everyone who
        # used the setup app and never saw a terminal (19 Oct 2026); the password is now optional.
        if not config.load_secrets().get('web_password'):
            return True
        exp = SESSIONS.get(self._cookie())
        return bool(exp and exp > time.time())

    def _form(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return {}
        if n <= 0 or n > 200000:
            return {}
        try:
            return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode('utf-8', 'replace')).items()}
        except Exception:
            return {}

    def _host_ok(self):
        """Only answer to the Pi's own names and addresses (stops a web page using DNS tricks to reach us)."""
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]').lower()
        return host in _allowed_hosts()

    def _same_origin(self):
        o = self.headers.get('Origin')
        return not o or o.split('//', 1)[-1] == self.headers.get('Host')

    # -- pages --
    def do_GET(self):
        if not self._host_ok():
            return self._send(421, 'unknown host')
        path = self.path.split('?')[0]
        sec = config.load_secrets()
        if path == '/login' and not sec.get('web_password'):
            return self._redirect('/')
        if path == '/login' or not self._signed_in():
            return self._send(200, self.login())
        if path == '/skill':
            name = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('name', [''])[0]
            src = skills.source(name)
            try:
                vs = skills.versions(name)
            except ValueError:
                vs = []
            vhtml = ''.join(
                '<details><summary>Version from %s</summary>%s<form method="post" action="/skill-rollback">'
                '<input type="hidden" name="name" value="%s"><input type="hidden" name="version" value="%s">'
                '<button class="plain">Put this version back</button></form></details>' % (
                    esc(v['when']), _diff_html(skills.diff(v['code'], src or '')) if src else '<pre>%s</pre>' % esc(v['code']),
                    esc(name), esc(v['id'])) for v in vs) or '<p class="sub">No earlier versions.</p>'
            state = '' if src is None else ('' if skills.is_enabled(name) else ' <span class="pill warn">switched off</span>')
            return self._send(200, page(name, (
                '<p><a class="btn plain" href="/">Back</a></p><h1>%s%s</h1>'
                '<div class="card"><h2>What it can reach</h2>%s</div>'
                '<div class="card"><h2>Code</h2><pre>%s</pre></div>'
                '<div class="card"><h2>Earlier versions</h2><p class="sub">Each shows what changed since it. The last %d are kept.</p>%s</div>') % (
                esc(name), state, _access_html(skills.access_report(src)) if src else '<p class="sub">not installed</p>',
                esc(src or 'not found'), skills.KEEP_VERSIONS, vhtml)))
        if path == '/api/live':
            return self._send(200, json.dumps(actions.live()), 'application/json')
        if path == '/settings':
            return self._send(200, self.settings())
        if path == '/api/bt':
            return self._send(200, json.dumps(system.bt_devices()), 'application/json')
        if path == '/api/wifi':
            return self._send(200, json.dumps(system.wifi_status('rescan' in self.path)), 'application/json')
        if path == '/app':
            return self._send(200, APP)
        if path == '/standby':
            return self._send(200, STANDBY)
        if path == '/log':
            try:
                with open(updater.LOG) as f:
                    tail = f.read()[-6000:]
            except OSError:
                tail = 'No updates yet.'
            return self._send(200, page('Updates', '<p><a class="btn plain" href="/">Back</a></p><h1>Update log</h1><pre>%s</pre>' % esc(tail)))
        return self._send(200, self.home())

    def do_POST(self):
        if not self._host_ok() or not self._same_origin():
            return self._send(403, 'not from this page')
        try:
            return self._post()
        except Exception as e:
            return self._send(400, 'that did not work: %s' % esc(str(e)[:120]))

    def _post(self):
        path = self.path.split('?')[0]
        f = self._form()
        sec = config.load_secrets()
        if path == '/login':
            now = time.time()
            who = self.client_address[0] if self.client_address else '?'
            for k in list(FAILS):
                FAILS[k] = [t for t in FAILS[k] if now - t < 600]
                if not FAILS[k]:
                    del FAILS[k]
            if len(FAILS.get(who, [])) >= 10 or sum(len(v) for v in FAILS.values()) >= 100:
                return self._send(429, self.login('Too many tries: wait ten minutes.'))
            for k in [k for k, exp in SESSIONS.items() if exp < now]:
                del SESSIONS[k]
            if config.check_password(f.get('password', ''), sec.get('web_password', '')):
                tok = secrets.token_urlsafe(24)
                SESSIONS[tok] = time.time() + SESSION_HOURS * 3600
                return self._redirect('/', {'Set-Cookie': 'bob=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d' % (tok, SESSION_HOURS * 3600)})
            FAILS.setdefault(who, []).append(now)
            time.sleep(1)
            return self._send(200, self.login('Wrong password.'))
        if not self._signed_in():
            return self._redirect('/login')
        if path == '/api/act':                       # the phone page and StandBy buttons
            what, arg = f.get('what', ''), f.get('arg', '')
            if what == 'talk':
                r = actions.talk()
            elif what == 'timer':
                r = actions.timer(arg, f.get('which', ''))
            elif what == 'music':
                r = actions.music_action(arg)
            elif what == 'quick_timer':
                from . import timers as _timers
                t = _timers.add_timer(_num(arg, 1, 600, 5) * 60, f.get('name') or None)
                r = {'ok': True, 'name': t['name']}
            else:
                r = {'ok': False, 'error': 'unknown action'}
            return self._send(200, json.dumps(r), 'application/json')
        if path in ('/api/bt', '/api/wifi', '/api/sound-test'):   # the settings page's Bluetooth, Wi-Fi and Sound cards
            try:
                act = f.get('act', '')
                if path == '/api/bt':
                    {'scan': lambda: system.bt_scan(), 'connect': lambda: system.bt_connect(f.get('address')),
                     'disconnect': lambda: system.bt_disconnect(f.get('address')),
                     'forget': lambda: system.bt_forget(f.get('address'))}[act]()
                    out = {'ok': True}
                elif path == '/api/wifi':
                    {'join': lambda: system.wifi_join(f.get('ssid'), f.get('password', '')),
                     'forget': lambda: system.wifi_forget(f.get('ssid'))}[act]()
                    out = {'ok': True}
                else:
                    ok, why = system.test_tone(f.get('device'))
                    out = {'ok': ok, 'error': '' if ok else (why or 'no sound device')}
            except (KeyError, ValueError) as e:
                out = {'ok': False, 'error': str(e) if isinstance(e, ValueError) else 'unknown action'}
            return self._send(200, json.dumps(out), 'application/json')
        if path == '/settings':
            cfg = config.load()
            for k in ('name', 'personality', 'language'):
                if k in f:
                    cfg[k] = f[k].strip()[:300]
            if f.get('voice') in VOICES:
                cfg['voice'] = f['voice']
            for k in ('mic_device', 'speaker_device'):
                if k in f:
                    cfg[k] = audio.safe_device(f[k].strip())
            if f.get('wake_phrase', '').strip():
                phrase = ' '.join(f['wake_phrase'].lower().replace(',', ' ').split())
                why = wake.check_phrase(phrase, VOSK_MODEL)
                if why:
                    return self._send(200, page('Kevin', '<p class="warn">Wake phrase not changed: %s.</p><p><a class="btn" href="/">Back</a></p>' % esc(why)))
                cfg['wake_phrase'] = phrase
            cfg['wake_sensitivity'] = _num(f.get('wake_sensitivity'), 20, 90, cfg['wake_sensitivity'])
            cfg['volume'] = _num(f.get('volume'), 0, 100, cfg['volume'])
            cfg['idle_seconds'] = _num(f.get('idle_seconds'), 5, 60, cfg['idle_seconds'])
            cfg['auto_update'] = f.get('auto_update') == 'on'
            if 'bedside_serial' in f:
                cfg['bedside_serial'] = ''.join(c for c in f['bedside_serial'] if c.isalnum() or c in '_-')[:40]
            for k, lo, hi in (('quiet_from', 0, 23), ('quiet_to', 0, 23), ('music_volume', 0, 100)):
                if f.get(k, '') != '':
                    cfg[k] = _num(f.get(k), lo, hi, cfg[k])
            cfg['quiet_enabled'] = f.get('quiet_enabled') == 'on'
            cfg['skill_approval'] = 'page' if f.get('skill_approval') == 'page' else 'voice'
            if f.get('town', '').strip() != cfg.get('town'):
                cfg['town'] = f.get('town', '').strip()[:100]
                cfg.update(latitude=None, longitude=None)
                if cfg['town']:
                    try:
                        lat, lon, tz, _label = tools.geocode(cfg['town'])
                        cfg.update(latitude=lat, longitude=lon, timezone=tz)
                    except Exception:
                        pass
            config.save(cfg)
            if f.get('api_key', '').strip():
                sec['gemini_api_key'] = f['api_key'].strip()
                config.save_secrets(sec)
            subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'restart', 'bob-assistant'], capture_output=True)
            return self._redirect('/settings?saved=1')
        if path == '/ai-connect':                      # your own Claude / ChatGPT account (docs/AI-ACCOUNTS.md)
            try:
                if f.get('claude_token', '').strip():
                    tok = f['claude_token'].strip()
                    if not tok.startswith('sk-ant-') or len(tok) < 40:
                        raise ValueError('that does not look like a token from "claude setup-token" (it starts sk-ant-)')
                    sec['claude_token'] = tok
                    config.save_secrets(sec)
                if f.get('chatgpt_auth', '').strip():
                    experts.save_chatgpt_signin(f['chatgpt_auth'])
            except ValueError as e:
                return self._send(200, page('Kevin', '<p class="warn">%s</p><p><a class="btn" href="/">Back</a></p>' % esc(e)))
            return self._redirect('/')
        if path == '/ai-forget':
            experts.forget(f.get('which', ''))
            return self._redirect('/')
        if path == '/helper':                          # "Help run KindleHub": off by default, on only when asked
            verb = 'enable' if f.get('on') == '1' else 'disable'
            subprocess.run(['sudo', '-n', '/usr/bin/systemctl', verb, '--now', 'bob-assistant-helper.service'],
                           capture_output=True, timeout=60)
            return self._redirect('/')
        if path == '/delete-skill':
            skills.delete(f.get('name', ''))
            return self._redirect('/')
        if path == '/skill-approve':
            try:
                skills.approve(f.get('name', ''), f.get('sha', ''))
            except ValueError as e:
                return self._send(200, page('Kevin', '<p class="warn">%s</p><p><a class="btn" href="/">Back</a></p>' % esc(e)))
            return self._redirect('/')
        if path == '/skill-reject':
            try:
                skills.clear_pending(f.get('name', ''), rejected=True)
            except ValueError:
                pass
            return self._redirect('/')
        if path == '/skill-toggle':
            try:
                skills.set_enabled(f.get('name', ''), f.get('on') == '1')
            except ValueError:
                pass
            return self._redirect('/')
        if path == '/skill-rollback':
            try:
                skills.rollback(f.get('name', ''), f.get('version') or None)
            except ValueError as e:
                return self._send(200, page('Kevin', '<p class="warn">%s</p><p><a class="btn" href="/">Back</a></p>' % esc(e)))
            return self._redirect('/skill?name=' + urllib.parse.quote(f.get('name', '')))
        if path == '/update':
            subprocess.Popen(['sudo', '-n', '/usr/bin/systemctl', 'start', '--no-block', 'bob-assistant-update-now.service'])
            return self._redirect('/log')
        if path == '/password':
            had = sec.get('web_password')
            if had and not config.check_password(f.get('current', ''), had):
                return self._send(200, page('Kevin', '<p class="warn">Current password is not right.</p><p><a class="btn" href="/">Back</a></p>'))
            new = f.get('password', '')
            if new and len(new) < 6:
                return self._send(200, page('Kevin', '<p class="warn">Use at least 6 characters (or leave it empty for no password).</p><p><a class="btn" href="/">Back</a></p>'))
            sec['web_password'] = config.hash_password(new) if new else ''
            config.save_secrets(sec)
            SESSIONS.clear()
            return self._redirect('/login' if new else '/')
        return self._send(404, 'not found')

    # -- views --
    def login(self, err=''):
        return page('Kevin', '<h1><span class="face"><i></i><i></i></span>Kevin</h1><form method="post" action="/login" class="card">'
                    '<label>Password</label><input type="password" name="password" autofocus><p class="warn">%s</p>'
                    '<button>Sign in</button></form>' % esc(err))

    def home(self):
        cfg, sec = config.load(), config.load_secrets()
        pi_st = {}
        try:
            pi_st = tools.pi_status()
        except Exception:
            pass
        st, active_phrase = bob_state()
        sk, bad = skills.load_all()
        state_txt = {'asleep': 'Listening for "%s"' % (active_phrase or cfg['wake_phrase']), 'listening': 'In a conversation',
                     'speaking': 'Speaking', 'working': 'Using a tool', 'needs_setup': 'Needs your Gemini key'}.get(st, st)
        def _row(n, desc, on):
            return ('<div class="row"><span><b>%s</b>%s<br><span class="sub">%s</span></span><span><a class="btn plain" href="/skill?name=%s">Code &amp; versions</a> '
                    '<form method="post" action="/skill-toggle" style="display:inline"><input type="hidden" name="name" value="%s">'
                    '<input type="hidden" name="on" value="%s"><button class="plain">%s</button></form> '
                    '<form method="post" action="/delete-skill" style="display:inline" onsubmit="return confirm(\'Delete %s?\')">'
                    '<input type="hidden" name="name" value="%s"><button class="bad">Delete</button></form></span></div>') % (
                esc(n), '' if on else ' <span class="pill warn">off</span>', esc(desc), esc(n), esc(n), '0' if on else '1',
                'Switch off' if on else 'Switch on', esc(n), esc(n))
        skills_html = ''.join(_row(s['name'], s['description'], True) for s in sk) + \
            ''.join(_row(n, 'switched off: not loaded until you switch it on', False) for n in skills.disabled_names())
        skills_html = skills_html or '<p class="sub">None yet. Wire something to the Pi and say: "Hey Kevin, make a skill for it." A good first one: "Hey Kevin, install the example temperature skill."</p>'
        if bad:
            skills_html += ''.join('<p class="warn">%s is broken: %s</p>' % (esc(b['name']), esc(b['problem'])) for b in bad)
        nokey = '' if sec.get('gemini_api_key') else (
            '<div class="card"><h2 class="big warn">Kevin needs a Gemini key</h2><p class="sub">Until it is added he cannot answer. '
            'Get a free one at aistudio.google.com/apikey and paste it under Settings, Accounts.</p>'
            '<a class="btn" href="/settings#accounts">Add the key</a></div>')
        return page('Kevin', (
            '<h1><span class="face"><i></i><i></i></span>%s</h1><p class="sub">%s · version %s</p>'
            '<p><a class="btn" href="/settings">Settings</a> <a class="btn plain" href="/app">Remote</a> <a class="btn plain" href="/standby">StandBy clock</a></p>'
            '%s%s'
            '<div class="card"><h2>Status</h2>'
            '<div class="row"><span>Kevin</span><span class="pill %s">%s</span></div>'
            '<div class="row"><span>Gemini key</span><span class="pill %s">%s</span></div>'
            '<div class="row"><span>Pi</span><span class="sub">%s°C · %s GB free · %s</span></div></div>'
            '<div class="card"><h2>Skills Kevin has made</h2>%s</div>'
            '<div class="card"><h2>Updates</h2><form method="post" action="/update" style="display:inline"><button class="plain">Check now</button></form> '
            '<a class="btn plain" href="/log">Update log</a></div>') % (
                esc(cfg['name']), esc(pi_st.get('ip') or ''), esc(pi_st.get('version', '?')), nokey, pending_cards(),
                'ok' if st in ('asleep', 'listening', 'speaking', 'working') else 'warn', esc(state_txt),
                'ok' if sec.get('gemini_api_key') else 'warn', 'set' if sec.get('gemini_api_key') else 'missing',
                esc(pi_st.get('cpu_temp_c', '?')), esc(pi_st.get('disk_free_gb', '?')), esc(service_active('bob-assistant')),
                skills_html))

    def settings(self):
        cfg, sec = config.load(), config.load_secrets()
        saved = 'saved=1' in self.path
        voice_opts = ''.join('<option%s>%s</option>' % (' selected' if v == cfg['voice'] else '', v) for v in VOICES)
        try:
            snd = system.sound_devices()
        except Exception:
            snd = {'speakers': [], 'mics': []}

        def opts(rows, cur):
            names = [r['name'] for r in rows]
            if cur and cur not in names:
                rows = rows + [{'name': cur, 'label': '%s (not plugged in now)' % cur}]
            rows = rows or [{'name': 'default', 'label': 'default'}]
            return ''.join('<option value="%s"%s>%s</option>' % (esc(r['name']), ' selected' if r['name'] == cur else '',
                                                                   esc(r['label'] if r['label'] != r['name'] else r['name'])) for r in rows)
        sect = lambda id_, title, sub, body: ('<div class="card" id="%s"><h2 class="big">%s</h2><p class="sub">%s</p>%s</div>'
                                               % (id_, title, sub, body))
        chk = lambda name, on, text: '<label class="toggle"><input type="checkbox" name="%s"%s> %s</label>' % (name, ' checked' if on else '', text)
        form = (
            '<form method="post" action="/settings" id="cfg">'
            + sect('kevin', 'Kevin', 'How he sounds and when he listens.',
                   '<label>Name</label><input name="name" value="%s">' % esc(cfg['name'])
                   + '<label>Wake phrase</label><input name="wake_phrase" value="%s">' % esc(cfg['wake_phrase'])
                   + '<label>Wake sensitivity: <b id="ws">%s</b> (higher wakes more easily, and more by mistake)</label>'
                     '<input type="range" name="wake_sensitivity" min="20" max="90" value="%s" oninput="ws.textContent=this.value">' % (
                       esc(cfg['wake_sensitivity']), esc(cfg['wake_sensitivity']))
                   + '<label>Voice</label><select name="voice">%s</select>' % voice_opts
                   + '<label>Personality</label><input name="personality" value="%s">' % esc(cfg['personality'])
                   + '<label>Language (e.g. en-GB, en-US)</label><input name="language" value="%s">' % esc(cfg['language'])
                   + '<label>Seconds he waits for you before going back to sleep</label>'
                     '<input type="number" name="idle_seconds" min="5" max="60" value="%s">' % esc(cfg['idle_seconds'])
                   + '<label>Town (for the weather)</label><input name="town" value="%s">' % esc(cfg['town']))
            + sect('sound', 'Sound', 'Which speaker and microphone Kevin uses. A Bluetooth speaker appears here once it is connected (below).',
                   '<label>Speaker</label><select name="speaker_device" id="spk">%s</select>' % opts(snd['speakers'], cfg['speaker_device'])
                   + '<p><button type="button" class="plain" onclick="testSpk()">Play a test sound</button></p><p class="note" id="spk-note"></p>'
                   + '<label>Microphone</label><select name="mic_device">%s</select>' % opts(snd['mics'], cfg['mic_device'])
                   + '<label>Kevin\'s volume</label><input type="range" name="volume" min="0" max="100" value="%s">' % esc(cfg['volume'])
                   + '<label>Music volume</label><input type="range" name="music_volume" min="0" max="100" value="%s">' % esc(cfg.get('music_volume', 60)))
            + '@@BT@@@@WIFI@@'
            + sect('quiet', 'Quiet hours', 'Softer chimes and a dim bedside screen. Alarms still ring.',
                   chk('quiet_enabled', cfg.get('quiet_enabled', True), 'Quiet hours on')
                   + '<label>From (hour, 0-23)</label><input type="number" name="quiet_from" min="0" max="23" value="%s">' % esc(cfg.get('quiet_from', 22))
                   + '<label>Until (hour, 0-23)</label><input type="number" name="quiet_to" min="0" max="23" value="%s">' % esc(cfg.get('quiet_to', 7)))
            + sect('accounts', 'Accounts', 'Kevin\'s Gemini key is %s.' % ('<span class="ok">set</span>' if sec.get('gemini_api_key') else '<span class="warn">missing: he cannot answer until you add it</span>'),
                   '<label>New Gemini API key (free from aistudio.google.com/apikey; leave empty to keep the current one)</label>'
                   '<input name="api_key" autocomplete="off">')
            + sect('devices', 'Bedside screen', 'Optional: see examples/bedside-screen.',
                   '<label>USB serial number (empty = none). Plugged in now: %s</label><input name="bedside_serial" value="%s">' % (
                       esc(', '.join(bedside.devices()) or 'no USB serial devices'), esc(cfg.get('bedside_serial', ''))))
            + sect('safety', 'Skills and updates', 'What Kevin may change by himself.',
                   '<label>Approving new skills</label><select name="skill_approval"><option value="voice"%s>A spoken yes, or Approve on the home page</option>'
                   '<option value="page"%s>Only Approve on the home page (after reading the code)</option></select>' % (
                       '' if cfg.get('skill_approval') == 'page' else ' selected', ' selected' if cfg.get('skill_approval') == 'page' else '')
                   + chk('auto_update', cfg.get('auto_update'), 'Install updates automatically'))
            + '<div class="savebar"><button>Save settings</button></div></form>')
        bt = sect('bluetooth', 'Bluetooth', 'Pair a speaker or headphones. Put the device in pairing mode first.',
                  '<div id="bt-list"><p class="sub">Loading…</p></div><p><button type="button" id="bt-scan" onclick="btScan()">Find devices</button></p>'
                  '<p class="note" id="bt-note"></p>')
        wifi = sect('wifi', 'Wi-Fi', 'Kevin needs a 2.4 or 5 GHz home network with a normal password (not a hotel or school login page).',
                    '<div id="wifi-list"><p class="sub">Loading…</p></div><p><button type="button" class="plain" onclick="wifiLoad(1)">Scan again</button></p>'
                    '<p class="note" id="wifi-note"></p>')
        body = (('<p><a class="btn plain" href="/">‹ Kevin</a></p><h1>Settings</h1>%s'
                 '<nav class="tabs"><a href="#kevin">Kevin</a><a href="#sound">Sound</a><a href="#bluetooth">Bluetooth</a><a href="#wifi">Wi-Fi</a>'
                 '<a href="#quiet">Quiet hours</a><a href="#accounts">Accounts</a><a href="#devices">Devices</a><a href="#safety">Skills</a>'
                 '<a href="#password">Password</a><a href="#extras">Extras</a></nav>') % (
                     '<p class="pill ok">Saved. Kevin is restarting.</p>' if saved else '')
                + form.replace('@@BT@@', bt).replace('@@WIFI@@', wifi)   # no named inputs in these two: the one form still saves everything
                + '<div id="password">' + password_card(sec) + '</div><div id="extras">' + ai_card() + helper_card() + '</div>'
                + '<script>' + SETTINGS_JS + '</script>')
        return page('Kevin settings', body)


SETTINGS_JS = r"""
const $=id=>document.getElementById(id),E=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function post(u,d){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(d)});return r.json()}
async function testSpk(){$('spk-note').textContent='Playing…';const r=await post('/api/sound-test',{device:$('spk').value});
  $('spk-note').textContent=r.ok?'Did you hear a beep? If not, pick another speaker.':'No sound: '+r.error}
let btT=0;
async function btLoad(){let d;try{d=await (await fetch('/api/bt')).json()}catch(e){$('bt-list').innerHTML='<p class="warn">Could not ask the Pi.</p>';return}
  if(!d.available){$('bt-list').innerHTML='<p class="warn">No Bluetooth on this Pi (or it is switched off).</p>';$('bt-scan').hidden=true;return}
  $('bt-list').innerHTML=d.devices.length?d.devices.map(x=>'<div class="dev"><div class="nm"><b>'+E(x.name)+'</b><span class="bars">'
    +(x.connected?'<span class="ok">connected</span>':x.paired?'paired':'found')+' · '+E(x.kind)+'</span></div>'
    +(x.connected?'<button type="button" class="plain" onclick="bt(\'disconnect\',\''+x.address+'\')">Disconnect</button>'
      :'<button type="button" onclick="bt(\'connect\',\''+x.address+'\')">Connect</button>')
    +(x.paired?'<button type="button" class="bad" onclick="if(confirm(\'Forget '+E(x.name).replace(/'/g,'')+'?\'))bt(\'forget\',\''+x.address+'\')">Forget</button>':'')
    +'</div>').join(''):'<p class="sub">Nothing yet. Press Find devices.</p>';
  $('bt-scan').disabled=d.scanning;$('bt-scan').textContent=d.scanning?'Looking…':'Find devices';
  $('bt-note').textContent=d.busy?d.busy[0].toUpperCase()+d.busy.slice(1)+'…':(d.last||'');
  clearTimeout(btT);btT=setTimeout(btLoad,d.scanning||d.busy?1500:8000)}
async function btScan(){await post('/api/bt',{act:'scan'});btLoad()}
async function bt(act,a){const r=await post('/api/bt',{act:act,address:a});if(!r.ok)$('bt-note').textContent=r.error;btLoad()}
let wfT=0;
async function wifiLoad(rescan){if(rescan)$('wifi-note').textContent='Scanning…';let d;
  try{d=await (await fetch('/api/wifi'+(rescan?'?rescan=1':''))).json()}catch(e){$('wifi-list').innerHTML='<p class="warn">Could not ask the Pi.</p>';return}
  if(!d.available){$('wifi-list').innerHTML='<p class="warn">'+E(d.last)+'</p>';return}
  $('wifi-list').innerHTML=d.networks.map(n=>'<div class="dev"><div class="nm"><b>'+E(n.ssid)+'</b><span class="bars">'
    +(n.in_use?'<span class="ok">connected</span> · ':'')+n.signal+'% signal'+(n.secure?' · password':' · open')
    +(d.saved.includes(n.ssid)&&!n.in_use?' · saved':'')+'</span></div>'
    +(n.in_use?'':'<button type="button" onclick="wifiJoin(\''+encodeURIComponent(n.ssid)+'\','+n.secure+')">Join</button>')
    +(d.saved.includes(n.ssid)&&!n.in_use?'<button type="button" class="bad" onclick="wifi(\'forget\',\''+encodeURIComponent(n.ssid)+'\')">Forget</button>':'')
    +'</div>').join('')||'<p class="sub">No networks found.</p>';
  $('wifi-note').textContent=d.busy?d.busy[0].toUpperCase()+d.busy.slice(1)+'…':(d.last||'');
  clearTimeout(wfT);if(d.busy)wfT=setTimeout(wifiLoad,2000)}
async function wifiJoin(s,secure){s=decodeURIComponent(s);let pw='';
  if(secure){pw=prompt('Password for '+s+' (capitals matter)');if(pw===null)return}
  const r=await post('/api/wifi',{act:'join',ssid:s,password:pw});$('wifi-note').textContent=r.ok?'Joining '+s+'…':r.error;setTimeout(wifiLoad,1500)}
async function wifi(act,s){s=decodeURIComponent(s);if(act==='forget'&&!confirm('Forget '+s+'?'))return;
  const r=await post('/api/wifi',{act:act,ssid:s});$('wifi-note').textContent=r.ok?'':r.error;wifiLoad()}
btLoad();wifiLoad(0);
"""


def ai_card():
    """Connect your own Claude / ChatGPT account (optional)."""
    st = experts.status()

    def row(key, label, how):
        s = st[key]
        state = ('<span class="pill ok">connected</span> <form method="post" action="/ai-forget" style="display:inline">'
                 '<input type="hidden" name="which" value="%s"><button class="plain">Disconnect</button></form>' % key) if s['connected'] else \
            '<span class="pill %s">%s</span>' % ('warn', 'not installed' if not s['installed'] else 'not connected')
        return '<div class="row"><span><b>%s</b><br><span class="sub">%s</span></span><span>%s</span></div>' % (label, how, state)
    return ('<div class="card"><h2>Your Claude or ChatGPT account (optional)</h2>'
            '<p class="sub">For hard questions Kevin can ask your own Claude or ChatGPT subscription. They only answer: no files, no '
            'commands. Step by step: docs/AI-ACCOUNTS.md on GitHub.</p>%s%s'
            '<form method="post" action="/ai-connect"><label>Claude: paste the token from <code>claude setup-token</code></label>'
            '<input name="claude_token" autocomplete="off" placeholder="sk-ant-...">'
            '<label>ChatGPT: paste the contents of <code>~/.codex/auth.json</code> after <code>codex login</code></label>'
            '<textarea name="chatgpt_auth" rows="3" autocomplete="off" placeholder="{...}" style="width:100%%;border-radius:12px;background:rgba(0,0,0,.25);color:inherit;border:1px solid var(--line);padding:10px"></textarea><p><button class="plain">Connect</button></p></form></div>') % (
        row('claude', 'Claude', 'Claude Code, with your Claude Pro or Max plan'),
        row('chatgpt', 'ChatGPT', 'Codex, with your ChatGPT Plus or Pro plan'))


def main():
    cfg = config.load()
    srv = ThreadingHTTPServer(('0.0.0.0', int(cfg.get('web_port', 8080))), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == '__main__':
    main()
