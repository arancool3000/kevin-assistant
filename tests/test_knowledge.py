import datetime
import io
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bob import knowledge  # noqa: E402

K = knowledge.KnowledgeTools({'latitude': 53.8, 'longitude': -1.55, 'timezone': 'Europe/London', 'town': 'Leeds'})


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(payload, seen=None):
    def urlopen(req, timeout=None):
        assert timeout == 10
        if seen is not None:
            seen.append(req.full_url if hasattr(req, 'full_url') else req)
        return _Resp(json.dumps(payload).encode())
    return urlopen


def _with_net(payload, fn, seen=None):
    real = urllib.request.urlopen
    urllib.request.urlopen = _fake(payload, seen)
    try:
        return fn()
    finally:
        urllib.request.urlopen = real


def test_declarations_match_methods():
    for d in knowledge.DECLARATIONS:
        assert hasattr(K, 't_' + d['name']), d['name']
        assert d['parameters']['type'] == 'OBJECT'


def test_calculate():
    assert K.t_calculate('2+3*4')['result'] == 14
    assert K.t_calculate('-(2**3) + sqrt(16)')['result'] == -4
    assert K.t_calculate('10/4')['result'] == 2.5
    assert abs(K.t_calculate('pi*2')['result'] - 6.2831853072) < 1e-9
    for bad in ('__import__("os").system("echo hi")', 'open("x")', '().__class__', '9**9**9', '2**100000', '1/0', 'x+1'):
        assert 'error' in K.t_calculate(bad), bad


def test_convert_units():
    assert K.t_convert_units(1, 'mi', 'km')['result'] == 1.609
    assert K.t_convert_units(100, 'c', 'f')['result'] == 212
    assert K.t_convert_units(32, 'f', 'c')['result'] == 0
    assert K.t_convert_units(0, 'c', 'k')['result'] == 273.15
    assert K.t_convert_units(1, 'pint', 'ml')['result'] == 568.261
    assert 'error' in K.t_convert_units(1, 'kg', 'km')
    assert 'error' in K.t_convert_units(1, 'parsec', 'km')


def test_countdown_to():
    t = datetime.date.today()
    r = K.t_countdown_to('25 December')
    assert 0 <= r['days'] <= 366 and 'December' in r['date']
    far = (t + datetime.timedelta(days=10)).isoformat()
    assert K.t_countdown_to(far)['days'] == 10
    assert K.t_countdown_to('christmas')['days'] == r['days']
    assert 0 <= K.t_countdown_to('new year')['days'] <= 366
    assert 'error' in K.t_countdown_to('whenever')


def test_moon_phase_shape():
    r = K.t_moon_phase()
    assert 0 <= r['illumination_pct'] <= 100 and r['phase'] and r['next_full_moon']
    assert 0 <= r['days_to_full_moon'] <= 30


def test_spell_word_and_random_tools():
    assert K.t_spell_word('cat') == {'word': 'cat', 'spelled': 'C A T', 'letters': 3}
    for _ in range(200):
        r = K.t_roll_dice(sides=6, count=2)
        assert all(1 <= x <= 6 for x in r['rolls']) and r['total'] == sum(r['rolls'])
        assert 5 <= K.t_random_number(5, 7)['number'] <= 7
    assert K.t_flip_coin()['result'] in ('heads', 'tails')
    assert K.t_pick_one('a, b ,c')['choice'] in 'abc'


def test_no_location_gives_error():
    r = knowledge.KnowledgeTools({'latitude': None, 'town': ''}).t_uv_index()
    assert 'settings' in r['error']


def test_uv_index_with_canned_reply():
    d = {'current': {'uv_index': 1.2}, 'daily': {'uv_index_max': [5.4]}}
    r = _with_net(d, K.t_uv_index)
    assert r['uv_max_today'] == 5.4 and r['level'] == 'moderate' and 'sun cream' in r['advice']


def test_currency_convert_with_canned_reply():
    seen = []
    r = _with_net({'amount': 10.0, 'base': 'GBP', 'date': '2026-10-13', 'rates': {'USD': 13.456}},
                  lambda: K.t_currency_convert(10, 'gbp', 'usd'), seen)
    assert r['result'] == 13.46 and r['to'] == 'USD' and 'frankfurter' in seen[0]


def test_trivia_unescapes_and_includes_answer():
    d = {'results': [{'category': 'Art &amp; Design', 'question': 'Who painted &quot;Guernica&quot;?', 'correct_answer': 'Pablo Picasso',
                      'incorrect_answers': ['Dal&iacute;', 'Monet', 'Goya']}]}
    r = _with_net(d, K.t_trivia_question)
    assert r['question'] == 'Who painted "Guernica"?' and r['answer'] == 'Pablo Picasso'
    assert len(r['options']) == 4 and 'Dalí' in r['options'] and r['category'] == 'Art & Design'


def test_network_failure_is_an_error_dict_not_a_raise():
    def boom(req, timeout=None):
        raise OSError('offline')
    real = urllib.request.urlopen
    urllib.request.urlopen = boom
    try:
        assert 'error' in K.t_tell_joke()
    finally:
        urllib.request.urlopen = real


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
    print('%d passed' % n)
