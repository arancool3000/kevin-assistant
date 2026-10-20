"""Kevin's built-in abilities: the everyday ones, before anyone has taught him anything.

Time, weather (Open-Meteo, free, no key), timers, notes he remembers, volume, the Pi's own health, ending the
conversation -- plus the skill-building tools in skills.py. Google Search comes built into Gemini Live.
"""
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request

from . import audio, config, experts, knowledge, music, skills, timers

NOTES = os.path.join(config.STATE, 'notes.json')
WEATHER_CODES = {0: 'clear', 1: 'mostly clear', 2: 'partly cloudy', 3: 'overcast', 45: 'fog', 48: 'fog',
                 51: 'light drizzle', 53: 'drizzle', 55: 'heavy drizzle', 61: 'light rain', 63: 'rain',
                 65: 'heavy rain', 71: 'light snow', 73: 'snow', 75: 'heavy snow', 80: 'showers',
                 81: 'showers', 82: 'heavy showers', 95: 'thunderstorm', 96: 'thunderstorm', 99: 'thunderstorm'}

S = lambda d: {'type': 'STRING', 'description': d}      # noqa: E731
N = lambda d: {'type': 'NUMBER', 'description': d}      # noqa: E731
OBJ = lambda props=None, req=None: {'type': 'OBJECT', 'properties': props or {}, 'required': req or []}   # noqa: E731

DECLARATIONS = [
    {'name': 'get_time', 'description': 'The current local date and time.', 'parameters': OBJ()},
    {'name': 'get_weather', 'description': 'Weather now and today (and tomorrow) for the town in settings, or another place.',
     'parameters': OBJ({'place': S('optional: another town or city')})},
    {'name': 'set_timer', 'description': 'Start a countdown timer (several can run at once). When it ends it rings until stopped.',
     'parameters': OBJ({'hours': N('hours'), 'minutes': N('minutes'), 'seconds': N('seconds'), 'name': S('optional name, e.g. pasta')})},
    {'name': 'set_alarm', 'description': 'An alarm at a time of day (the next time that time comes round), e.g. to wake up. '
     'It rings, getting louder, until stopped.', 'parameters': OBJ({'time': S('e.g. 7:30, 6 pm, 19:05'), 'name': S('optional label')}, ['time'])},
    {'name': 'list_timers', 'description': 'Timers and alarms: time left, when each is due, and whether one is ringing.', 'parameters': OBJ()},
    {'name': 'stop_timer', 'description': 'Stop a ringing timer or alarm, or cancel one before it rings ("stop", "cancel the pasta timer", "cancel all").',
     'parameters': OBJ({'which': S('a name, "alarm", "all", or leave empty for the ringing one')})},
    {'name': 'change_timer', 'description': 'Pause, resume, add or take off time, or snooze (default 9 minutes) a timer or alarm.',
     'parameters': OBJ({'which': S('a name, or empty for the ringing/only one'), 'action': S('pause, resume, add, subtract or snooze'),
                        'minutes': N('for add/subtract/snooze')}, ['action'])},
    {'name': 'play_radio', 'description': 'Play an internet radio station by name (any station in the world, e.g. BBC Radio 2, Jazz FM, Radio Paradise).',
     'parameters': OBJ({'station': S('the station name')}, ['station'])},
    {'name': 'play_music', 'description': 'Play songs from the music folder on the Pi: a song, artist or album name, or empty to shuffle everything.',
     'parameters': OBJ({'query': S('what to play, or empty to shuffle')})},
    {'name': 'music_control', 'description': 'Control the music or radio: stop, pause, resume, next, louder, quieter, or volume (0-100).',
     'parameters': OBJ({'action': S('stop, pause, resume, next, louder, quieter or volume'), 'volume': N('0-100, for volume')}, ['action'])},
    {'name': 'now_playing', 'description': 'What music or radio is playing now (song title when the station sends it).', 'parameters': OBJ()},
    {'name': 'quiet_hours', 'description': 'Quiet hours (softer chimes, dim bedside screen; alarms still ring): read them, or change them.',
     'parameters': OBJ({'start_hour': N('0-23'), 'end_hour': N('0-23'), 'enabled': {'type': 'BOOLEAN', 'description': 'on or off'}})},
    {'name': 'ask_expert', 'description': 'Hand a hard question to the user\'s own Claude or ChatGPT account (only if connected on '
     'the settings page): careful maths, code, planning, a long or tricky explanation. Slow (up to a minute or two): say '
     '"let me think about that" first. Not for everyday questions.',
     'parameters': OBJ({'question': S('the full question, with any details the user gave'), 'which': S('claude, chatgpt, or empty for either')}, ['question'])},
    {'name': 'remember', 'description': 'Remember a fact the user tells you, for later conversations.',
     'parameters': OBJ({'fact': S('the fact, in a short sentence')}, ['fact'])},
    {'name': 'recall', 'description': 'What you have been asked to remember (optionally about one topic).',
     'parameters': OBJ({'about': S('optional topic')})},
    {'name': 'forget', 'description': 'Forget remembered facts that mention some words.', 'parameters': OBJ({'about': S('words to match')}, ['about'])},
    {'name': 'set_volume', 'description': 'Speaker volume, 0-100.', 'parameters': OBJ({'percent': N('0-100')}, ['percent'])},
    {'name': 'dance', 'description': 'Dance mode on or off: Kevin follows the beat of the music in the room and dances on the '
     'dance screen (http://<pi>.local:8080/dance, e.g. on a TV), plus anything the owner has hooked up to the beat.',
     'parameters': OBJ({'on': {'type': 'BOOLEAN', 'description': 'on or off'}}, ['on'])},
    {'name': 'pi_status', 'description': 'The Raspberry Pi itself: temperature, uptime, disk space, memory, IP address, version.',
     'parameters': OBJ()},
    {'name': 'gpio_guide', 'description': 'Which GPIO pins are free to wire things to and how (BCM numbers), to help the user wire hardware for a new skill.',
     'parameters': OBJ()},
    {'name': 'end_conversation', 'description': 'Go back to sleep (the user said bye, thanks, that is all).', 'parameters': OBJ()},
] + knowledge.DECLARATIONS + skills.DECLARATIONS


def _notes():
    try:
        with open(NOTES) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save_notes(n):
    os.makedirs(os.path.dirname(NOTES), exist_ok=True)
    with open(NOTES + '.tmp', 'w') as f:
        json.dump(n[-500:], f)
    os.replace(NOTES + '.tmp', NOTES)


def geocode(place):
    q = urllib.parse.urlencode({'name': place, 'count': 1, 'language': 'en', 'format': 'json'})
    with urllib.request.urlopen('https://geocoding-api.open-meteo.com/v1/search?' + q, timeout=10) as r:
        res = (json.load(r).get('results') or [None])[0]
    if not res:
        raise ValueError('I could not find a place called %s' % place)
    return res['latitude'], res['longitude'], res.get('timezone', 'auto'), '%s, %s' % (res['name'], res.get('country', ''))


def weather(lat, lon, tz='auto'):
    q = urllib.parse.urlencode({'latitude': lat, 'longitude': lon, 'timezone': tz or 'auto', 'forecast_days': 2,
                                'current': 'temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m',
                                'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code'})
    with urllib.request.urlopen('https://api.open-meteo.com/v1/forecast?' + q, timeout=10) as r:
        d = json.load(r)
    c, day = d['current'], d['daily']
    return {'now': {'temp_c': c['temperature_2m'], 'feels_like_c': c['apparent_temperature'], 'code': c['weather_code'],
                    'sky': WEATHER_CODES.get(c['weather_code'], 'unknown'), 'wind_kmh': c['wind_speed_10m'],
                    'humidity_pct': c['relative_humidity_2m']},
            'today': {'high_c': day['temperature_2m_max'][0], 'low_c': day['temperature_2m_min'][0],
                      'rain_chance_pct': day['precipitation_probability_max'][0], 'sky': WEATHER_CODES.get(day['weather_code'][0], '')},
            'tomorrow': {'high_c': day['temperature_2m_max'][1], 'low_c': day['temperature_2m_min'][1],
                         'rain_chance_pct': day['precipitation_probability_max'][1], 'sky': WEATHER_CODES.get(day['weather_code'][1], '')}}


def _ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.0.2.1', 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def pi_status():
    out = {}
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            out['cpu_temp_c'] = round(int(f.read()) / 1000.0, 1)
    except OSError:
        pass
    try:
        with open('/proc/uptime') as f:
            out['uptime_hours'] = round(float(f.read().split()[0]) / 3600, 1)
    except OSError:
        pass
    du = shutil.disk_usage('/')
    out['disk_free_gb'] = round(du.free / 1e9, 1)
    try:
        with open('/proc/meminfo') as f:
            m = {l.split(':')[0]: int(l.split()[1]) for l in f}
        out['memory_free_mb'] = round(m.get('MemAvailable', 0) / 1024)
    except (OSError, ValueError):
        pass
    out['ip'] = _ip()
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'VERSION')) as f:
            out['version'] = f.read().strip()
    except OSError:
        pass
    return out


GPIO_GUIDE = {
    'numbering': 'BCM (GPIO numbers), as gpiozero uses -- not the physical pin numbers',
    'free_for_anything': [4, 5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27],
    'physical_pin_of': {4: 7, 5: 29, 6: 31, 12: 32, 13: 33, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13},
    'i2c': {'sda': 2, 'scl': 3, 'note': 'switched on by the installer (needs one reboot after install)'},
    'serial': {'tx': 14, 'rx': 15, 'note': 'turn off the serial console in raspi-config first'},
    'spi': {'mosi': 10, 'miso': 9, 'sclk': 11, 'ce0': 8, 'ce1': 7},
    'power': '3.3V on pins 1 and 17, 5V on pins 2 and 4, ground on 6, 9, 14, 20, 25, 30, 34, 39',
    'rules': ['GPIO pins are 3.3 V: never connect 5 V to a GPIO pin',
              'an LED needs a resistor (220-330 ohm) in series',
              'motors, bare relay coils and long LED strips need their own power supply and a driver -- never power them from a GPIO pin (a ready-made relay module is fine)',
              'never switch mains voltage unless the relay is rated, enclosed and wired by someone qualified',
              'buttons: one leg to the GPIO pin, the other to ground (gpiozero Button uses the internal pull-up)'],
}


class Tools(knowledge.KnowledgeTools):
    def __init__(self, cfg, ring=None):      # ring: kept for old callers; timers.Ringer rings now
        self.cfg = cfg
        self.ended = False

    def declarations(self):
        return DECLARATIONS + skills.declarations()

    def builtin_declarations(self):
        return list(DECLARATIONS)

    def call(self, name, args):
        a = args or {}
        try:
            r = skills.handle(name, a)
            if r is not None:
                return r
            fn = getattr(self, 't_' + name, None)
            if not fn:
                return {'error': 'no tool called %s' % name}
            return fn(**a)
        except TypeError as e:
            return {'error': 'wrong arguments: %s' % e}
        except Exception as e:
            return {'error': str(e)[:300]}

    def t_get_time(self):
        return {'now': time.strftime('%A %d %B %Y, %H:%M'), 'timezone': time.strftime('%Z')}

    def t_get_weather(self, place=None):
        c = self.cfg
        if place:
            lat, lon, tz, label = geocode(place)
        elif c.get('latitude') is not None:
            lat, lon, tz, label = c['latitude'], c['longitude'], c.get('timezone') or 'auto', c.get('town') or 'here'
        elif c.get('town'):
            lat, lon, tz, label = geocode(c['town'])
        else:
            return {'error': 'no town set: say which town, or set it on the web page'}
        return dict(weather(lat, lon, tz), place=label)

    def t_set_timer(self, hours=None, minutes=None, seconds=None, name=None):
        secs = float(hours or 0) * 3600 + float(minutes or 0) * 60 + float(seconds or 0)
        if secs <= 0:
            return {'error': 'how long?'}
        t = timers.add_timer(secs, name)
        return {'ok': True, 'name': t['name'], 'rings_in': timers.say_left(secs),
                'rings_at': time.strftime('%H:%M', time.localtime(t['due']))}

    def t_set_alarm(self, time=None, name=None):
        t = timers.add_alarm(time, name)
        import time as _t
        return {'ok': True, 'name': t['name'], 'rings_at': _t.strftime('%A %H:%M', _t.localtime(t['due'])),
                'in': timers.say_left(t['total'])}

    def t_list_timers(self):
        items = timers.view()
        return {'items': [dict(i, left=timers.say_left(i['left_s'])) for i in items]} if items else {'items': [], 'say': 'none set'}

    def t_stop_timer(self, which=''):
        names = timers.change(which or 'ringing', 'cancel')
        return {'stopped': names} if names else {'error': 'no timer or alarm by that name'}

    def t_change_timer(self, action, which='', minutes=None):
        how = {'pause': 'pause', 'resume': 'resume', 'add': 'add', 'subtract': 'add', 'snooze': 'snooze'}.get(str(action).lower())
        if not how:
            return {'error': 'pause, resume, add, subtract or snooze'}
        secs = float(minutes or (9 if how == 'snooze' else 1)) * 60
        names = timers.change(which or 'ringing', how, -secs if action == 'subtract' else secs)
        return {'changed': names, 'action': action} if names else {'error': 'no timer or alarm by that name'}

    def t_play_radio(self, station):
        return music.play_radio(station, int(self.cfg.get('music_volume', 60)))

    def t_play_music(self, query=''):
        return music.play_music(self.cfg.get('music_dir') or config.DEFAULTS['music_dir'], query, int(self.cfg.get('music_volume', 60)))

    def t_music_control(self, action, volume=None):
        r = music.control(action, volume)
        if action == 'volume' and volume is not None and not r.get('error'):
            self._save_setting('music_volume', int(max(0, min(100, float(volume)))))
        return r

    def t_now_playing(self):
        return music.now_playing()

    def t_quiet_hours(self, start_hour=None, end_hour=None, enabled=None):
        for key, val in (('quiet_from', start_hour), ('quiet_to', end_hour)):
            if val is not None:
                self._save_setting(key, int(val) % 24)
        if enabled is not None:
            self._save_setting('quiet_enabled', bool(enabled))
        return {'from': self.cfg.get('quiet_from', 22), 'to': self.cfg.get('quiet_to', 7),
                'enabled': self.cfg.get('quiet_enabled', True), 'quiet_now': config.is_quiet(self.cfg)}

    def _save_setting(self, key, val):
        self.cfg[key] = val
        try:
            c = config.load()
            c[key] = val
            config.save(c)
        except OSError:
            pass

    def t_ask_expert(self, question, which=''):
        return experts.ask(question, which or 'auto')

    def t_remember(self, fact):
        n = _notes()
        n.append({'at': time.strftime('%Y-%m-%d'), 'fact': str(fact)[:400]})
        _save_notes(n)
        return {'ok': True}

    def t_recall(self, about=None):
        n = _notes()
        if about:
            w = str(about).lower()
            n = [x for x in n if w in x['fact'].lower()]
        return {'facts': n[-40:]}

    def t_forget(self, about):
        n = _notes()
        keep = [x for x in n if str(about).lower() not in x['fact'].lower()]
        _save_notes(keep)
        return {'forgot': len(n) - len(keep)}

    def t_dance(self, on=True):
        from . import dance
        go = bool(on) and str(on).lower() not in ('false', '0', 'off', 'no')
        dance.set_enabled(go)
        return {'ok': True, 'dancing': go,
                'say': ('Dance mode on. Put some music on; the dance screen is at port 8080, slash dance.' if go
                        else 'Dance mode off.')}

    def t_set_volume(self, percent):
        pct = audio.set_volume(percent)
        self.cfg['volume'] = pct
        try:
            cfg = config.load()
            cfg['volume'] = pct
            config.save(cfg)                    # kept across restarts
        except OSError:
            pass
        return {'ok': True, 'volume': pct}

    def t_pi_status(self):
        return pi_status()

    def t_gpio_guide(self):
        return GPIO_GUIDE

    def t_end_conversation(self):
        self.ended = True
        return {'ok': True}


def memory_lines(limit=30):
    """Remembered facts, for the start of every conversation."""
    n = _notes()[-limit:]
    return '\n'.join('- %s' % x['fact'] for x in n)


def update_notice():
    """If the updater installed a new version since Kevin last said so, say so once."""
    seen_path = os.path.join(config.STATE, 'announced.json')
    try:
        with open('/var/lib/bob-assistant-update/updated.json') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return ''
    try:
        with open(seen_path) as f:
            if json.load(f).get('version') == d.get('version'):
                return ''
    except (OSError, ValueError):
        pass
    try:
        with open(seen_path, 'w') as f:
            json.dump({'version': d.get('version')}, f)
    except OSError:
        pass
    return 'You were just updated to version %s: mention it briefly if it fits.' % d.get('version')


def run_cmd(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
