"""Writing the microSD card on a Mac: the same image writer as Windows (flasher.write_image), with macOS's own
disk tools around it.

  - cards are found with `diskutil` and only external SD / USB disks of a sensible size are offered, never the
    Mac's own disk;
  - writing a raw disk needs administrator rights, so the app asks macOS for them (the normal password prompt)
    and runs itself again as a small helper (`--mac-write`) that does only the writing, reporting progress
    through a file the window reads;
  - afterwards the card is mounted again so the settings can be added, then ejected.
"""
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import tempfile
import time

import flasher


def _plist(args, timeout=30):
    r = subprocess.run(['/usr/sbin/diskutil'] + args, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise IOError((r.stderr or r.stdout).decode('utf-8', 'replace').strip()[:200] or 'diskutil failed')
    return plistlib.loads(r.stdout)


def disk_from_info(info):
    """diskutil info -> the same shape the Windows code uses, so flasher.choose_disks/describe work unchanged."""
    m = re.match(r'^disk(\d+)$', info.get('DeviceIdentifier', ''))
    proto = str(info.get('BusProtocol') or '')
    bus = 'SD' if 'Secure Digital' in proto or 'SD' == proto else 'USB' if 'USB' in proto else proto.upper()
    return {'Number': int(m.group(1)) if m else -1, 'Size': int(info.get('TotalSize') or info.get('Size') or 0), 'Bus': bus,
            'FriendlyName': (info.get('MediaName') or info.get('IORegistryEntryName') or 'Card').strip(),
            'IsBoot': bool(info.get('Internal')) or info.get('MountPoint') == '/',
            'IsSystem': bool(info.get('Internal')) or bool(info.get('APFSContainerReference') and info.get('Internal')),
            'IsOffline': not info.get('WritableMedia', True)}


def list_disks():
    out = []
    for ident in _plist(['list', '-plist', 'external', 'physical']).get('WholeDisks', []):
        try:
            d = disk_from_info(_plist(['info', '-plist', ident]))
            if d['Number'] >= 0:
                out.append(d)
        except Exception:
            pass
    return out


def same_disk(a, b):
    return a['Number'] == b['Number'] and a['Size'] == b['Size']


class RawTarget:
    """/dev/rdiskN, opened by the root helper: unbuffered, and every write is a whole number of sectors."""
    def __init__(self, number):
        self.fd = os.open('/dev/rdisk%d' % int(number), os.O_RDWR)

    def write_at(self, offset, data):
        os.pwrite(self.fd, data, offset)

    def read_at(self, offset, n):
        return os.pread(self.fd, n, offset)

    def flush(self):
        os.fsync(self.fd)

    def close(self):
        os.close(self.fd)


# ---- the root helper ---------------------------------------------------------------------------------

def helper(number, url, size, sha256, status_path, stop_path):
    """Runs as root (asked for by write()). Unmount, write, check; progress goes to status_path as JSON lines."""
    def say(**kw):
        with open(status_path, 'a') as f:
            f.write(json.dumps(kw) + '\n')
    try:
        subprocess.run(['/usr/sbin/diskutil', 'unmountDisk', 'force', '/dev/disk%d' % number], capture_output=True, timeout=60)
        target = RawTarget(number)
        last = {'t': 0}

        def progress(stage, done, total):
            if time.time() - last['t'] > 0.4 or done >= total:
                last['t'] = time.time()
                say(stage=stage, done=done, total=total)
        try:
            flasher.write_image(flasher.http_opener(url), target, size, sha256, progress, lambda: os.path.exists(stop_path))
        finally:
            target.close()
        say(done_ok=True)
        return 0
    except flasher.Cancelled:
        say(error='cancelled')
    except Exception as e:
        say(error=str(e)[:300])
    return 1


def _applescript_string(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def self_command():
    """How to run this app again: the bundled executable, or python + this script while developing."""
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bob_setup.py')]


def write(disk, img, progress, cancel):
    """Ask for admin rights, then write the card in the helper. progress(stage, done, total) as on Windows."""
    work = tempfile.mkdtemp(prefix='kevin-setup-')
    status, stop = os.path.join(work, 'status'), os.path.join(work, 'stop')
    open(status, 'w').close()
    cmd = self_command() + ['--mac-write', str(int(disk['Number'])), img['url'], str(int(img['extract_size'])),
                            img['extract_sha256'], status, stop]
    shell = ' '.join(shlex.quote(c) for c in cmd)
    script = 'do shell script %s with administrator privileges with prompt %s' % (
        _applescript_string(shell), _applescript_string('Kevin Setup needs your password to write the microSD card.'))
    proc = subprocess.Popen(['/usr/bin/osascript', '-e', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    seen, result = 0, {}
    while True:
        if cancel() and not os.path.exists(stop):
            open(stop, 'w').close()
        with open(status) as f:
            f.seek(seen)
            chunk = f.read()
        seen += len(chunk)
        for line in chunk.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if 'stage' in d:
                progress(d['stage'], d['done'], d['total'])
            result.update(d)
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    err = (proc.stderr.read() or b'').decode('utf-8', 'replace')
    if result.get('done_ok'):
        return
    if result.get('error') == 'cancelled':
        raise flasher.Cancelled()
    if 'User canceled' in err or '-128' in err:
        raise IOError('the password was not given, so the card was not touched')
    raise IOError(result.get('error') or err.strip()[:200] or 'the card could not be written')


def boot_volume(number, wait=60):
    """Mount the freshly written card and find its boot partition (the one with config.txt)."""
    subprocess.run(['/usr/sbin/diskutil', 'mountDisk', '/dev/disk%d' % number], capture_output=True, timeout=60)
    end = time.time() + wait
    while time.time() < end:
        try:
            for part in _plist(['list', '-plist', '/dev/disk%d' % number]).get('AllDisksAndPartitions', [{}])[0].get('Partitions', []):
                mp = part.get('MountPoint')
                if mp and os.path.exists(os.path.join(mp, 'config.txt')):
                    return mp
        except Exception:
            pass
        time.sleep(2)
    raise IOError('the card\'s boot partition did not appear: take the card out, put it back, and use "I already wrote the card"')


def eject(path_or_number):
    target = '/dev/disk%d' % path_or_number if isinstance(path_or_number, int) else path_or_number
    return subprocess.run(['/usr/sbin/diskutil', 'eject', target], capture_output=True, timeout=60).returncode == 0


def boot_drives():
    """Mounted volumes that look like a Raspberry Pi OS boot partition (for "I already wrote the card")."""
    out = []
    for name in sorted(os.listdir('/Volumes')):
        root = os.path.join('/Volumes', name)
        if os.path.exists(os.path.join(root, 'config.txt')) and os.path.exists(os.path.join(root, 'cmdline.txt')):
            out.append((root, name))
    return out


def this_mac_wifi():
    for cmd in (['/usr/sbin/networksetup', '-getairportnetwork', 'en0'], ['/usr/sbin/ipconfig', 'getsummary', 'en0']):
        try:
            txt = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
        except Exception:
            continue
        m = re.search(r'Current Wi-Fi Network:\s*(.+)$', txt, re.M) or re.search(r'^\s*SSID\s*:\s*(.+)$', txt, re.M)
        if m and m.group(1).strip() not in ('<redacted>', ''):
            return m.group(1).strip()
    return ''


def saved_wifi_password(ssid):
    """From the Mac's keychain: macOS asks the user to allow it (their own choice, behind a button)."""
    if not ssid:
        return ''
    try:
        r = subprocess.run(['/usr/bin/security', 'find-generic-password', '-D', 'AirPort network password', '-a', ssid, '-w'],
                           capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''
