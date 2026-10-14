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


def test_mac_helper_writes_and_reports(tmp_path=None):
    """The Mac's root helper, with a file standing in for /dev/rdiskN and a local 'download'."""
    import hashlib
    import io
    import lzma
    import flasher
    import flasher_mac
    tmp = str(tmp_path or tempfile.mkdtemp())
    img = os.urandom(3 << 20)
    xz = lzma.compress(img)
    card = os.path.join(tmp, 'card.img')
    status, stop = os.path.join(tmp, 'status'), os.path.join(tmp, 'stop')
    saved = (flasher_mac.RawTarget, flasher.http_opener, flasher_mac.subprocess.run)
    flasher_mac.RawTarget = lambda n: flasher.FileTarget(card)
    flasher.http_opener = lambda url: (lambda off: io.BytesIO(xz[off:]))
    flasher_mac.subprocess.run = lambda *a, **k: None              # no diskutil here
    try:
        assert flasher_mac.helper(4, 'x', len(img), hashlib.sha256(img).hexdigest(), status, stop) == 0
    finally:
        flasher_mac.RawTarget, flasher.http_opener, flasher_mac.subprocess.run = saved
    lines = [json.loads(x) for x in open(status)]
    assert lines[-1] == {'done_ok': True} and any(x.get('stage') == 'verify' for x in lines)
    assert open(card, 'rb').read()[:len(img)] == img


def test_mac_disk_shapes():
    import flasher
    import flasher_mac
    sd = flasher_mac.disk_from_info({'DeviceIdentifier': 'disk4', 'BusProtocol': 'Secure Digital', 'TotalSize': 31914983424,
                                     'MediaName': 'SD Card Reader', 'Internal': False, 'WritableMedia': True})
    inside = flasher_mac.disk_from_info({'DeviceIdentifier': 'disk0', 'BusProtocol': 'Apple Fabric', 'TotalSize': 10 ** 12, 'Internal': True})
    assert flasher.choose_disks([sd, inside]) == [sd]                  # never the Mac's own disk
    assert 'SD Card Reader' in flasher.describe(sd)


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
    print('%d passed' % n)
