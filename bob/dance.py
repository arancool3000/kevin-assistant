"""Dance mode: Kevin finds the beat in whatever is playing in the room and dances to it.

Out of the box he dances on a screen: open http://<pi-name>.local:8080/dance (the settings page's Dance button) on a
TV or the Pi's own HDMI output, and Kevin's face bounces, sways, blinks and travels in time with the music.

Everything else is yours to add (docs/DANCE.md). The beat is written to STATE/dance.json about twenty times a second
and served at /api/dance, so a skill, an ESP32 with LEDs, a robot arm or another computer can follow it:

  {"live": true, "n": 128, "bpm": 122, "glow": 0.8, "hue": 210, "kick": 1.0, "snare": 0.0, "hat": 0.4,
   "snares": 41, "hats": 260, "loud": 0.6, "at": 1760000000.0}

  n        beats so far (it goes up by one on every beat: the moment to move)
  bpm      the tempo (fast songs count at half speed, which is what bodies dance to)
  kick / snare / hat   0..1, jumps to 1 on that drum and fades: good for lights
  snares / hats        counters, they go up on every snare / hi-hat
  glow     how hard the last beat hit, 0..1;  loud  the music's loudness against its own recent peak
  hue      a colour that moves on every bar (4 beats), for anything that lights up

How it hears: the microphone Kevin already listens with (no extra hardware). It reads the 100 ms chunks the wake-word
listener reads anyway, so nothing extra runs while dance mode is off. Nothing is recorded or kept.
"""
import json
import os
import time

from . import config

ON_FILE = os.path.join(config.STATE, 'dance_on')
NOW_FILE = os.path.join(config.STATE, 'dance.json')
RATE = 16000
_cache = {'at': 0.0, 'on': False}


def enabled():
    """Checked on every microphone chunk, so it looks at the disk at most once a second."""
    now = time.time()
    if now - _cache['at'] > 1.0:
        _cache['at'], _cache['on'] = now, os.path.exists(ON_FILE)
    return _cache['on']


def set_enabled(on):
    if on:
        open(ON_FILE, 'w').close()
    elif os.path.exists(ON_FILE):
        os.remove(ON_FILE)
    _cache['at'] = 0.0


class _Band:
    """Onset finder for one band: the energy jumping well above its own last second."""
    def __init__(self, ratio, floor):
        self.ratio, self.floor, self.hist, self.prev = ratio, floor, [], 0.0

    def hit(self, e, ticks=10):
        avg = sum(self.hist) / len(self.hist) if self.hist else e
        self.hist = (self.hist + [e])[-ticks:]
        jump = e > self.ratio * avg or (e > 1.6 * self.prev and e > avg)
        self.prev = e
        return jump and e > self.floor, e / max(avg, 1.0)


class Beat:
    def __init__(self):
        self.lp = self.lp2 = 0.0
        self.bass, self.mid, self.high = _Band(1.45, 300), _Band(1.45, 220), _Band(1.45, 100)
        self.last, self.gaps, self.n, self.peak = 0.0, [], 0, 1.0
        self.st = {'kick': 0.0, 'snare': 0.0, 'hat': 0.0, 'glow': 0.0, 'loud': 0.0, 'snares': 0, 'hats': 0,
                   'hue': 200}

    def period(self):
        g = sorted(self.gaps)
        p = g[len(g) // 2] if len(g) >= 3 else 0.5
        while p < 0.4:
            p *= 2
        while p > 1.0:
            p /= 2
        return p

    def feed(self, pcm, now):
        n = len(pcm) // 2
        if not n:
            return
        import array
        s = array.array('h')
        s.frombytes(pcm[:n * 2])
        lp, lp2, eb, em, eh, tot = self.lp, self.lp2, 0.0, 0.0, 0.0, 0.0
        for x in s:                     # ~150 Hz and ~1.5 kHz one-pole low-passes: bass, mid, high
            lp += 0.06 * (x - lp)
            lp2 += 0.55 * (x - lp2)
            eb += lp * lp
            em += (lp2 - lp) ** 2
            eh += (x - lp2) ** 2
            tot += x * x
        self.lp, self.lp2 = lp, lp2
        eb, em, eh, tot = [(v / n) ** 0.5 for v in (eb, em, eh, tot)]
        st = self.st
        for k in ('kick', 'snare', 'hat'):
            st[k] *= 0.6
        st['glow'] *= 0.8
        self.peak = max(tot, self.peak * 0.998)
        st['loud'] = 0.6 * st['loud'] + 0.4 * min(1.0, tot / self.peak)
        kick, punch = self.bass.hit(eb)
        gap = max(0.3, 0.7 * self.period()) if len(self.gaps) >= 3 else 0.3
        if kick and now - self.last > 0.18:
            st['kick'] = 1.0 if now - self.last > gap else max(st['kick'], 0.7)    # in between: lights only
        if kick and now - self.last > gap:
            if self.last and now - self.last < 1.5:
                self.gaps = (self.gaps + [now - self.last])[-12:]
            self.last = now
            self.n += 1
            st['glow'] = min(1.0, 0.6 + 0.15 * punch)
            if self.n % 4 == 0:
                st['hue'] = (st['hue'] + 47) % 360
        sn, rm = self.mid.hit(em)
        ht, rh = self.high.hit(eh)
        if sn and not kick and rm >= rh * 1.15:
            st['snare'], st['snares'] = 1.0, st['snares'] + 1
        elif ht and not kick:
            st['hat'], st['hats'] = 1.0, st['hats'] + 1

    def snapshot(self, now):
        out = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.st.items()}
        out.update(n=self.n, bpm=round(60 / self.period()), at=now)
        return out


_beat = {'b': None, 'wrote': 0.0}


def feed(pcm):
    """Called with each 100 ms microphone chunk while dance mode is on."""
    b = _beat['b'] = _beat['b'] or Beat()
    now = time.time()
    half = len(pcm) // 2 // 2 * 2                    # two 50 ms steps per chunk: snappier lights
    b.feed(pcm[:half], now - 0.05)
    b.feed(pcm[half:], now)
    try:
        tmp = NOW_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(b.snapshot(now), f)
        os.replace(tmp, NOW_FILE)
    except OSError:
        pass


def now_state():
    """What /api/dance serves: the newest beat, live only while dance mode is on and the listener is feeding it."""
    try:
        with open(NOW_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d['live'] = os.path.exists(ON_FILE) and time.time() - d.get('at', 0) < 2
    return d
