"""Timers and alarms, kept on disk so a restart never loses one, and shared by Kevin and the web page.

A timer counts down ("pasta, 10 minutes"); an alarm is a time of day ("wake me at 7"). When one is done it
rings, again and again, until someone stops it (by voice, the web page or the bedside screen) or it gives up:
a timer after 5 minutes, an alarm after 15 -- an alarm gets louder as it goes, to wake a sleeper.

The file is the truth: every change is written at once (atomically), and the ringer re-reads it twice a
second, so a stop from another process (the web page) takes effect straight away.
"""
import datetime as dt
import json
import os
import re
import threading
import time

from . import config

FILE = os.path.join(config.STATE, 'timers.json')
TIMER_RING_EVERY, TIMER_RING_FOR = 20, 300
ALARM_RING_EVERY, ALARM_RING_FOR = 6, 900
_lock = threading.Lock()


def _load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d.get('items'), list):
            return d
    except (OSError, ValueError):
        pass
    return {'next': 1, 'items': []}


def _save(d):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(d, f)
    os.replace(tmp, FILE)


def left(t, now=None):
    if t.get('paused_left') is not None:
        return max(0.0, t['paused_left'])
    return max(0.0, t['due'] - (now or time.time()))


def state(t):
    return 'ringing' if t.get('rang_at') else 'paused' if t.get('paused_left') is not None else 'waiting'


def view(now=None):
    """Every timer and alarm: id, name, kind, seconds left, state, and the clock time it is due."""
    now = now or time.time()
    out = []
    for t in sorted(_load()['items'], key=lambda t: left(t, now)):
        out.append({'id': t['id'], 'name': t['name'], 'kind': t['kind'], 'left_s': round(left(t, now)),
                    'state': state(t), 'due': time.strftime('%H:%M', time.localtime(t['due']))})
    return out


def _add(kind, name, due, total):
    with _lock:
        d = _load()
        t = {'id': d['next'], 'kind': kind, 'name': (name or '').strip()[:40] or ('alarm' if kind == 'alarm' else 'timer %d' % d['next']),
             'due': due, 'total': total, 'rang_at': None, 'paused_left': None}
        d['next'] += 1
        d['items'].append(t)
        _save(d)
        return t


def add_timer(seconds, name=None):
    seconds = float(seconds)
    if not 0 < seconds <= 7 * 86400:
        raise ValueError('a timer can be from 1 second to a week')
    return _add('timer', name, time.time() + seconds, seconds)


def parse_clock(text, now=None):
    """'7', '7:30', '07:30', '7.30 pm', '19:05' -> the next time that clock time comes round."""
    now = now or dt.datetime.now()
    m = re.match(r'^\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\s*$', str(text).lower())
    if not m:
        raise ValueError('say a time like 7:30 or 6 pm')
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or '').replace('.', '')
    if ap == 'pm' and h < 12:
        h += 12
    if ap == 'am' and h == 12:
        h = 0
    if h > 23 or mi > 59:
        raise ValueError('that is not a time of day')
    at = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if at <= now:
        at += dt.timedelta(days=1)
    return at


def add_alarm(clock, name=None, now=None):
    at = parse_clock(clock, now)
    return _add('alarm', name or 'alarm', at.timestamp(), (at - (now or dt.datetime.now())).total_seconds())


def find(which, items):
    w = str(which or '').strip().lower()
    if w in ('', 'all', 'every', 'everything'):
        return list(items)
    if w in ('ringing', 'it', 'that', 'this'):
        hit = [t for t in items if t.get('rang_at')]
        return hit or list(items)[:1]
    return [t for t in items if str(t['id']) == w or w in t['name'].lower() or w == t['kind']]


def change(which, how, seconds=0):
    """how: cancel | pause | resume | add | snooze. Returns the names changed."""
    with _lock:
        d = _load()
        hits = find(which, d['items'])
        now = time.time()
        for t in hits:
            if how == 'cancel':
                d['items'].remove(t)
            elif how == 'pause' and t['paused_left'] is None and not t['rang_at']:
                t['paused_left'] = left(t, now)
            elif how == 'resume' and t['paused_left'] is not None:
                t['due'], t['paused_left'] = now + t['paused_left'], None
            elif how == 'add':
                if t['paused_left'] is not None:
                    t['paused_left'] = max(1, t['paused_left'] + seconds)
                else:
                    t['due'] = max(now + 1, t['due'] + seconds)
            elif how == 'snooze':
                t['due'], t['rang_at'], t['paused_left'] = now + max(60, seconds), None, None
        _save(d)
        return [t['name'] for t in hits]


def say_left(s):
    s = int(round(s))
    h, m, sec = s // 3600, s // 60 % 60, s % 60
    parts = (['%d hour%s' % (h, '' if h == 1 else 's')] if h else []) + (['%d minute%s' % (m, '' if m == 1 else 's')] if m else [])
    if not h and (sec or not m):
        parts.append('%d second%s' % (sec, '' if sec == 1 else 's'))
    return ' '.join(parts)


class Ringer:
    """Rings whatever is due, until stopped. `chime(kind, loudness 0-1)` makes the sound."""

    def __init__(self, chime, log=print):
        self.chime, self.log = chime, log
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        last = {}
        while True:
            time.sleep(0.5)
            try:
                self._tick(last)
            except Exception as e:
                self.log('ringer: %s' % e)

    def _tick(self, last):
        now = time.time()
        with _lock:
            d = _load()
            changed = False
            for t in list(d['items']):
                if t['paused_left'] is not None or t['due'] > now:
                    continue
                if not t['rang_at']:
                    t['rang_at'] = now
                    changed = True
                every, limit = (ALARM_RING_EVERY, ALARM_RING_FOR) if t['kind'] == 'alarm' else (TIMER_RING_EVERY, TIMER_RING_FOR)
                if now - t['rang_at'] > limit:
                    d['items'].remove(t)              # nobody stopped it: give up quietly
                    changed = True
                    continue
                if now - last.get(t['id'], 0) >= every:
                    last[t['id']] = now
                    loud = min(1.0, 0.5 + (now - t['rang_at']) / limit) if t['kind'] == 'alarm' else 0.6
                    threading.Thread(target=self.chime, args=(t['kind'], loud), daemon=True).start()
            if changed:
                _save(d)
