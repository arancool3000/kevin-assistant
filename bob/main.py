"""Kevin's main loop (service bob-assistant): listen for the wake phrase on the Pi, then talk with Gemini Live.

    python -m bob.main
"""
import asyncio
import json
import os
import signal
import sys
import time

from . import audio, bedside, config, live, music, timers, tools, wake

VOSK_MODEL = os.environ.get('BOB_VOSK_MODEL', os.path.join(config.STATE, 'vosk-model'))
STATE_FILE = os.path.join(config.STATE, 'state.json')
WAKE_NOW = os.path.join(config.STATE, 'wake_now')     # made by the web page / bedside screen: talk now, no wake phrase
STOP_NOW = os.path.join(config.STATE, 'stop_now')     # ...or: end this conversation now (live.py checks it)


def take(flag):
    """True once if the flag file exists (and removes it)."""
    try:
        os.unlink(flag)
        return True
    except OSError:
        return False


def log(msg):
    sys.stdout.write('%s %s\n' % (time.strftime('%H:%M:%S'), msg))
    sys.stdout.flush()


_PHRASE = {}


def set_state(s, phrase=None):
    """What Kevin is doing, for the web page (asleep / listening / speaking / working / needs_setup)."""
    if phrase:
        _PHRASE['p'] = phrase
    try:
        os.makedirs(config.STATE, exist_ok=True)
        with open(STATE_FILE + '.tmp', 'w') as f:
            json.dump({'state': s, 'at': time.time(), 'phrase': _PHRASE.get('p')}, f)
        os.replace(STATE_FILE + '.tmp', STATE_FILE)
    except OSError:
        pass


def main():
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    cfg = config.load()
    key = config.load_secrets()['gemini_api_key']
    while not key:
        set_state('needs_setup')
        log('no Gemini API key yet: add it on the web page (http://<this pi>:%s) or in /etc/bob/secrets.json' % cfg['web_port'])
        time.sleep(15)
        cfg, key = config.load(), config.load_secrets()['gemini_api_key']
    try:
        audio.set_volume(cfg.get('volume', 70))
    except Exception as e:
        log('volume not set: %s' % e)
    speaker = audio.Speaker(audio.safe_device(cfg.get('speaker_device')))
    chime = audio.tone()

    def ring_chime(kind, loud):
        """A timer's three bright notes, or an alarm's insistent run; softer in quiet hours (alarms excepted)."""
        if kind == 'alarm':
            for _ in range(3):
                speaker.play(audio.tone((880, 1175, 880, 1175), 140, 0.15 + 0.35 * loud))
                time.sleep(0.9)
        else:
            vol = 0.12 if config.is_quiet(cfg) else 0.3
            speaker.play(audio.tone((1046, 1318, 1568), 150, vol))

    timers.Ringer(ring_chime, log)
    bedside.start(log)
    toolbox = tools.Tools(cfg)
    mic = audio.Mic(audio.safe_device(cfg.get('mic_device'))).start()
    ww = wake.WakeWord(cfg, VOSK_MODEL)
    set_state('asleep')
    speaker.play(audio.tone((660, 990, 1320), 120, 0.2))      # "I'm ready" -- also how a first install says it is done
    if ww.fell_back:
        log('the wake phrase "%s" uses words the offline recogniser does not know: using "hey kevin"' % cfg.get('wake_phrase'))
    set_state('asleep', phrase=ww.phrase)
    log('listening for "%s" (on this Pi; nothing leaves it until then)' % ww.phrase)
    failures = 0
    while True:
        try:
            take(STOP_NOW)                                # a stop pressed while asleep means nothing
            if not ww.wait(mic, stop=lambda: os.path.exists(WAKE_NOW)) and not take(WAKE_NOW):
                continue
        except Exception as e:
            log('listening failed: %s' % e)
            time.sleep(2)
            mic.start()
            continue
        log('woken')
        speaker.play(chime)
        time.sleep(0.25)
        music.duck(True)
        try:
            cfg.update(config.load())                     # settings changed on the web page apply now
            toolbox.cfg = cfg
            why = asyncio.run(live.converse(cfg, config.load_secrets()['gemini_api_key'], mic, speaker, toolbox,
                                            log=log, on_state=set_state))
            log('conversation ended (%s)' % why)
            failures = 0
        except Exception as e:
            failures += 1
            log('conversation failed: %s' % str(e)[:200])
            speaker.play(audio.tone((440, 330), 160, 0.25))     # a low "that didn't work" tone
            time.sleep(min(30, 2 ** failures))
        music.duck(False)
        take(WAKE_NOW)
        set_state('asleep')
        t = time.time()            # a breath before listening again: drop 1.5 s of audio so his own last words can't wake him
        while time.time() - t < 1.5:
            mic.read(timeout=0.5)


if __name__ == '__main__':
    main()
