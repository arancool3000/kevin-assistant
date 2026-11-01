"""YouTube, the TV guide, chess (engine and camera), Gmail and the health checks -- all without network or hardware.

    python3 -m pytest tests/test_features.py
"""
import os
import sys
import tempfile
import time

_T = tempfile.mkdtemp()
os.environ.setdefault('BOB_STATE', _T)
os.environ.setdefault('BOB_ETC', _T)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pytest  # noqa: E402

from bob import chesscam, chessgame, config, gmail, health, music, tools, tvguide, youtube  # noqa: E402


def test_youtube_keeps_short_results_unless_long():
    out = 'a\tSong\t200\nb\tTen hour rain\t36000\nc\tBroken line\nd\tJingle\t10\ne\tLive set\tNA\n'
    assert [r[0] for r in youtube.pick_rows(out, 5)] == ['a']
    assert [r[0] for r in youtube.pick_rows(out, 5, long=True)] == ['a', 'b', 'd', 'e']


def test_youtube_liked_list_and_shuffle(monkeypatch):
    for f in (youtube.LIKED,):
        if os.path.exists(f):
            os.remove(f)
    started = []
    monkeypatch.setattr(music, '_start', lambda urls, vol, shuffle=False: started.append(list(urls)))
    monkeypatch.setattr(music, 'now_playing', lambda: {'playing': True, 'title': 'Song A - Band'})
    assert youtube.play_liked()['error']
    assert youtube.like()['liked'] == 'Song A - Band'                 # what is playing
    youtube.like('Song B')
    youtube.like('Song B')                                            # not twice
    assert [r['song'] for r in youtube.liked()] == ['Song A - Band', 'Song B']
    r = youtube.play_liked(count=10, shuffle=True)
    assert r['ok'] and r['queued'] == 1 and r['shuffled']
    urls = [u for u in started[-1] if not u.startswith('--')]
    assert sorted(urls) == ['ytdl://ytsearch1:Song A - Band', 'ytdl://ytsearch1:Song B']
    assert music._now['kind'] == 'youtube'
    assert youtube.like('song b', remove=True)['removed'] == 1


def test_tv_guide_channels_and_now_next():
    assert tvguide.channel_key('BBC1') == 'one' and tvguide.channel_key('bbc news') == 'news'
    assert tvguide.channel_key('') is None and tvguide.channel_key('ITV') is False
    assert tvguide.service('one', {'tv_bbc_one': 'bbc_one_scotland'}) == 'bbc_one_scotland'
    assert tvguide.guide({}, 'ITV')['error']
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 11, 1, 19, 30, tzinfo=timezone.utc).astimezone()

    def item(start, mins, brand, ep=None):
        s = start.astimezone(timezone.utc)
        return {'published_time': {'start': s.strftime('%Y-%m-%dT%H:%M:%SZ'),
                                   'end': (s + timedelta(minutes=mins)).strftime('%Y-%m-%dT%H:%M:%SZ')},
                'brand': {'title': brand}, 'episode': {'title': ep}}
    items = [item(now - timedelta(hours=2), 60, 'Old'), item(now - timedelta(minutes=30), 60, 'Quiz', 'Final'),
             item(now - timedelta(minutes=30), 60, 'Quiz', 'Final'), item(now + timedelta(minutes=30), 30, 'News')]
    rows = tvguide.programmes(items, now)
    assert [r[2] for r in rows] == ['Quiz: Final', 'News']            # the finished one and the duplicate are gone
    s = tvguide.summary('BBC One', rows, 'now', now)
    assert s.startswith('BBC One: Quiz: Final now') and 'then News' in s


def test_chess_moves_are_understood():
    assert chessgame.normalise_move('e2 to e4') == 'e2e4'
    assert chessgame.normalise_move('G1-F3') == 'g1f3'
    assert chessgame.normalise_move('e7 e8 queen') == 'e7e8q'
    assert chessgame.normalise_move('castle') is None


def test_chess_game_against_the_engine(monkeypatch):
    chess = pytest.importorskip('chess')
    monkeypatch.setattr(chessgame, 'engine_move', lambda b, *a, **k: sorted(b.legal_moves, key=lambda m: m.uci())[0])
    r = chessgame.new_game('white', 900)
    assert r['you_are'] == 'white' and r['elo'] == 900
    assert chessgame.play('e2 e5')['error']                           # illegal
    r = chessgame.play('e2 to e4')
    assert r['your_move'] == 'e4' and r['engine_move'] and r['turn'] == 'white' and r['moves'] == 2
    t = tools.Tools({})
    assert 'Pe4' not in t.t_chess_board()['pieces'] and 'e4' in t.t_chess_board()['pieces']
    assert chessgame.undo()['took_back'] == 2
    assert chessgame.board_of(chessgame.load()).fen() == chess.STARTING_FEN
    assert t.t_chess_set_elo(5000)['elo'] == 3190


def test_camera_and_gmail_tools_are_off_until_switched_on():
    names = lambda cfg: {d['name'] for d in tools.Tools(cfg).builtin_declarations()}   # noqa: E731
    base = names({})
    assert 'chess_see_move' not in base and 'gmail_inbox' not in base
    assert {'youtube_play', 'tv_guide', 'chess_move', 'health_report'} <= base
    assert 'chess_see_move' in names({'chess_camera': '/dev/video0'})
    assert config.DEFAULTS['chess_camera'] == '' and config.DEFAULTS['gmail_enabled'] is False
    assert 'gmail_inbox' not in names({'gmail_enabled': True})        # switched on but no credentials: still off
    assert tools.Tools({}).call('chess_see_move', {})['error'].startswith('the chess camera is off')
    assert 'Gmail is off' in tools.Tools({}).call('gmail_inbox', {})['error']


def test_camera_reads_a_move_from_changed_squares():
    chess = pytest.importorskip('chess')
    np = pytest.importorskip('numpy')
    b = chess.Board()
    d = np.zeros((8, 8), dtype=np.float32)
    d[1, 4] = d[3, 4] = 30.0                                          # e2 and e4 changed
    assert chesscam.pick_move(b, None, d)[0] == 'e2e4'
    assert chesscam.pick_move(b, None, np.zeros((8, 8), dtype=np.float32))[0] is None
    b.push_uci('e2e4')
    b.push_uci('e7e5')                                                # the engine's reply, then the user's Nf3
    d = np.zeros((8, 8), dtype=np.float32)
    for r, f in ((6, 4), (4, 4), (0, 6), (2, 5)):
        d[r, f] = 25.0
    assert chesscam.pick_move(b, chess.Move.from_uci('e7e5'), d)[0] == 'g1f3'
    assert chesscam.parse_corners('10,90 90,90 90,10 10,10', 200, 100) == [[20, 90], [180, 90], [180, 10], [20, 10]]
    with pytest.raises(ValueError):
        chesscam.parse_corners('1 2 3', 200, 100)


def test_gmail_setup_helpers_hold_no_secrets():
    link = gmail.auth_link('my-client-id')
    assert 'gmail.readonly' in link and 'client_secret' not in link
    assert gmail.code_from('http://localhost/?code=4/abc&scope=x') == '4/abc'
    assert gmail.code_from('4/xyz') == '4/xyz'
    with pytest.raises(ValueError):
        gmail.code_from('http://localhost/?error=access_denied')
    assert gmail._sender('"Jane Doe" <jane@example.com>') == 'Jane Doe'
    assert gmail._sender('<only@example.com>') == 'only@example.com'


def test_bug_watcher_finds_crashes_and_skips_transcripts():
    lines = ['Nov 01 10:00:00 pi python[1]: heard: Traceback (most recent call last)',
             'Nov 01 10:00:01 pi python[1]: Traceback (most recent call last):',
             'Nov 01 10:00:01 pi python[1]:   File "/opt/bob-assistant/bob/music.py", line 42, in play',
             'Nov 01 10:00:01 pi python[1]:     x = y',
             'Nov 01 10:00:01 pi python[1]: NameError: name \'y\' is not defined',
             'Nov 01 10:00:02 pi python[1]: said: ValueError: not a bug']
    assert health.tracebacks(lines) == [("NameError: name 'y' is not defined", 'music.py:42 in play')]


def test_self_heal_restarts_failed_units_with_a_cooldown():
    done, restarted = {}, []
    svc = {'bob-assistant': 'failed', 'bob-assistant-web': 'active', 'bob-assistant-skills': 'inactive'}
    now = time.time()
    assert health.heal(svc, done, now, restarted.append) == ['bob-assistant', 'bob-assistant-skills']
    assert health.heal(svc, done, now + 60, restarted.append) == []            # cooling down
    assert health.heal(svc, done, now + health.COOLDOWN + 1, restarted.append) == ['bob-assistant', 'bob-assistant-skills']
    assert restarted.count('bob-assistant-web') == 0
