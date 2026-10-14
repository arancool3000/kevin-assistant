"""Kevin Setup's helpers that don't need Windows or a window.  python3 tests/test_setup_helpers.py (or pytest)"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'setup-windows'))
import bob_setup as b   # noqa: E402


def test_netsh_parsing():
    out = '    Name : Wi-Fi\n    SSID                   : Home Net 5G\n    BSSID                  : aa:bb:cc:dd:ee:ff\n'
    assert b.parse_netsh_ssid(out) == 'Home Net 5G'
    assert b.parse_netsh_ssid('nothing here') == ''
    assert b.parse_netsh_key('    Key Content            : pa ss:word\n') == 'pa ss:word'
    assert b.parse_netsh_key('Security key : Absent') == ''


def test_strong_password():
    pw = b.strong_password()
    assert len(pw) == 14 and not set(pw) & set('0O1lI')
    assert b.strong_password() != pw


def test_answers_never_keep_secrets():
    b.SAVED = os.path.join(tempfile.mkdtemp(), 'answers.json')
    b.save_answers({'town': 'Leeds', 'password': 'x', 'web_password': 'y', 'gemini_api_key': 'z', 'wifi_password': 'w'})
    saved = json.load(open(b.SAVED))
    assert not {'password', 'web_password', 'gemini_api_key', 'wifi_password'} & set(saved)
    assert b.load_answers() == {'town': 'Leeds'}          # empty answers keep the defaults


def test_gradient_ends():
    assert b.gradient(0) == '#2f8cff' and b.gradient(1) == '#a65cf0'


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
    print('%d passed' % n)
