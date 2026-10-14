"""Timers and alarms, quiet hours, conversation cues, the phone/bedside actions and the bedside pages.

    python3 tests/test_parity.py      (or pytest)
"""
import datetime as dt
import json
import os
import sys
import tempfile
import time

_T = tempfile.mkdtemp()
os.environ.setdefault('BOB_STATE', _T)
os.environ.setdefault('BOB_ETC', _T)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from bob import actions, bedside, config, live, timers   # noqa: E402

TMP = config.STATE        # whichever folder bob.config settled on (another test file may have imported it first)
os.makedirs(TMP, exist_ok=True)


def _reset():
    for f in ('timers.json', 'state.json', 'wake_now', 'stop_now'):
        try:
            os.unlink(os.path.join(TMP, f))
        except OSError:
            pass


def test_timer_lifecycle():
    _reset()
    timers.add_timer(300, 'pasta')
    timers.add_timer(60, '')
    v = timers.view()
    assert [t['name'] for t in v] == ['timer 2', 'pasta']          # soonest first, unnamed get a number
    assert timers.change('pasta', 'pause') == ['pasta']
    assert [t for t in timers.view() if t['name'] == 'pasta'][0]['state'] == 'paused'
    timers.change('pasta', 'add', 120)
    assert abs([t for t in timers.view() if t['name'] == 'pasta'][0]['left_s'] - 420) <= 1
    timers.change('pasta', 'resume')
    assert timers.change('all', 'cancel') and timers.view() == []


def test_alarm_clock_parsing():
    now = dt.datetime(2026, 10, 14, 18, 0)
    assert timers.parse_clock('7:30', now) == dt.datetime(2026, 10, 15, 7, 30)
    assert timers.parse_clock('7 pm', now) == dt.datetime(2026, 10, 14, 19, 0)
    assert timers.parse_clock('12 am', now) == dt.datetime(2026, 10, 15, 0, 0)
    for bad in ('25:00', 'soon', '7:61'):
        try:
            timers.parse_clock(bad, now)
            assert False, bad
        except ValueError:
            pass


def test_ringer_rings_then_stop_and_snooze():
    _reset()
    rung = []
    timers.add_timer(0.2, 'eggs')
    r = timers.Ringer(lambda kind, loud: rung.append((kind, loud)), log=lambda m: None)
    time.sleep(1.5)
    assert rung and rung[0][0] == 'timer'
    assert timers.view()[0]['state'] == 'ringing'
    assert actions.timer('snooze')['ok']
    t = timers.view()[0]
    assert t['state'] == 'waiting' and 500 < t['left_s'] <= 540
    assert actions.timer('stop', t['id'])['ok'] and timers.view() == []
    assert r


def test_quiet_hours_wrap_midnight():
    c = dict(config.DEFAULTS, quiet_from=22, quiet_to=7)
    at = lambda h: time.struct_time((2026, 10, 14, h, 0, 0, 2, 287, 0))   # noqa: E731
    assert config.is_quiet(c, at(23)) and config.is_quiet(c, at(3)) and not config.is_quiet(c, at(12))
    assert not config.is_quiet(dict(c, quiet_enabled=False), at(23))
    assert config.is_quiet(dict(c, quiet_from=13, quiet_to=15), at(14))


def test_conversation_cues():
    assert live.heard_cue('thanks kevin') == 'close'
    assert live.heard_cue('thank you, one more thing') == 'hold'
    assert live.heard_cue('hang on a second') == 'hold'
    assert live.heard_cue('what is the weather') is None
    assert live.heard_cue('tasty pasta') is None


def test_talk_button_flags():
    _reset()
    json.dump({'state': 'asleep'}, open(os.path.join(TMP, 'state.json'), 'w'))
    assert actions.talk()['listening'] and os.path.exists(actions.WAKE_NOW)
    json.dump({'state': 'listening'}, open(os.path.join(TMP, 'state.json'), 'w'))
    assert not actions.talk()['listening'] and os.path.exists(actions.STOP_NOW)


def test_bedside_pages_fit():
    _reset()
    b = bedside.Bedside(log=lambda m: None)
    b.data_at = time.time() + 999
    b.data = {'name': 'Kevin', 'state': 'asleep', 'quiet': True, 'music': {'playing': False},
              'weather': {'now': {'temp_c': 17.6, 'code': 3, 'sky': 'overcast'}, 'today': {'low_c': 10, 'high_c': 19, 'rain_chance_pct': 40}},
              'timers': [{'id': 1, 'name': 'a very long timer name', 'kind': 'timer', 'left_s': 272, 'state': 'waiting', 'due': '18:52'},
                         {'id': 2, 'name': 'alarm', 'kind': 'alarm', 'left_s': 45000, 'state': 'waiting', 'due': '07:30'}]}
    for i in range(len(bedside.PAGES)):
        b.page = i
        for line in b.render():
            assert len(bedside.fit(line)) == 16
    b.page = 0
    assert '4:32' in b.render()[1]
    assert b.brightness() == 1                    # quiet hours: dim
    b.data['timers'][0]['state'] = 'ringing'
    b.page = 2
    assert 'DONE' in b.render()[1] and b.page == 0   # a ringing alarm jumps to Home


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
    print('%d passed' % n)
