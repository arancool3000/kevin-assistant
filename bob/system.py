"""Bluetooth, Wi-Fi and sound devices for the settings page, through the Pi's own tools.

  Bluetooth  bluetoothctl (BlueZ). Speakers play through bluez-alsa: their ALSA name is
             bluealsa:DEV=<address>,PROFILE=a2dp, which the Sound section offers once one is connected.
  Wi-Fi      nmcli (NetworkManager). A polkit rule from install.sh lets Kevin's user manage it.
             Joining a new network that fails switches back to the one that worked.
  Sound      aplay -L / arecord -L, so the page offers a list instead of a box to type names into.

Every value that reaches a command is checked first (addresses, network names), and nothing goes through a shell.
"""
import re
import subprocess
import threading
import time

MAC_RE = re.compile(r'^[0-9A-F]{2}(:[0-9A-F]{2}){5}$')
BT_STATE = {'scanning_until': 0.0, 'busy': '', 'last': ''}
WIFI_STATE = {'busy': '', 'last': ''}
_lock = threading.Lock()


def _run(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except FileNotFoundError:
        return 127, '%s is not installed' % args[0]
    except subprocess.TimeoutExpired:
        return 124, 'timed out'


def mac(x):
    m = str(x or '').strip().upper()
    if not MAC_RE.match(m):
        raise ValueError('that is not a Bluetooth address')
    return m


# ---------- Bluetooth ----------
def bt_available():
    code, out = _run(['bluetoothctl', 'show'], 8)
    return code == 0 and 'Controller' in out


def _bt_info(m):
    _c, out = _run(['bluetoothctl', 'info', m], 8)
    get = lambda k: (re.search(r'^\s*%s:\s*(.+)$' % k, out, re.M) or [None, ''])[1].strip()
    icon = get('Icon')
    return {'paired': get('Paired') == 'yes', 'connected': get('Connected') == 'yes', 'trusted': get('Trusted') == 'yes',
            'kind': 'headphones' if 'headphone' in icon else 'speaker' if icon.startswith('audio') else (icon or 'device')}


def bt_devices():
    """Every device BlueZ knows (paired ones and ones found by the last scan), connected first."""
    _c, out = _run(['bluetoothctl', 'devices'], 8)
    rows = []
    for line in out.splitlines():
        m = re.match(r'^Device ([0-9A-F:]{17}) (.*)$', line.strip())
        if not m:
            continue
        addr, name = m.group(1), m.group(2).strip()
        if name.replace('-', ':') == addr:
            name = ''
        d = {'address': addr, 'name': name or 'Unnamed device'}
        d.update(_bt_info(addr))
        rows.append(d)
    rows.sort(key=lambda d: (not d['connected'], not d['paired'], d['name'].lower()))
    return {'available': bt_available(), 'scanning': time.time() < BT_STATE['scanning_until'],
            'busy': BT_STATE['busy'], 'last': BT_STATE['last'], 'devices': rows}


def bt_scan(seconds=12):
    """Look for devices for a few seconds (in the background: the page polls bt_devices)."""
    if time.time() < BT_STATE['scanning_until']:
        return
    BT_STATE['scanning_until'] = time.time() + seconds
    _run(['bluetoothctl', 'power', 'on'], 8)
    threading.Thread(target=_run, args=(['bluetoothctl', '--timeout', str(seconds), 'scan', 'on'], seconds + 5),
                     daemon=True).start()


def _bt_job(label, fn):
    def go():
        with _lock:
            BT_STATE['busy'] = label
            try:
                BT_STATE['last'] = fn()
            except Exception as e:
                BT_STATE['last'] = 'That did not work: %s' % e
            BT_STATE['busy'] = ''
    threading.Thread(target=go, daemon=True).start()


def bt_connect(addr):
    """Pair (no PIN: speakers and headphones), trust so it reconnects by itself, then connect."""
    m = mac(addr)

    def go():
        if not _bt_info(m)['paired']:
            code, out = _run(['bluetoothctl', '--agent', 'NoInputNoOutput', '--timeout', '25', 'pair', m], 35)
            if code != 0 and 'AlreadyExists' not in out and not _bt_info(m)['paired']:
                return 'Could not pair. Put the device in pairing mode (usually hold its Bluetooth button) and try again.'
        _run(['bluetoothctl', 'trust', m], 10)
        code, out = _run(['bluetoothctl', '--timeout', '20', 'connect', m], 30)
        if _bt_info(m)['connected']:
            return 'Connected. To play Kevin through it, pick it under Sound and Save.'
        return 'Paired, but it did not connect. Switch it off and on, then press Connect again.'
    _bt_job('connecting', go)


def bt_disconnect(addr):
    m = mac(addr)
    _bt_job('disconnecting', lambda: _run(['bluetoothctl', 'disconnect', m], 15)[0] == 0 and 'Disconnected.' or 'Could not disconnect.')


def bt_forget(addr):
    m = mac(addr)
    _bt_job('forgetting', lambda: _run(['bluetoothctl', 'remove', m], 15)[0] == 0 and 'Forgotten.' or 'Could not forget it.')


# ---------- Wi-Fi ----------
def _nm(args, timeout=20):
    return _run(['nmcli', '-t', '-e', 'yes'] + args, timeout)


def _split(line):
    """nmcli -t escapes ':' inside values as '\\:'."""
    out, cur, esc_ = [], '', False
    for ch in line:
        if esc_:
            cur += ch
            esc_ = False
        elif ch == '\\':
            esc_ = True
        elif ch == ':':
            out.append(cur)
            cur = ''
        else:
            cur += ch
    out.append(cur)
    return out


def ssid_ok(s):
    s = str(s or '')
    if not 0 < len(s.encode('utf-8')) <= 32 or any(ord(c) < 32 for c in s):
        raise ValueError('that is not a Wi-Fi name')
    return s


def wifi_status(rescan=False):
    code, out = _nm(['-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list', '--rescan', 'yes' if rescan else 'auto'], 30)
    if code == 127:
        return {'available': False, 'networks': [], 'saved': [], 'busy': '', 'last': 'NetworkManager is not installed.'}
    nets = {}
    for line in out.splitlines():
        f = _split(line)
        if len(f) < 4 or not f[1]:
            continue
        n = nets.get(f[1])
        sig = int(f[2]) if f[2].isdigit() else 0
        if not n or sig > n['signal'] or f[0] == '*':
            nets[f[1]] = {'ssid': f[1], 'signal': sig, 'secure': bool(f[3].strip()), 'in_use': f[0] == '*' or (n or {}).get('in_use', False)}
    _c, so = _nm(['-f', 'NAME,TYPE', 'connection', 'show'], 10)
    saved = [_split(l)[0] for l in so.splitlines() if _split(l)[-1:] == ['802-11-wireless']]
    rows = sorted(nets.values(), key=lambda n: (not n['in_use'], -n['signal']))
    return {'available': True, 'networks': rows[:25], 'saved': saved, 'busy': WIFI_STATE['busy'], 'last': WIFI_STATE['last']}


def wifi_join(ssid, password=''):
    """Join a network. If it does not work within 40 s, go back to the network that was working."""
    s = ssid_ok(ssid)
    pw = str(password or '')
    if pw and not 8 <= len(pw) <= 63:
        raise ValueError('a Wi-Fi password is 8 to 63 characters')
    _c, out = _nm(['-f', 'NAME,TYPE,DEVICE', 'connection', 'show', '--active'], 10)
    before = next((_split(l)[0] for l in out.splitlines() if '802-11-wireless' in l), '')

    def go():
        WIFI_STATE['busy'] = 'joining %s' % s
        args = ['device', 'wifi', 'connect', s] + (['password', pw] if pw else [])
        code, out = _nm(args, 45)
        if code == 0:
            WIFI_STATE['last'] = 'Joined %s. If this page stops answering, open it again from a device on %s.' % (s, s)
        else:
            if before:
                _nm(['connection', 'up', before], 45)
            WIFI_STATE['last'] = 'Could not join %s (%s). Still on %s.' % (
                s, 'wrong password?' if 'Secrets were required' in out or 'password' in out.lower() else 'out of range?', before or 'the old network')
        WIFI_STATE['busy'] = ''
    threading.Thread(target=go, daemon=True).start()


def wifi_forget(name):
    s = ssid_ok(name)
    _c, out = _nm(['-f', 'NAME,TYPE', 'connection', 'show', '--active'], 10)
    if any(_split(l)[0] == s for l in out.splitlines()):
        raise ValueError('that is the network Kevin is on now: join another one first')
    code, _o = _nm(['connection', 'delete', 'id', s], 15)
    WIFI_STATE['last'] = 'Forgot %s.' % s if code == 0 else 'Could not forget %s.' % s


# ---------- Sound devices ----------
def _alsa_list(cmd):
    _c, out = _run([cmd, '-L'], 8)
    rows, name = [], None
    for line in out.splitlines():
        if line and not line[0].isspace():
            name = line.strip()
            rows.append({'name': name, 'label': name})
        elif name and rows and rows[-1]['label'] == name and line.strip():
            rows[-1]['label'] = line.strip()
    keep = [r for r in rows if r['name'] == 'default' or r['name'].startswith(('plughw:', 'sysdefault:'))]
    return keep


def sound_devices():
    """{speakers, mics}: [{name, label}], plus connected Bluetooth speakers (bluez-alsa)."""
    speakers, mics = _alsa_list('aplay'), _alsa_list('arecord')
    for d in bt_devices()['devices'] if bt_available() else []:
        if d['connected']:
            speakers.append({'name': 'bluealsa:DEV=%s,PROFILE=a2dp' % d['address'], 'label': 'Bluetooth: %s' % d['name']})
    return {'speakers': speakers, 'mics': mics}


def test_tone(device):
    """Half a second of a soft 660 Hz tone through one speaker device."""
    import math
    import struct
    from .audio import safe_device
    dev = safe_device(device)
    pcm = b''.join(struct.pack('<h', int(6000 * math.sin(2 * math.pi * 660 * i / 24000) * min(1, i / 600, (12000 - i) / 600)))
                   for i in range(12000))
    try:
        p = subprocess.run(['aplay', '-q', '-D', dev, '-f', 'S16_LE', '-r', '24000', '-c', '1', '-t', 'raw'],
                           input=pcm, capture_output=True, timeout=10)
        return p.returncode == 0, (p.stderr or b'').decode('utf-8', 'replace')[-200:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
