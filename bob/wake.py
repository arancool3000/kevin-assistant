"""The wake phrase, heard on the Pi itself (Vosk, offline): nothing leaves the Pi until "hey kevin" is heard.

The recogniser is limited to the wake phrase plus "[unk]" (anything else), which makes it fast and hard to
fool, and a word must reach a confidence bar set by the sensitivity setting (0-100 %).
"""
import json
import os
import time

from . import audio


def min_confidence(sensitivity):
    """55 % -> 0.675. Higher sensitivity = a lower bar = wakes more easily."""
    s = max(0, min(100, float(sensitivity)))
    return round(0.95 - 0.5 * s / 100.0, 3)


def decide(words, phrase, sensitivity):
    """Vosk's word list (with confidences) -> did that contain the wake phrase, confidently enough?"""
    want = phrase.lower().split()
    if not want:
        return False
    got = [w for w in words if w.get('word') and w['word'] != '[unk]']
    texts = [w['word'].lower() for w in got]
    bar = min_confidence(sensitivity)
    for i in range(len(texts) - len(want) + 1):
        if texts[i:i + len(want)] == want:
            confs = [got[i + k].get('conf', 0) for k in range(len(want))]
            if min(confs) >= bar:
                return True
    return False


def known_words(model_dir):
    """The words the offline model can hear, when the model ships a word list (the small English one does not:
    then vocab() asks the model itself)."""
    try:
        with open(os.path.join(model_dir, 'graph', 'words.txt'), encoding='utf-8') as f:
            return {line.split()[0] for line in f if line.strip()}
    except OSError:
        return None


_MODEL = {'m': None, 'dir': None, 'used': 0.0}


def _model(model_dir):
    """A loaded Vosk model, kept for a few minutes (the settings page checks phrases with it too)."""
    if _MODEL['m'] is not None and _MODEL['dir'] == model_dir:
        _MODEL['used'] = time.time()
        return _MODEL['m']
    try:
        import vosk
        vosk.SetLogLevel(-1)
        if not os.path.isdir(model_dir):
            return None
        _MODEL.update(m=vosk.Model(model_dir), dir=model_dir, used=time.time())
        return _MODEL['m']
    except Exception:
        return None


def release_model(idle=600):
    if _MODEL['m'] is not None and time.time() - _MODEL['used'] > idle:
        _MODEL.update(m=None, dir=None)


def unknown_words(words, model_dir, model=None):
    """Which of these words the offline recogniser cannot hear. None if that cannot be checked here."""
    vocab = known_words(model_dir)
    if vocab is not None:
        return [w for w in words if w not in vocab]
    m = model or _model(model_dir)
    if m is None or not hasattr(m, 'find_word'):
        return None
    return [w for w in words if m.find_word(w) == -1]


def words_of(phrase):
    return [w for w in str(phrase or '').lower().replace(',', ' ').replace('-', ' ').split() if w]


def check_phrase(phrase, model_dir, model=None):
    """None if the phrase is usable, else a reason to read out or show."""
    words = words_of(phrase)
    if not 1 <= len(words) <= 4:
        return 'use one to four words, e.g. "hey kevin"'
    if any(not w.isalpha() for w in words):
        return 'letters only, no numbers or symbols'
    unknown = unknown_words(words, model_dir, model)
    if unknown:
        return 'the offline recogniser does not know %s: pick ordinary English words' % ', '.join('"%s"' % w for w in unknown)
    return None


COMMON = set("""a an the and or but so to of in on at it is be am are was i you me my your we he she they this that
yes no not ok okay hey hi hello oh um uh go do get got can will just like what how why when where who now then
there here come look see well right good thanks thank please one two up down out off all some""".split())


def _syllables(word):
    groups, prev = 0, False
    for ch in word:
        v = ch in 'aeiouy'
        if v and not prev:
            groups += 1
        prev = v
    if word.endswith('e') and groups > 1 and not word.endswith(('le', 'ee')):
        groups -= 1
    return max(1, groups)


def tips(phrase):
    """Plain advice about how well a phrase will work (it can still be used): accidental wakes and missed ones."""
    words = words_of(phrase)
    out = []
    if not words:
        return out
    syl = sum(_syllables(w) for w in words)
    if len(words) == 1:
        out.append('a single word wakes me by accident more often: two or three words work best, like "hey %s"' % words[0])
    if syl < 3:
        out.append('it is very short (%d syllables), so everyday talk may set it off: 3 to 5 syllables is best' % syl)
    if all(w in COMMON for w in words):
        out.append('every word is a very common one, so ordinary conversation may wake me')
    if syl > 7:
        out.append('it is long, so it may be missed when said quickly')
    return out


def suggestions(name, model_dir, model=None):
    """Wake phrases that the recogniser knows, built from the assistant's name first."""
    n = words_of(name)[:1]
    base = (['hey ' + n[0], 'okay ' + n[0], 'hello ' + n[0]] if n else []) + \
        ['hey kevin', 'hey computer', 'hello robot', 'hey buddy', 'okay assistant']
    out = []
    for p in base:
        if p not in out and not check_phrase(p, model_dir, model):
            out.append(p)
    return out[:6]


# ---- what was heard (the settings page's "Test it", and tuning the sensitivity) --------------------------

def _state_dir():
    from . import config
    return config.STATE


def log_event(phrase, conf, bar, woke):
    """One line per time the phrase was heard, woken or not (no audio and no other words are kept)."""
    path = os.path.join(_state_dir(), 'wake_log.json')
    try:
        with open(path) as f:
            rows = json.load(f)
    except (OSError, ValueError):
        rows = []
    rows = (rows + [{'at': time.time(), 'phrase': phrase, 'conf': round(conf, 2), 'bar': bar, 'woke': bool(woke)}])[-20:]
    try:
        with open(path + '.tmp', 'w') as f:
            json.dump(rows, f)
        os.replace(path + '.tmp', path)
    except OSError:
        pass


def recent_events(n=8):
    try:
        with open(os.path.join(_state_dir(), 'wake_log.json')) as f:
            return json.load(f)[-n:][::-1]
    except (OSError, ValueError):
        return []


def test_mode_until():
    try:
        with open(os.path.join(_state_dir(), 'wake_test_until')) as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def set_test_mode(seconds):
    path = os.path.join(_state_dir(), 'wake_test_until')
    with open(path, 'w') as f:
        f.write(str(time.time() + seconds if seconds else 0))


def heard(words, phrase, sensitivity):
    """(the phrase was heard at all, its weakest word's confidence, the bar it had to reach)."""
    want = phrase.lower().split()
    got = [w for w in words if w.get('word') and w['word'] != '[unk]']
    texts = [w['word'].lower() for w in got]
    best = None
    for i in range(len(texts) - len(want) + 1):
        if texts[i:i + len(want)] == want:
            c = min(got[i + k].get('conf', 0) for k in range(len(want)))
            best = c if best is None else max(best, c)
    return best is not None, best or 0.0, min_confidence(sensitivity)


def _music_on():
    try:
        from . import music
        return music.playing()
    except Exception:
        return False


class WakeWord:
    def __init__(self, cfg, model_dir):
        import vosk
        vosk.SetLogLevel(-1)
        if not os.path.isdir(model_dir):
            raise RuntimeError('the wake word model is missing at %s (run install.sh again)' % model_dir)
        self.cfg = cfg
        self.model_dir = model_dir
        self.model = vosk.Model(model_dir)
        self.wanted = ''
        self.phrase = 'hey kevin'
        self.fell_back = False
        self.problem = ''
        self.use(cfg.get('wake_phrase', ''))

    def use(self, phrase):
        """Switch to a phrase (or fall back to "hey kevin" if the recogniser cannot hear it). Returns the problem, if any."""
        phrase = ' '.join(words_of(phrase))
        self.wanted = phrase
        why = check_phrase(phrase, self.model_dir, self.model) if phrase else 'no wake phrase set'
        self.phrase = phrase if not why else 'hey kevin'
        self.fell_back = bool(why) and phrase != 'hey kevin'
        self.problem = why or ''
        return why

    def _config_phrase(self):
        """The phrase saved in the settings now (changed on the page or by voice): read cheaply, every 2 s."""
        from . import config
        c = config.load()
        self.cfg['wake_sensitivity'] = c.get('wake_sensitivity', self.cfg.get('wake_sensitivity', 55))
        return ' '.join(words_of(c.get('wake_phrase', '')))

    def wait(self, mic, stop=None, on_change=None):
        """Block until the wake phrase is heard (returns True), or stop() says to give up (returns False).
        A new phrase saved in the settings is picked up within two seconds, with no restart."""
        import vosk
        rec, rec_phrase, checked = None, None, 0.0
        while True:
            if stop and stop():
                return False
            if time.time() - checked > 2:
                checked = time.time()
                try:
                    want = self._config_phrase()
                    if want and want != self.wanted:
                        self.use(want)
                        if on_change:
                            on_change(self)
                except Exception:
                    pass
            if rec is None or rec_phrase != self.phrase:
                rec = vosk.KaldiRecognizer(self.model, audio.RATE_IN, json.dumps([self.phrase, '[unk]']))
                rec.SetWords(True)
                rec_phrase = self.phrase
            data = mic.read()
            if not data:
                time.sleep(0.5)
                mic.start()
                continue
            if rec.AcceptWaveform(data):
                r = json.loads(rec.Result())
                found, conf, bar = heard(r.get('result', []), self.phrase, self.cfg.get('wake_sensitivity', 55))
                if found:
                    if conf < bar + 0.12 and _music_on():
                        bar = round(bar + 0.12, 3)    # lyrics can sound like the phrase: with music on, be surer
                    woke = conf >= bar
                    log_event(self.phrase, conf, bar, woke)
                    if woke:
                        return True
