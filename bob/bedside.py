"""The bedside screen: an Arduino Nano with a 16x2 LCD, a joystick and a buzzer on a USB cable (see
examples/bedside-screen/ for the sketch and wiring). Kevin draws it; its joystick works Kevin.

Pages (left/right): Home (time, date, weather, and the one thing that matters most right now), Weather,
Timers, Kevin. Press = talk to Kevin / stop him; down = stop a ringing alarm (else stop the music);
up = back to Home; hold = screen off/on. Dim in quiet hours, bright for 15 s after a touch.

Wire protocol, 115200 baud:
  Kevin -> screen   'H' hello (screen answers 'K')   'T' row + 16 bytes   'G' slot + 8 rows (glyph, drawn as 8-15)
                    'B' 0..5 backlight               'Z' ms/10 + half-period us/10 (a tone)
  screen -> Kevin   one byte per joystick event: l r u d p (press) h (held)
Which device: the USB serial number in settings ("bedside_serial"); nothing is opened unless it is set,
because opening a Nano's port resets it (a skill's Arduino must never be disturbed).
"""
import glob
import threading
import time

from . import actions, config

PAGES = ('home', 'weather', 'timers', 'kevin')
SUN, CLOUD, RAIN, MOON, BELL, TIMER, MUSIC, MIC = (chr(8 + i) for i in range(8))
ICONS = ([4, 21, 14, 31, 14, 21, 4, 0], [0, 0, 6, 9, 17, 31, 0, 0], [6, 9, 17, 31, 0, 10, 0, 20], [0, 6, 12, 24, 24, 12, 6, 0],
         [4, 14, 14, 14, 31, 0, 4, 0], [31, 17, 10, 4, 10, 17, 31, 0], [3, 5, 9, 9, 11, 27, 24, 0], [14, 14, 14, 14, 31, 4, 14, 0])
DEG, BLOCK = '\xdf', '\xff'          # the LCD's own degree sign and solid block
BRIGHT_S = 15


def fit(s, n=16):
    s = ''.join(c if 32 <= ord(c) < 127 or 8 <= ord(c) < 16 or c in DEG + BLOCK else '?' for c in str(s).replace('°', DEG))
    return s[:n].ljust(n)


def mmss(s):
    s = max(0, int(s))
    return '%d:%02d:%02d' % (s // 3600, s // 60 % 60, s % 60) if s >= 3600 else '%d:%02d' % (s // 60, s % 60)


def port(serial_no):
    hits = sorted(glob.glob('/dev/serial/by-id/*%s*' % serial_no)) if serial_no else []
    return hits[0] if hits else None


def devices():
    """USB serial devices plugged in now (for the settings page hint)."""
    return [p.rsplit('/', 1)[-1] for p in sorted(glob.glob('/dev/serial/by-id/*'))]


class Screen:
    def __init__(self, path):
        import serial
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate, self.ser.timeout = path, 115200, 0
        self.ser.exclusive = True
        self.ser.open()                      # resets the Nano; it boots, then says hello back
        time.sleep(2.5)
        self.ser.reset_input_buffer()
        for _ in range(5):
            self.ser.write(b'H')
            got, t = b'', time.time()
            while time.time() - t < 1.0:
                got += self.ser.read(64)
                if b'K' in got:
                    self.lines, self.light = [None, None], None
                    self.icons()
                    return
                time.sleep(0.05)
        raise OSError('no hello from the bedside screen (is the sketch from examples/bedside-screen on it?)')

    def icons(self):
        for i, rows in enumerate(ICONS):
            self.ser.write(b'G' + bytes([i] + rows))
            time.sleep(0.01)
        self.lines, self.icons_at = [None, None], time.time()

    def show(self, a, b):
        for row, txt in enumerate((fit(a), fit(b))):
            if txt != self.lines[row]:
                self.ser.write(b'T' + bytes([row]) + txt.encode('latin-1'))
                self.lines[row] = txt
                time.sleep(0.02)

    def backlight(self, level):
        level = max(0, min(5, int(level)))
        if level != self.light:
            self.ser.write(b'B' + bytes([level]))
            self.light = level

    def tone(self, ms, hz):
        self.ser.write(b'Z' + bytes([min(255, ms // 10), min(255, int(500000 / hz) // 10)]))

    def keys(self):
        return self.ser.read(64).decode('ascii', 'ignore')


class Bedside:
    def __init__(self, log=print):
        self.log, self.page, self.lit_until, self.dark = log, 0, 0.0, False
        self.note_txt, self.note_until, self.data, self.data_at = None, 0.0, {}, 0.0

    def live(self):
        if time.time() - self.data_at > 1:
            try:
                self.data = actions.live()
            except Exception as e:
                self.log('bedside: %s' % e)
            self.data_at = time.time()
        return self.data

    def sky(self):
        w = (self.live().get('weather') or {}).get('now') or {}
        code, temp = w.get('code', 3), w.get('temp_c')
        night = not 7 <= time.localtime().tm_hour < 19
        icon = (MOON if night else SUN) if code in (0, 1) else RAIN if code >= 51 else CLOUD
        return icon, temp

    def headline(self):
        d = self.live()
        ts = d.get('timers') or []
        ring = [t for t in ts if t['state'] == 'ringing']
        if ring:
            return BELL + ' %s DONE' % ring[0]['name']
        if d.get('state') in ('listening', 'speaking', 'working'):
            return MIC + ' %s %s' % (d.get('name', 'Kevin'), d['state'])
        if ts:
            t = ts[0]
            right = t['due'] if t['kind'] == 'alarm' else mmss(t['left_s'])
            return (BELL if t['kind'] == 'alarm' else TIMER) + ' ' + t['name'][:14 - len(right)].ljust(14 - len(right)) + right
        m = d.get('music') or {}
        if m.get('playing'):
            return MUSIC + ' ' + str(m.get('title') or m.get('source') or 'music')
        return ' press = talk'

    def p_home(self):
        icon, temp = self.sky()
        tail = icon + ('%d%s' % (round(temp), DEG) if temp is not None else '')
        return time.strftime('%H:%M %a %d').ljust(16 - len(tail)) + tail, self.headline()

    def p_weather(self):
        w = self.live().get('weather')
        if not w:
            return 'Weather', 'set your town'
        icon, temp = self.sky()
        n, t = w['now'], w['today']
        return ('%s%d%s %s' % (icon, round(temp or 0), DEG, n.get('sky', '')),
                '%d-%d%s rain %d%%' % (round(t['low_c']), round(t['high_c']), DEG, t.get('rain_chance_pct') or 0))

    def p_timers(self):
        ts = (self.live().get('timers') or [])[:2]
        if not ts:
            return TIMER + ' no timers', BELL + ' no alarms'
        rows = []
        for t in ts:
            right = 'DONE' if t['state'] == 'ringing' else t['due'] if t['kind'] == 'alarm' else mmss(t['left_s'])
            rows.append((BELL if t['kind'] == 'alarm' or t['state'] == 'ringing' else TIMER) + t['name'][:14 - len(right)].ljust(15 - len(right)) + right)
        return rows[0], rows[1] if len(rows) > 1 else ''

    def p_kevin(self):
        d = self.live()
        st = d.get('state', 'asleep')
        return MIC + ' %s %s' % (d.get('name', 'Kevin'), st), ' press = talk' if st == 'asleep' else ''

    def render(self):
        if time.time() < self.note_until:
            return self.note_txt
        if any(t['state'] == 'ringing' for t in self.live().get('timers') or []):
            self.page = 0
        return getattr(self, 'p_' + PAGES[self.page])()

    def note(self, a, b=''):
        self.note_txt, self.note_until = (a, b), time.time() + 2

    def key(self, k):
        self.lit_until = time.time() + BRIGHT_S
        if k == 'h':
            self.dark = not self.dark
            return
        if self.dark:
            self.dark = False
            return
        ringing = any(t['state'] == 'ringing' for t in self.live().get('timers') or [])
        if k in 'lr':
            self.page = (self.page + (1 if k == 'r' else -1)) % len(PAGES)
        elif k == 'u':
            self.page = 0
        elif k == 'p':
            r = actions.talk()
            self.note(MIC + (' Listening...' if r.get('listening') else ' Stopped'))
        elif k == 'd':
            if ringing:
                actions.timer('stop')
                self.note(BELL + ' alarm stopped')
            else:
                actions.music_action('stop')
                self.note(MUSIC + ' music stopped')
        self.data_at = 0

    def brightness(self):
        if self.dark:
            return 0
        if time.time() < self.lit_until:
            return 5
        return 1 if self.live().get('quiet') else 4

    def run(self, scr):
        while True:
            for k in scr.keys():
                if k in 'lrudph':
                    self.key(k)
            if time.time() - scr.icons_at > 60:
                scr.icons()                  # the LCD can lose them after a glitch
            scr.backlight(self.brightness())
            scr.show(*self.render())
            time.sleep(0.1)


def start(log=print):
    """Run the screen in the background whenever its serial number is set and it is plugged in."""
    def loop():
        while True:
            path = port((config.load().get('bedside_serial') or '').strip())
            if not path:
                time.sleep(10)
                continue
            try:
                log('bedside screen on %s' % path)
                Bedside(log).run(Screen(path))
            except Exception as e:
                log('bedside screen: %s' % str(e)[:160])
                time.sleep(10)
    threading.Thread(target=loop, daemon=True).start()
