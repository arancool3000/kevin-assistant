"""What the phone page and the bedside screen can do, and the live picture they both show.

Kevin's own process (main.py) and the web page are separate services, so they talk through small files in
the state folder: wake_now / stop_now (the talk button), timers.json (timers.py) and mpv's socket (music.py).
"""
import json
import os
import time

from . import config, music, timers, tools

WAKE_NOW = os.path.join(config.STATE, 'wake_now')
STOP_NOW = os.path.join(config.STATE, 'stop_now')
_weather = {'at': 0.0, 'data': None, 'where': None}


def kevin_state():
    try:
        with open(os.path.join(config.STATE, 'state.json')) as f:
            return json.load(f).get('state') or 'starting'
    except (OSError, ValueError):
        return 'starting'


def _touch(path):
    with open(path, 'w') as f:
        f.write(str(time.time()))


def talk():
    """The talk button: start a conversation without the wake phrase, or end the one that's on."""
    if kevin_state() in ('listening', 'speaking', 'working'):
        _touch(STOP_NOW)
        return {'ok': True, 'listening': False}
    _touch(WAKE_NOW)
    return {'ok': True, 'listening': True}


def timer(action, which=''):
    """stop (the ringing one, or `which`), snooze, pause, resume, add1 (one more minute), cancel."""
    how = {'stop': 'cancel', 'cancel': 'cancel', 'snooze': 'snooze', 'pause': 'pause', 'resume': 'resume', 'add1': 'add'}.get(action)
    if not how:
        return {'ok': False, 'error': 'unknown timer action'}
    secs = 9 * 60 if how == 'snooze' else 60
    names = timers.change(str(which) or 'ringing', how, secs)
    return {'ok': bool(names), 'changed': names}


def music_action(action):
    return music.control(action)


def weather(cfg=None):
    """Weather for the town in settings, at most every 10 minutes (the screens ask often)."""
    c = cfg or config.load()
    where = (c.get('latitude'), c.get('longitude'), c.get('town'))
    if _weather['data'] and _weather['where'] == where and time.time() - _weather['at'] < 600:
        return _weather['data']
    try:
        if c.get('latitude') is not None:
            lat, lon, tz = c['latitude'], c['longitude'], c.get('timezone') or 'auto'
        elif c.get('town'):
            lat, lon, tz, _ = tools.geocode(c['town'])
        else:
            return None
        _weather.update(at=time.time(), data=tools.weather(lat, lon, tz), where=where)
    except Exception:
        _weather['at'] = time.time() - 480          # try again in two minutes
    return _weather['data']


def live(cfg=None):
    """Everything a screen needs, in one small dict."""
    c = cfg or config.load()
    try:
        playing = music.now_playing()
    except Exception:
        playing = {'playing': False}
    return {'name': c.get('name', 'Kevin'), 'state': kevin_state(), 'timers': timers.view(), 'music': playing,
            'quiet': config.is_quiet(c), 'weather': weather(c), 'now': time.time()}
