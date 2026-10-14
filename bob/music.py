"""Music: internet radio (the free Radio Browser directory, no key) and songs from a folder on the Pi, played by
mpv. Kevin turns the music down while he listens and talks, and back up afterwards.

mpv runs as its own process with a control socket in the state folder, so the web page can stop or pause it
too. Put music in the folder named in settings (default /var/lib/bob-assistant/music): mp3, m4a, ogg, flac, wav.
"""
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request

from . import config

SOCK = os.path.join(config.STATE, 'mpv.sock')
EXTS = ('.mp3', '.m4a', '.ogg', '.oga', '.flac', '.wav', '.opus', '.aac')
UA = 'kevin-assistant (https://github.com/arancool3000/kevin-assistant)'
_now = {'what': None, 'kind': None, 'volume': 60, 'ducked': False}


def _cmd(*args, want=False):
    """One mpv IPC command; returns its 'data' (or None)."""
    if not os.path.exists(SOCK):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(SOCK)
        s.sendall((json.dumps({'command': list(args)}) + '\n').encode())
        buf = b''
        while b'\n' not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        for line in buf.split(b'\n'):
            if line.strip():
                d = json.loads(line)
                if 'error' in d:
                    return d.get('data') if want else d['error']
    except (OSError, ValueError):
        return None
    return None


def playing():
    return _cmd('get_property', 'idle-active', want=True) is False


def _start(urls, volume, shuffle=False):
    stop()
    if not shutil.which('mpv'):
        raise RuntimeError('the music player (mpv) is not installed: run the installer again')
    args = ['mpv', '--no-video', '--no-terminal', '--input-ipc-server=' + SOCK, '--volume=%d' % volume,
            '--idle=no', '--cache=yes', '--network-timeout=15']
    if shuffle:
        args.append('--shuffle')
    subprocess.Popen(args + list(urls), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(30):                      # wait for its control socket
        if os.path.exists(SOCK) and _cmd('get_property', 'pid', want=True):
            break
        time.sleep(0.1)


def stop():
    _cmd('quit')
    for _ in range(20):
        if not os.path.exists(SOCK) or _cmd('get_property', 'pid', want=True) is None:
            break
        time.sleep(0.1)
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    _now.update(what=None, kind=None, ducked=False)


def find_station(name):
    q = urllib.parse.urlencode({'name': name, 'limit': 8, 'hidebroken': 'true', 'order': 'clickcount', 'reverse': 'true'})
    req = urllib.request.Request('https://all.api.radio-browser.info/json/stations/search?' + q, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        hits = [h for h in json.load(r) if h.get('url_resolved')]
    return hits[0] if hits else None


def play_radio(name, volume=60):
    st = find_station(name)
    if not st:
        return {'error': 'I could not find a radio station called %s' % name}
    _start([st['url_resolved']], volume)
    _now.update(what=st['name'].strip(), kind='radio', volume=volume)
    return {'ok': True, 'station': st['name'].strip(), 'country': st.get('country', '')}


def library(folder):
    out = []
    for d, _, files in os.walk(folder):
        out += [os.path.join(d, f) for f in files if f.lower().endswith(EXTS)]
    return sorted(out)


def play_music(folder, query='', volume=60):
    songs = library(folder)
    if not songs:
        return {'error': 'there is no music on the Pi yet: copy songs into %s' % folder}
    q = str(query or '').lower().strip()
    if q in ('', 'anything', 'music', 'something', 'shuffle', 'all'):
        pick, shuffle = songs, True
    else:
        words = q.split()
        pick = [s for s in songs if all(w in s.lower() for w in words)]
        shuffle = False
        if not pick:
            return {'error': 'nothing in the music folder matches %s' % query}
    _start(pick, volume, shuffle)
    title = 'shuffled music' if shuffle else os.path.splitext(os.path.basename(pick[0]))[0]
    _now.update(what=title, kind='music', volume=volume)
    return {'ok': True, 'playing': title, 'songs': len(pick)}


def now_playing():
    if not playing():
        return {'playing': False}
    meta = _cmd('get_property', 'metadata', want=True) or {}
    title = meta.get('icy-title') or meta.get('title') or _cmd('get_property', 'media-title', want=True)
    paused = _cmd('get_property', 'pause', want=True)
    return {'playing': True, 'paused': bool(paused), 'source': _now['what'], 'kind': _now['kind'], 'title': title,
            'volume': _cmd('get_property', 'volume', want=True)}


def control(action, volume=None):
    a = str(action or '').lower()
    if a in ('stop', 'off'):
        stop()
        return {'ok': True, 'stopped': True}
    if not playing():
        return {'error': 'nothing is playing'}
    if a == 'pause':
        _cmd('set_property', 'pause', True)
    elif a in ('resume', 'play', 'continue'):
        _cmd('set_property', 'pause', False)
    elif a in ('next', 'skip'):
        _cmd('playlist-next', 'force')
    elif a in ('louder', 'up'):
        _cmd('add', 'volume', 10)
    elif a in ('quieter', 'down'):
        _cmd('add', 'volume', -10)
    elif a == 'volume' and volume is not None:
        _cmd('set_property', 'volume', max(0, min(100, float(volume))))
    else:
        return {'error': 'stop, pause, resume, next, louder, quieter or volume'}
    return dict(now_playing(), ok=True)


def duck(on):
    """Music down to a murmur while Kevin is in a conversation; back afterwards."""
    if on and not _now['ducked'] and playing():
        _now['volume'] = _cmd('get_property', 'volume', want=True) or _now['volume']
        _cmd('set_property', 'volume', max(5, _now['volume'] * 0.2))
        _now['ducked'] = True
    elif not on and _now['ducked']:
        _cmd('set_property', 'volume', _now['volume'])
        _now['ducked'] = False
