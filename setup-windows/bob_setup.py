"""Kevin Setup for Windows.

Two ways to set up a Raspberry Pi as Kevin:

  1. Write a microSD card  (recommended, for a brand-new Pi)
     Choose the card: the app downloads Raspberry Pi OS Lite (64-bit) from raspberrypi.com, writes and checks it
     (flasher.py), then writes your Wi-Fi, a login, SSH, and Kevin's settings (Gemini key, name, town,
     settings-page password) onto it. Put the card in the Pi and power it on: it joins your Wi-Fi and installs
     Kevin by itself (10-20 minutes the first time). A card already flashed with Raspberry Pi Imager (no
     customisation) can have just the settings added.

  2. Install on a Pi that is already running
     Give its address, user name and password; the app installs Kevin over the network (SSH) and shows progress.

Nothing is sent anywhere except to your own Pi (the only download is the Raspberry Pi OS image). The Gemini key
and passwords sit on the card only until first boot, when the installer moves them into a file only Kevin can read
and deletes the copy on the card.
"""
import json
import os
import re
import secrets
import string
import sys
import threading
import webbrowser

import flasher

REPO = 'arancool3000/kevin-assistant'
try:
    from _version import TAG            # written by the release workflow: the app installs its own release
except ImportError:
    TAG = 'main'
INSTALL_URL = 'https://raw.githubusercontent.com/%s/%s/install.sh' % (REPO, TAG)
KEY_URL = 'https://aistudio.google.com/apikey'
COUNTRIES = ['GB', 'US', 'IE', 'CA', 'AU', 'NZ', 'DE', 'FR', 'ES', 'IT', 'NL', 'BE', 'SE', 'NO', 'DK', 'FI', 'PL',
             'PT', 'CH', 'AT', 'IN', 'JP', 'SG', 'ZA', 'BR', 'MX']
VOICES = ['Charon', 'Puck', 'Kore', 'Fenrir', 'Aoede', 'Leda', 'Orus', 'Zephyr']


# ---- what goes on the card (pure functions: tested on any OS) -----------------------------------------

def _yaml_str(s):
    """A YAML double-quoted string, safe for any password or Wi-Fi name."""
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'


RESERVED_USERS = {'root', 'bob-assistant', 'bob-skill', 'daemon', 'nobody'}


def _common(d, errs):
    if not d.get('gemini_api_key', '').strip():
        errs.append('Gemini API key is empty (get one free at aistudio.google.com/apikey)')
    if len(d.get('web_password', '')) < 6:
        errs.append('Settings page password: at least 6 characters')


def validate_card(d):
    """Checks for preparing a new SD card."""
    errs = []
    if not re.match(r'^[a-z]([a-z0-9-]{0,30}[a-z0-9])?$', d.get('hostname', '')):
        errs.append('Pi name: lower case letters, digits and -, starting with a letter, not ending in - (e.g. bob)')
    if not re.match(r'^[a-z_][a-z0-9_-]{0,30}$', d.get('username', '')) or d.get('username') in RESERVED_USERS:
        errs.append('User name: lower case letters and digits, not root (e.g. pi)')
    if len(d.get('password', '')) < 8:
        errs.append('Pi password: at least 8 characters')
    ssid = d.get('wifi_ssid', '')
    if not ssid:
        errs.append('Wi-Fi name is empty')
    elif len(ssid.encode('utf-8')) > 32:
        errs.append('Wi-Fi name: at most 32 bytes')
    pw = d.get('wifi_password', '')
    if pw and not (8 <= len(pw) <= 63 or re.match(r'^[0-9a-fA-F]{64}$', pw)):
        errs.append('Wi-Fi password: 8 to 63 characters (or empty for an open network)')
    _common(d, errs)
    return errs


def validate_ssh(d):
    """Checks for installing on a Pi that is already running (no Wi-Fi or new password needed)."""
    errs = []
    if not d.get('username'):
        errs.append('User name: the one you log in to the Pi with')
    if not d.get('password'):
        errs.append('Pi password: the one you log in to the Pi with')
    _common(d, errs)
    return errs


validate = validate_card            # older name, kept for scripts


def firstboot_json(d):
    out = {k: d.get(k, '') for k in ('gemini_api_key', 'web_password', 'name', 'wake_phrase', 'town', 'voice')}
    out['kindlehub_helper'] = d.get('kindlehub_helper') is True        # "Help run KindleHub": off unless ticked
    return json.dumps(out, indent=2)


def firstboot_script(country='GB'):
    """Runs on the Pi at first boot (as a service that retries until it succeeds): Wi-Fi on, clock right,
    then the installer. Its log is /var/log/bob-install.log."""
    return '\n'.join([
        '#!/bin/bash',
        '# Kevin first boot: installs Kevin, then switches itself off. Log: /var/log/bob-install.log',
        'exec >>/var/log/bob-install.log 2>&1',
        'set -o pipefail',
        'export HOME=/root DEBIAN_FRONTEND=noninteractive',
        'echo "== first boot $(date)"',
        'rfkill unblock wifi 2>/dev/null; for f in /var/lib/systemd/rfkill/*:wlan; do [ -e "$f" ] && echo 0 > "$f"; done',
        'command -v raspi-config >/dev/null && raspi-config nonint do_wifi_country %s' % country,
        'for i in $(seq 1 120); do curl -fsS -o /dev/null --max-time 10 https://github.com && break; sleep 5; done',
        'for i in $(seq 1 60); do [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ] && break; sleep 5; done',
        'curl -fsSL --retry 5 --retry-all-errors -o /root/bob-install.sh %s || exit 1' % INSTALL_URL,
        'bash /root/bob-install.sh --config /etc/bob/firstboot.json || exit 1',
        'rm -f /root/bob-install.sh',
        'systemctl disable bob-firstboot.service',
        'echo "== Kevin installed $(date)"',
        '',
    ])


FIRSTBOOT_SERVICE = (
    '[Unit]\nDescription=Install Kevin on first boot\nAfter=network-online.target time-sync.target\nWants=network-online.target\n'
    '[Service]\nType=oneshot\nExecStart=/bin/bash /usr/local/sbin/bob-firstboot.sh\nRestart=on-failure\nRestartSec=60\n'
    'TimeoutStartSec=3600\n[Install]\nWantedBy=multi-user.target\n')


def cloud_init_files(d):
    """user-data, network-config and meta-data for Raspberry Pi OS images that use cloud-init (2025 onwards)."""
    groups = 'users,adm,dialout,audio,netdev,video,plugdev,input,gpio,spi,i2c,render,sudo'
    def block(path, perm, text):
        return ['  - path: %s' % path, '    permissions: "%s"' % perm, '    content: |'] + \
            ['      ' + line for line in text.splitlines()]
    user_data = '\n'.join([
        '#cloud-config',
        '# written by Kevin Setup',
        'hostname: %s' % d['hostname'],
        'manage_etc_hosts: true',
        'users:',
        '  - name: %s' % d['username'],
        '    groups: %s' % groups,
        '    shell: /bin/bash',
        '    lock_passwd: false',
        '    sudo: ALL=(ALL) NOPASSWD:ALL',
        'chpasswd:',
        '  expire: false',
        '  users:',
        '    - {name: %s, password: %s, type: text}' % (d['username'], _yaml_str(d['password'])),
        'ssh_pwauth: true',
        'apt:',
        '  conf: |',
        '    Acquire { Check-Date "false"; };',
        'write_files:',
    ] + block('/etc/bob/firstboot.json', '0600', firstboot_json(d))
      + block('/usr/local/sbin/bob-firstboot.sh', '0700', firstboot_script(d.get('country', 'GB')))
      + block('/etc/systemd/system/bob-firstboot.service', '0644', FIRSTBOOT_SERVICE) + [
        'runcmd:',
        '  - [systemctl, enable, --now, ssh]',
        '  - [systemctl, daemon-reload]',
        '  - [systemctl, enable, bob-firstboot.service]',
        '  - [systemctl, start, --no-block, bob-firstboot.service]',
        '',
    ])
    ap = ['        %s:' % _yaml_str(d['wifi_ssid'])]
    ap += (['          password: %s' % _yaml_str(d['wifi_password'])] if d.get('wifi_password') else ['          {}'])
    network = '\n'.join([
        'network:',
        '  version: 2',
        '  wifis:',
        '    renderer: NetworkManager',
        '    wlan0:',
        '      dhcp4: true',
        '      optional: true',
        '      regulatory-domain: %s' % d.get('country', 'GB'),
        '      access-points:',
    ] + ap + [''])
    meta = 'dsmode: local\ninstance-id: bob-%s\nlocal-hostname: %s\n' % (secrets.token_hex(4), d['hostname'])
    return {'user-data': user_data, 'network-config': network, 'meta-data': meta}


def _nm_escape(v):
    """A value for a NetworkManager keyfile (glib key-file syntax): backslashes escaped."""
    return str(v).replace('\\', '\\\\')


def firstrun_script(d):
    """firstrun.sh for older Bookworm images (the way Raspberry Pi Imager sets a card up). Runs once, as root,
    before the normal boot: user, name, SSH, Wi-Fi, and the first-boot install service."""
    def q(s):
        return "'" + str(s).replace("'", "'\\''") + "'"
    pw = d.get('wifi_password')
    sec = ('[wifi-security]\nkey-mgmt=wpa-psk\npsk=%s\n' % _nm_escape(pw)) if pw else ''
    nm = ('[connection]\nid=bob-wifi\nuuid=@UUID@\ntype=wifi\ninterface-name=wlan0\nautoconnect=true\n'
          '[wifi]\nmode=infrastructure\nssid=%s\n%s[ipv4]\nmethod=auto\n[ipv6]\nmethod=auto\n') % (_nm_escape(d['wifi_ssid']), sec)
    return '\n'.join([
        '#!/bin/bash',
        '# written by Kevin Setup: runs once on first boot, then removes itself',
        'set +e',
        'BOOT=/boot/firmware; [ -d $BOOT ] || BOOT=/boot',
        'finish() { rm -f $BOOT/firstrun.sh; sed -i "s| systemd.run.*||g" $BOOT/cmdline.txt; exit 0; }',
        'command -v cloud-init >/dev/null && [ -e $BOOT/user-data ] && finish     # a cloud-init image sets itself up',
        'HOST=%s; USERN=%s; PASS=%s' % (q(d['hostname']), q(d['username']), q(d['password'])),
        'CUR=$(getent passwd 1000 | cut -d: -f1)',
        'if [ -n "$CUR" ] && [ "$CUR" != "$USERN" ]; then usermod -l "$USERN" "$CUR"; usermod -m -d "/home/$USERN" "$USERN"; groupmod -n "$USERN" "$CUR"; fi',
        'id "$USERN" >/dev/null 2>&1 || useradd -m -s /bin/bash "$USERN"',
        'for g in sudo adm users audio video plugdev input render netdev gpio i2c spi dialout; do getent group $g >/dev/null && usermod -aG $g "$USERN"; done',
        'echo "$USERN:$PASS" | chpasswd',
        '[ -x /usr/lib/userconf-pi/userconf ] && /usr/lib/userconf-pi/userconf "$USERN" "$(echo "$PASS" | openssl passwd -6 -stdin)"',
        'echo "$USERN ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/010_bob-user; chmod 440 /etc/sudoers.d/010_bob-user',
        'raspi-config nonint do_hostname "$HOST"',
        'systemctl enable ssh',
        'rfkill unblock wifi 2>/dev/null; for f in /var/lib/systemd/rfkill/*:wlan; do [ -e "$f" ] && echo 0 > "$f"; done',
        'raspi-config nonint do_wifi_country %s' % q(d.get('country', 'GB')),
        "cat > /etc/NetworkManager/system-connections/bob-wifi.nmconnection <<'NMEOF'",
        nm.rstrip('\n'),
        'NMEOF',
        'sed -i "s/@UUID@/$(cat /proc/sys/kernel/random/uuid)/" /etc/NetworkManager/system-connections/bob-wifi.nmconnection',
        'chmod 600 /etc/NetworkManager/system-connections/bob-wifi.nmconnection',
        'mkdir -p /etc/bob; mv $BOOT/bob-firstboot.json /etc/bob/firstboot.json; chmod 600 /etc/bob/firstboot.json',
        "cat > /usr/local/sbin/bob-firstboot.sh <<'FBEOF'",
        firstboot_script(d.get('country', 'GB')).rstrip('\n'),
        'FBEOF',
        'chmod 700 /usr/local/sbin/bob-firstboot.sh',
        "cat > /etc/systemd/system/bob-firstboot.service <<'SVCEOF'",
        FIRSTBOOT_SERVICE.rstrip('\n'),
        'SVCEOF',
        'systemctl enable bob-firstboot.service',
        'finish',
        '',
    ])


def _drive_info(root):
    """(is removable, volume label) for a Windows drive, without touching empty card readers."""
    import ctypes
    k32 = ctypes.windll.kernel32
    removable = k32.GetDriveTypeW(root) == 2
    label = ctypes.create_unicode_buffer(261)
    k32.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
    return removable, label.value


def is_boot_partition(root):
    return os.path.exists(os.path.join(root, 'config.txt')) and os.path.exists(os.path.join(root, 'cmdline.txt'))


def boot_drives(show_all=False):
    """Removable drives that look like a Raspberry Pi OS boot partition, as (root, label)."""
    if os.name != 'nt':
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i) or letter in 'AB':
            continue
        root = '%s:\\' % letter
        try:
            removable, label = _drive_info(root)
        except Exception:
            removable, label = False, ''
        if (removable or show_all) and is_boot_partition(root):
            out.append((root, label))
    return out


def uses_cloud_init(root):
    """Raspberry Pi OS images from October 2025 set themselves up with cloud-init; older ones use firstrun.sh."""
    if any(os.path.exists(os.path.join(root, n)) for n in ('user-data', 'meta-data', 'network-config')):
        return True
    try:
        with open(os.path.join(root, 'issue.txt'), encoding='utf-8', errors='replace') as f:
            m = re.search(r'(\d{4})-(\d{2})-(\d{2})', f.read())
        if m:
            return (int(m.group(1)), int(m.group(2))) >= (2025, 10)
    except OSError:
        pass
    return False


def _write(path, text):
    with open(path, 'w', newline='\n', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    with open(path, encoding='utf-8') as f:            # read it back: a card that lies about writes is caught here
        if f.read() != text:
            raise IOError('%s did not write correctly' % os.path.basename(path))


def prepare_card(root, d):
    """Write everything onto the boot partition at `root`. Returns a list of what was done."""
    if not is_boot_partition(root):
        raise IOError('%s is not a Raspberry Pi boot drive (no config.txt / cmdline.txt)' % root)
    done = []
    if uses_cloud_init(root):
        for name, text in cloud_init_files(d).items():
            path = os.path.join(root, name)
            if os.path.exists(path) and not os.path.exists(path + '.orig'):
                os.replace(path, path + '.orig')
            _write(path, text)
            done.append('wrote ' + name)
    else:
        _write(os.path.join(root, 'firstrun.sh'), firstrun_script(d))
        _write(os.path.join(root, 'bob-firstboot.json'), firstboot_json(d))
        cmd_path = os.path.join(root, 'cmdline.txt')
        with open(cmd_path, encoding='utf-8') as f:
            cmd = f.read().strip()
        cmd = re.sub(r' systemd\.run.*', '', cmd)
        cmd += ' systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target'
        _write(cmd_path, cmd + '\n')
        done += ['wrote firstrun.sh', 'wrote bob-firstboot.json', 'updated cmdline.txt']
    _write(os.path.join(root, 'ssh'), '')
    done.append('enabled SSH')
    return done


def install_over_ssh(host, user, password, d, out, confirm_key=None):
    """Install Kevin on a running Pi. `out(text)` receives progress lines; `confirm_key(fingerprint)` must return
    True to trust a Pi seen for the first time (defaults to trusting it)."""
    import paramiko

    class Ask(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fp = ':'.join('%02x' % b for b in key.get_fingerprint())
            if confirm_key and not confirm_key('%s %s' % (key.get_name(), fp)):
                raise paramiko.SSHException('host key not accepted')

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(Ask())
    out('Connecting to %s...' % host)
    cli.connect(host, username=user, password=password, timeout=15, banner_timeout=15, auth_timeout=15,
                look_for_keys=False, allow_agent=False)
    tag = secrets.token_hex(4)
    cfg, script = '/tmp/bob-firstboot-%s.json' % tag, '/tmp/bob-install-%s.sh' % tag
    try:
        sftp = cli.open_sftp()
        sftp.open(cfg, 'w').close()
        sftp.chmod(cfg, 0o600)                 # private before anything is written into it
        with sftp.file(cfg, 'w') as f:
            f.write(firstboot_json(d))
        sftp.close()
        _i, o, _e = cli.exec_command('curl -fsSL --retry 3 -o %s %s && echo OK' % (script, INSTALL_URL), timeout=120)
        if 'OK' not in o.read().decode():
            raise RuntimeError('the Pi could not download the installer (is it online?)')
        stdin, stdout, _stderr = cli.exec_command('sudo -S -p "" bash %s --config %s 2>&1' % (script, cfg))
        stdout.channel.settimeout(1800)
        stdin.write(password + '\n')
        stdin.flush()
        stdin.channel.shutdown_write()           # nothing else will ever be typed: nothing can wait for it
        for line in iter(stdout.readline, ''):
            out(line.rstrip())
        return stdout.channel.recv_exit_status()
    finally:
        try:
            cli.exec_command('rm -f %s %s' % (script, cfg))
        except Exception:
            pass
        cli.close()


# ---- helpers for the window (no window needed: tested on any OS) ---------------------------------------

SAVED = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'Kevin Setup', 'answers.json')
REMEMBER = ('wifi_ssid', 'country', 'hostname', 'username', 'name', 'wake_phrase', 'voice', 'town')   # never secrets
VOICE_NOTES = {'Charon': 'calm, deep', 'Puck': 'bright, upbeat', 'Kore': 'firm, clear', 'Fenrir': 'warm, excitable',
               'Aoede': 'breezy', 'Leda': 'youthful', 'Orus': 'steady', 'Zephyr': 'light, airy'}


def _run_quiet(cmd, timeout=8):
    import subprocess
    flags = 0x08000000 if os.name == 'nt' else 0              # CREATE_NO_WINDOW: no console flashes up
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags,
                           encoding='utf-8', errors='replace')
        return r.stdout or ''
    except Exception:
        return ''


def parse_netsh_ssid(text):
    """The connected Wi-Fi's name from `netsh wlan show interfaces`."""
    for line in text.splitlines():
        m = re.match(r'^\s*SSID\s*:\s*(.+?)\s*$', line)          # "SSID", not "BSSID"
        if m:
            return m.group(1)
    return ''


def parse_netsh_key(text):
    """The saved password from `netsh wlan show profile name=... key=clear` ("Key Content")."""
    m = re.search(r'Key Content\s*:\s*(.+?)\s*$', text, re.M)
    return m.group(1) if m else ''


def this_pc_wifi():
    return parse_netsh_ssid(_run_quiet(['netsh', 'wlan', 'show', 'interfaces'])) if os.name == 'nt' else ''


def saved_wifi_password(ssid):
    """Windows keeps the password of every network it has joined; reading it back is the user's own choice (a button)."""
    if os.name != 'nt' or not ssid:
        return ''
    return parse_netsh_key(_run_quiet(['netsh', 'wlan', 'show', 'profile', 'name=' + ssid, 'key=clear']))


def this_pc_country():
    """GB, US, ... from the Windows region (or the locale elsewhere); GB if unknown."""
    try:
        if os.name == 'nt':
            import ctypes
            buf = ctypes.create_unicode_buffer(16)
            if ctypes.windll.kernel32.GetUserDefaultGeoName(buf, 16):
                code = buf.value.upper()
                if re.match(r'^[A-Z]{2}$', code):
                    return code
        import locale
        loc = (locale.getlocale()[0] or '')
        m = re.search(r'[_-]([A-Z]{2})', loc)
        if m:
            return m.group(1)
    except Exception:
        pass
    return 'GB'


def strong_password(n=14):
    """Easy to type, hard to guess: letters and digits, no look-alikes (0 O 1 l I)."""
    alphabet = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(n))


def test_gemini_key(key, timeout=10):
    """(ok, message): asks Google whether the key works (only Google sees it)."""
    import urllib.error
    import urllib.request
    key = (key or '').strip()
    if not key:
        return False, 'Paste your key first.'
    try:
        req = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models?pageSize=1',
                                     headers={'x-goog-api-key': key})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            json.load(r)
        return True, 'The key works.'
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return False, 'Google says this key is not valid. Copy it again from AI Studio.'
        return False, 'Google answered with an error (%s). Try again in a minute.' % e.code
    except Exception:
        return False, 'Could not reach Google from this PC. Check the internet connection.'


def check_town(town, timeout=10):
    """(ok, 'Leeds, United Kingdom') for the weather town, using the free Open-Meteo place search."""
    import urllib.parse
    import urllib.request
    if not (town or '').strip():
        return False, 'Optional: type your town for the weather.'
    try:
        q = urllib.parse.urlencode({'name': town.strip(), 'count': 1, 'language': 'en', 'format': 'json'})
        with urllib.request.urlopen('https://geocoding-api.open-meteo.com/v1/search?' + q, timeout=timeout) as r:
            hit = (json.load(r).get('results') or [None])[0]
        if not hit:
            return False, 'No place called "%s" was found.' % town.strip()
        return True, '%s, %s' % (hit['name'], hit.get('country', ''))
    except Exception:
        return False, 'Could not check it (no internet?). It will be looked up on the Pi.'


def kevin_answers(host, timeout=4):
    """Is Kevin's settings page answering yet (http://<host>:8080)?"""
    import urllib.request
    try:
        with urllib.request.urlopen('http://%s:8080/login' % host, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def load_answers():
    try:
        with open(SAVED, encoding='utf-8') as f:
            d = json.load(f)
        return {k: str(v) for k, v in d.items() if k in REMEMBER and v}      # an empty answer keeps the default
    except (OSError, ValueError):
        return {}


def save_answers(d):
    try:
        os.makedirs(os.path.dirname(SAVED), exist_ok=True)
        with open(SAVED, 'w', encoding='utf-8') as f:
            json.dump({k: d.get(k, '') for k in REMEMBER}, f, indent=2)
    except OSError:
        pass


# ---- the window: a step-by-step wizard -------------------------------------------------------------------

# Kevin's colours: near-black, with the blue-to-violet of his face
BG, PANEL, SIDE, INK, DIM, ACC, ACC2, GOOD, BAD, LINE, FIELD = ('#0b0b10', '#15141f', '#07070b', '#f5f5f7', '#9a99b3',
                                                               '#7d79ff', '#6a66f2', '#30d158', '#ff6b61', '#2a2940', '#1d1c2b')
GRAD = ('#2f8cff', '#5e5ce6', '#a65cf0')


def _mix(a, b, t):
    a, b = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient(t):
    """0..1 along Kevin's blue -> indigo -> violet."""
    return _mix(GRAD[0], GRAD[1], t * 2) if t < 0.5 else _mix(GRAD[1], GRAD[2], (t - 0.5) * 2)


def gui():
    import queue
    import tkinter as tk
    from tkinter import messagebox, ttk

    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)        # crisp text on high-DPI screens
        except Exception:
            pass
    root = tk.Tk()
    root.title('Kevin Setup')
    root.geometry('980x700')
    root.minsize(900, 640)
    root.configure(bg=BG)
    FONT = 'Segoe UI' if os.name == 'nt' else 'Helvetica'
    st = ttk.Style()
    try:
        st.theme_use('clam')
    except tk.TclError:
        pass
    st.configure('.', background=BG, foreground=INK, font=(FONT, 10))
    st.configure('Card.TFrame', background=PANEL)
    st.configure('Side.TFrame', background=SIDE)
    st.configure('TLabel', background=PANEL)
    st.configure('Hint.TLabel', background=PANEL, foreground=DIM, font=(FONT, 9))
    st.configure('H1.TLabel', background=PANEL, font=(FONT, 20, 'bold'))
    st.configure('Lead.TLabel', background=PANEL, foreground=DIM, font=(FONT, 11))
    st.configure('Good.TLabel', background=PANEL, foreground=GOOD, font=(FONT, 9, 'bold'))
    st.configure('Bad.TLabel', background=PANEL, foreground=BAD, font=(FONT, 9, 'bold'))
    st.configure('TEntry', fieldbackground=FIELD, foreground=INK, insertcolor=INK, bordercolor=LINE, lightcolor=LINE,
                 darkcolor=LINE, padding=8)
    st.map('TEntry', bordercolor=[('focus', ACC)], lightcolor=[('focus', ACC)])
    st.configure('TCombobox', fieldbackground=FIELD, foreground=INK, background=FIELD, arrowcolor=INK, bordercolor=LINE,
                 lightcolor=LINE, darkcolor=LINE, padding=7)
    st.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', INK)], selectbackground=[('readonly', FIELD)])
    root.option_add('*TCombobox*Listbox.background', FIELD)
    root.option_add('*TCombobox*Listbox.foreground', INK)
    root.option_add('*TCombobox*Listbox.selectBackground', ACC)
    for w in ('TCheckbutton', 'TRadiobutton'):
        st.configure(w, background=PANEL, foreground=INK, indicatorbackground=FIELD, indicatorforeground=ACC, focuscolor=PANEL)
        st.map(w, background=[('active', PANEL)], indicatorbackground=[('selected', ACC)], indicatorforeground=[('selected', 'white')])
    st.configure('Accent.TButton', background=ACC, foreground='white', bordercolor=ACC, lightcolor=ACC, darkcolor=ACC,
                 padding=(20, 10), font=(FONT, 10, 'bold'))
    st.map('Accent.TButton', background=[('disabled', '#34335a'), ('active', ACC2)], foreground=[('disabled', '#77769a')])
    st.configure('TButton', background='#23223a', foreground=INK, bordercolor=LINE, lightcolor='#23223a', darkcolor='#23223a',
                 padding=(14, 8))
    st.map('TButton', background=[('active', '#2e2d4a'), ('disabled', '#1a1928')], foreground=[('disabled', '#5d5c7a')])
    st.configure('Horizontal.TProgressbar', troughcolor='#1d1c2b', background=ACC, bordercolor=LINE, lightcolor=ACC,
                 darkcolor=ACC2, thickness=12)
    st.configure('TSeparator', background=LINE)

    answers = load_answers()
    v = {}

    def var(key, default=''):
        if key not in v:
            v[key] = tk.StringVar(value=answers.get(key, default))
        return v[key]

    mode = tk.StringVar(value='card')          # card (new Pi) | imager (settings onto a flashed card) | ssh
    helper_on = tk.BooleanVar(value=False)     # "Help run KindleHub": off by default

    # -- layout: sidebar with the steps, a page, and Back / Next --
    side = ttk.Frame(root, style='Side.TFrame', width=230)
    side.pack(side='left', fill='y')
    side.pack_propagate(False)
    # Kevin's face: a gradient tile with two eyes that blink, and bounce while he is working
    face = tk.Canvas(side, width=86, height=86, bg=SIDE, highlightthickness=0)
    face.pack(pady=(30, 6))
    for y in range(86):
        face.create_line(4, y, 82, y, fill=gradient(y / 85.0))
    for (x0, y0, x1, y1) in ((0, 0, 14, 14), (72, 0, 86, 14), (0, 72, 14, 86), (72, 72, 86, 86)):   # round the corners
        face.create_rectangle(x0, y0, x1, y1, fill=SIDE, outline=SIDE)
    for cx, cy in ((14, 14), (72, 14), (14, 72), (72, 72)):
        face.create_oval(cx - 14, cy - 14, cx + 14, cy + 14, fill=gradient(cy / 85.0), outline='')
    face.create_rectangle(4, 14, 82, 72, fill='', outline='')
    eyes = [face.create_rectangle(x, 30, x + 10, 56, fill='white', outline='') for x in (29, 47)]
    look = {'t': 0, 'blink': 0}

    def animate():
        look['t'] += 1
        t = look['t']
        if look['blink'] > 0:
            look['blink'] -= 1
        elif t % 45 == 0 or (t % 13 == 0 and __import__('random').random() < 0.08):
            look['blink'] = 2
        h = 3 if look['blink'] else 26
        bob = int(3 * __import__('math').sin(t / 2.0)) if work.get('busy') else 0
        for i, e in enumerate(eyes):
            x = 29 + 18 * i
            face.coords(e, x, 43 - h / 2 + bob, x + 10, 43 + h / 2 + bob)
        root.after(90, animate)
    tk.Label(side, text='Kevin Setup', bg=SIDE, fg='white', font=(FONT, 15, 'bold')).pack(pady=(4, 22))
    body = tk.Frame(root, bg=BG)
    body.pack(side='left', fill='both', expand=True)
    stripe = tk.Canvas(body, height=4, bg=BG, highlightthickness=0)
    stripe.pack(fill='x', padx=26, pady=(26, 0))
    stripe.bind('<Configure>', lambda e: [stripe.create_line(x, 0, x, 4, fill=gradient(x / max(1, e.width - 1)))
                                          for x in range(e.width)])
    card = ttk.Frame(body, style='Card.TFrame', padding=(34, 28))
    card.pack(fill='both', expand=True, padx=26)
    nav = tk.Frame(body, bg=BG)
    nav.pack(fill='x', padx=26, pady=16)
    back_btn = ttk.Button(nav, text='← Back')
    next_btn = ttk.Button(nav, text='Next →', style='Accent.TButton')
    back_btn.pack(side='left')
    next_btn.pack(side='right')

    STEPS = ['Welcome', 'Wi-Fi', 'Kevin', 'Logins', 'Extras', 'Set up', 'Done']
    step_labels = []
    for i, name in enumerate(STEPS):
        lab = tk.Label(side, text='   %d   %s' % (i + 1, name), bg=SIDE, fg='#8f8eb0', font=(FONT, 11), anchor='w', pady=8)
        lab.pack(fill='x', padx=10)
        step_labels.append(lab)
    tk.Label(side, text='Nothing leaves this PC except to\nGoogle (to check your key), the\nRaspberry Pi website (the OS image)\nand your own Pi.',
             bg=SIDE, fg='#56557a', font=(FONT, 8), justify='left', anchor='w').pack(side='bottom', fill='x', padx=22, pady=20)

    pages = {}

    def page(name):
        f = ttk.Frame(card, style='Card.TFrame')
        pages[name] = f
        return f

    def h1(parent, text, lead=None):
        ttk.Label(parent, text=text, style='H1.TLabel').pack(anchor='w')
        if lead:
            ttk.Label(parent, text=lead, style='Lead.TLabel', wraplength=640, justify='left').pack(anchor='w', pady=(4, 16))

    def field(parent, label, key, default='', show=None, values=None, hint=None, width=None):
        ttk.Label(parent, text=label, font=(FONT, 10, 'bold')).pack(anchor='w', pady=(10, 3))
        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x')
        if values:
            w = ttk.Combobox(row, textvariable=var(key, default), values=values, state='readonly', width=width or 40)
        else:
            w = ttk.Entry(row, textvariable=var(key, default), show=show or '', width=width or 44)
        w.pack(side='left')
        if show:
            shown = tk.BooleanVar(value=False)
            ttk.Checkbutton(row, text='Show', variable=shown,
                            command=lambda: w.configure(show='' if shown.get() else show)).pack(side='left', padx=8)
        if hint:
            ttk.Label(parent, text=hint, style='Hint.TLabel', wraplength=640, justify='left').pack(anchor='w', pady=(2, 0))
        return row, w

    def note(parent):
        lab = ttk.Label(parent, text='', style='Hint.TLabel', wraplength=640)
        lab.pack(anchor='w', pady=(4, 0))

        def say(ok, text):
            lab.configure(text=('✓ ' if ok else '✗ ') + text if ok is not None else text,
                          style='Good.TLabel' if ok else 'Bad.TLabel' if ok is False else 'Hint.TLabel')
        return say

    def in_background(fn, then):
        """Run fn() off the window's thread, then then(result) on it."""
        threading.Thread(target=lambda: (lambda r: root.after(0, lambda: then(r)))(fn()), daemon=True).start()

    # 1. Welcome
    p = page('Welcome')
    h1(p, 'Set up Kevin', 'A voice assistant for your Raspberry Pi that you build by talking to it. This takes about five '
                          'minutes here, then 10-20 minutes on the Pi by itself.')
    ttk.Label(p, text='You need', font=(FONT, 11, 'bold')).pack(anchor='w', pady=(4, 2))
    for item in ('A Raspberry Pi 4 or 5 (3 B+ works, slowly) and its power supply',
                 'A microSD card, 8 GB or more, and a way to plug it into this PC',
                 'A USB speakerphone (or a USB microphone and speaker)',
                 'A free Gemini API key from Google (the next steps show you where)'):
        ttk.Label(p, text='•  ' + item).pack(anchor='w', pady=1)
    ttk.Label(p, text='How are you setting it up?', font=(FONT, 11, 'bold')).pack(anchor='w', pady=(18, 4))
    for val, txt, sub in (('card', 'A new Pi: write the microSD card for me', 'Downloads Raspberry Pi OS, writes and checks the card, adds your settings.'),
                          ('imager', 'I already wrote the card with Raspberry Pi Imager', 'Only adds the settings to it (no customisation in Imager).'),
                          ('ssh', 'My Pi is already running', 'Installs Kevin over the network.')):
        ttk.Radiobutton(p, text=txt, value=val, variable=mode).pack(anchor='w', pady=(6, 0))
        ttk.Label(p, text='      ' + sub, style='Hint.TLabel').pack(anchor='w')

    # 2. Wi-Fi
    p = page('Wi-Fi')
    h1(p, 'Wi-Fi', 'The Pi joins this network when it first starts. (Not needed if your Pi is already running.)')
    var('wifi_ssid', this_pc_wifi())
    _r, _w = field(p, 'Wi-Fi name', 'wifi_ssid', hint='Exactly as your phone shows it: capitals matter. Filled in from this PC.')
    _r, _w = field(p, 'Wi-Fi password', 'wifi_password', show='•')
    wifi_say = note(p)

    def fill_wifi_password():
        pw = saved_wifi_password(v['wifi_ssid'].get().strip())
        if pw:
            v['wifi_password'].set(pw)
            wifi_say(True, 'Filled in from this PC.')
        else:
            wifi_say(False, 'This PC has no saved password for that network: type it in.')
    ttk.Button(_r, text='Use this PC\'s saved password', command=fill_wifi_password).pack(side='left', padx=4)
    field(p, 'Country', 'country', this_pc_country(), values=COUNTRIES, width=8,
          hint='Wi-Fi rules differ by country. Taken from Windows.')

    # 3. Kevin
    p = page('Kevin')
    h1(p, 'Kevin', 'His name, his voice, and the key he uses to talk.')
    krow, _w = field(p, 'Gemini API key', 'gemini_api_key', show='•',
                     hint='Free: sign in with a Google account, press "Create API key", copy it here.')
    key_say = note(p)
    ttk.Button(krow, text='Get a free key', command=lambda: webbrowser.open(KEY_URL)).pack(side='left', padx=4)

    def try_key(btn):
        btn.state(['disabled'])
        key_say(None, 'Checking with Google…')
        in_background(lambda: test_gemini_key(v['gemini_api_key'].get()),
                      lambda r: (key_say(*r), btn.state(['!disabled'])))
    tb = ttk.Button(krow, text='Test key')
    tb.configure(command=lambda: try_key(tb))
    tb.pack(side='left')
    two = ttk.Frame(p, style='Card.TFrame')
    two.pack(fill='x')
    left, right = ttk.Frame(two, style='Card.TFrame'), ttk.Frame(two, style='Card.TFrame')
    left.pack(side='left', fill='x', expand=True)
    right.pack(side='left', fill='x', expand=True, padx=(20, 0))
    field(left, 'Name', 'name', 'Kevin', width=22)
    field(right, 'Wake phrase', 'wake_phrase', 'hey kevin', width=22, hint='Two common words work best.')
    field(left, 'Voice', 'voice', 'Charon', values=['%s' % n for n in VOICES], width=20)
    vnote = ttk.Label(left, text='', style='Hint.TLabel')
    vnote.pack(anchor='w')
    v['voice'].trace_add('write', lambda *a: vnote.configure(text=VOICE_NOTES.get(v['voice'].get(), '')))
    vnote.configure(text=VOICE_NOTES.get(v['voice'].get(), ''))
    trow, _w = field(right, 'Town (for the weather)', 'town', width=22)
    town_say = note(right)
    tbtn = ttk.Button(trow, text='Check')
    tbtn.configure(command=lambda: (town_say(None, 'Looking it up…'),
                                    in_background(lambda: check_town(v['town'].get()), lambda r: town_say(*r))))
    tbtn.pack(side='left', padx=4)

    # 4. Logins
    p = page('Logins')
    h1(p, 'Logins', 'Two passwords: one for the Pi itself (for SSH, if you ever need it) and one for Kevin\'s settings '
                    'page. Write them down somewhere safe.')

    def gen(key):
        v[key].set(strong_password())
    r1, _w = field(p, 'Pi name on your network', 'hostname', 'kevin', hint='Then the settings page is http://<name>.local:8080')
    r2, _w = field(p, 'Pi user name', 'username', 'pi')
    r3, _w = field(p, 'Pi password', 'password', show='•', hint='A new Pi: choose one (8+ characters). A running Pi: the one it has.')
    ttk.Button(r3, text='Make one', command=lambda: gen('password')).pack(side='left', padx=4)
    r4, _w = field(p, 'Settings page password', 'web_password', show='•', hint='6+ characters. You sign in to Kevin\'s page with it.')
    ttk.Button(r4, text='Make one', command=lambda: gen('web_password')).pack(side='left', padx=4)
    hrow, _w = field(p, 'Pi address (only for a Pi that is already running)', 'ssh_host', 'kevin.local',
                     hint='Its name with .local, or its IP address from your router.')

    # 5. Extras
    p = page('Extras')
    h1(p, 'Extras', 'All optional, and all can be changed later on Kevin\'s settings page.')
    ttk.Label(p, text='Your Claude or ChatGPT account', font=(FONT, 11, 'bold')).pack(anchor='w', pady=(6, 2))
    ttk.Label(p, text='Kevin can hand hard questions (maths, code, planning) to your own Claude Pro/Max or ChatGPT Plus/Pro '
                      'subscription. You connect it on the settings page after setup: it takes two minutes.',
              wraplength=640, justify='left').pack(anchor='w')
    ttk.Button(p, text='How to connect an account', command=lambda: webbrowser.open(
        'https://github.com/%s/blob/main/docs/AI-ACCOUNTS.md' % REPO)).pack(anchor='w', pady=6)
    ttk.Label(p, text='A bedside screen', font=(FONT, 11, 'bold')).pack(anchor='w', pady=(14, 2))
    ttk.Label(p, text='A £10 Arduino Nano with a little LCD and a joystick shows the time, weather and timers, and its button '
                      'talks to Kevin.', wraplength=640, justify='left').pack(anchor='w')
    ttk.Button(p, text='Parts and wiring', command=lambda: webbrowser.open(
        'https://github.com/%s/tree/main/examples/bedside-screen' % REPO)).pack(anchor='w', pady=6)
    ttk.Label(p, text='Help run KindleHub', font=(FONT, 11, 'bold')).pack(anchor='w', pady=(14, 2))
    ttk.Checkbutton(p, text='Lend the Pi\'s spare time to KindleHub (free games for e-readers)', variable=helper_on).pack(anchor='w')
    ttk.Label(p, text='It plays chess moves for KindleHub\'s computer opponent and nothing else, using at most half of one '
                      'core at the lowest priority. Off unless you tick it.', style='Hint.TLabel', wraplength=640).pack(anchor='w')

    # 6. Set up
    p = page('Set up')
    h1(p, 'Set up', '')
    lead = ttk.Label(p, text='', style='Lead.TLabel', wraplength=640, justify='left')
    lead.pack(anchor='w', pady=(0, 10))
    pick = ttk.Frame(p, style='Card.TFrame')
    pick.pack(fill='x')
    choice = tk.StringVar()
    chooser = ttk.Combobox(pick, textvariable=choice, state='readonly', width=52)
    chooser.pack(side='left')
    refresh_btn = ttk.Button(pick, text='Refresh')
    refresh_btn.pack(side='left', padx=6)
    go_btn = ttk.Button(p, text='Start', style='Accent.TButton')
    go_btn.pack(anchor='w', pady=14)
    stage_box = ttk.Frame(p, style='Card.TFrame')
    stage_box.pack(fill='x')
    bar = ttk.Progressbar(p, maximum=1000, style='Horizontal.TProgressbar')
    bar.pack(fill='x', pady=(10, 2))
    status = tk.StringVar()
    ttk.Label(p, textvariable=status, style='Hint.TLabel').pack(anchor='w')
    cancel_btn = ttk.Button(p, text='Cancel', state='disabled')
    cancel_btn.pack(anchor='e')
    show_log = tk.BooleanVar(value=False)
    log = tk.Text(p, height=8, wrap='word', font=('Consolas', 9), relief='flat', bg='#0f0e18', fg='#c9c8e0',
                  insertbackground=INK, highlightthickness=0)
    ttk.Checkbutton(p, text='Show details', variable=show_log,
                    command=lambda: log.pack(fill='both', expand=True, pady=(6, 0)) if show_log.get() else log.pack_forget()).pack(anchor='w')

    # 7. Done
    p = page('Done')
    h1(p, 'Almost there', '')
    done_lead = ttk.Label(p, text='', style='Lead.TLabel', wraplength=640, justify='left')
    done_lead.pack(anchor='w', pady=(0, 10))
    wait_say = ttk.Label(p, text='', font=(FONT, 12, 'bold'))
    wait_say.pack(anchor='w', pady=8)
    wait_bar = ttk.Progressbar(p, mode='indeterminate', style='Horizontal.TProgressbar')
    wait_bar.pack(fill='x')
    links = ttk.Frame(p, style='Card.TFrame')
    links.pack(anchor='w', pady=14)
    open_btn = ttk.Button(links, text='Open Kevin\'s settings', style='Accent.TButton', state='disabled')
    open_btn.pack(side='left')
    app_btn = ttk.Button(links, text='Phone remote', state='disabled')
    app_btn.pack(side='left', padx=8)
    tips = ttk.Label(p, text='', wraplength=640, justify='left')
    tips.pack(anchor='w', pady=(6, 0))

    # -- moving between steps --
    cur = {'i': 0}
    lines = queue.Queue()
    stop = threading.Event()
    work = {'busy': False, 'progress': None, 'stage': None}
    disks, drives = {}, {}

    def out(text):
        lines.put(text)

    def wanted_steps():
        return [s for s in STEPS if not (s == 'Wi-Fi' and mode.get() == 'ssh')]

    def show(name):
        for f in pages.values():
            f.pack_forget()
        pages[name].pack(fill='both', expand=True)
        steps = wanted_steps()
        for i, lab in enumerate(step_labels):
            s = STEPS[i]
            on, skipped, past = s == name, s not in steps, steps.index(s) < steps.index(name) if s in steps else False
            lab.configure(fg='white' if on else '#3d3c58' if skipped else '#30d158' if past else '#8f8eb0',
                          bg='#1c1b30' if on else SIDE,
                          font=(FONT, 11, 'bold' if on else 'normal'),
                          text='   %s   %s' % ('✓' if past else str(i + 1), s))
        back_btn.state(['disabled'] if name in ('Welcome', 'Done') or work['busy'] else ['!disabled'])
        next_btn.configure(text='Close' if name == 'Done' else 'Next →')
        next_btn.state(['disabled'] if name == 'Set up' else ['!disabled'])
        if name == 'Set up':
            prepare_setup_page()

    def data():
        keep = ('password', 'wifi_password', 'web_password', 'wifi_ssid')     # never trim these
        d = {k: (x.get() if k in keep else x.get().strip()) for k, x in v.items()}
        d['kindlehub_helper'] = bool(helper_on.get())
        return d

    def problems(name):
        """What's wrong on this step, in plain words (checked before moving on)."""
        d, errs = data(), []
        m = mode.get()
        if name == 'Wi-Fi':
            if not d.get('wifi_ssid'):
                errs.append('Type the Wi-Fi name.')
            elif len(d['wifi_ssid'].encode('utf-8')) > 32:
                errs.append('That Wi-Fi name is too long (32 bytes at most).')
            pw = d.get('wifi_password', '')
            if pw and not (8 <= len(pw) <= 63 or re.match(r'^[0-9a-fA-F]{64}$', pw)):
                errs.append('A Wi-Fi password has 8 to 63 characters (or leave it empty for an open network).')
        if name == 'Kevin':
            if not d.get('gemini_api_key'):
                errs.append('Paste your Gemini API key ("Get a free key" opens the page).')
            if not d.get('wake_phrase'):
                errs.append('Choose a wake phrase, like "hey kevin".')
        if name == 'Logins':
            full = dict(d, wifi_ssid=d.get('wifi_ssid') or 'x')
            for e in (validate_ssh(full) if m == 'ssh' else validate_card(full)):
                if not e.startswith(('Gemini', 'Wi-Fi')):
                    errs.append(e)
            if m == 'ssh' and not d.get('ssh_host'):
                errs.append('Type the Pi\'s address.')
        return errs

    def go_next():
        steps = wanted_steps()
        name = steps[cur['i']]
        if name == 'Done':
            root.destroy()
            return
        errs = problems(name)
        if errs:
            messagebox.showerror('Kevin Setup', '\n'.join(errs))
            return
        if name == 'Logins':
            save_answers(data())
        cur['i'] = min(cur['i'] + 1, len(steps) - 1)
        show(steps[cur['i']])

    def go_back():
        if work['busy']:
            return
        steps = wanted_steps()
        name = steps[cur['i']]
        cur['i'] = max(0, steps.index(name) - 1)
        show(steps[cur['i']])
    next_btn.configure(command=go_next)
    back_btn.configure(command=go_back)

    # -- the Set up step --
    STAGES = {'card': ['Download Raspberry Pi OS', 'Write the card', 'Check the card', 'Add your settings', 'Eject'],
              'imager': ['Add your settings'],
              'ssh': ['Connect to the Pi', 'Install Kevin (10-20 minutes)']}
    stage_rows = []

    def draw_stages():
        for w in stage_rows:
            w.destroy()
        stage_rows.clear()
        names = STAGES[mode.get()]
        for n in names:
            done_ = work['stage'] is not None and names.index(n) < work['stage']
            now_ = work['stage'] is not None and names.index(n) == work['stage']
            lab = ttk.Label(stage_box, text='%s  %s' % ('✓' if done_ else '›' if now_ else '·', n),
                            font=(FONT, 10, 'bold' if now_ else 'normal'), foreground=GOOD if done_ else INK if now_ else DIM)
            lab.pack(anchor='w', pady=1)
            stage_rows.append(lab)

    def stage(i):
        work['stage'] = i
        root.after(0, draw_stages)

    def refresh_choices():
        m = mode.get()
        if m == 'card':
            disks.clear()
            try:
                for dsk in flasher.choose_disks(flasher.list_disks()):
                    disks[flasher.describe(dsk)] = dsk
            except Exception as e:
                out('Could not list the cards: %s' % e)
            vals = list(disks)
        else:
            drives.clear()
            for r, label in boot_drives(False):
                drives['%s  %s' % (r, label or 'bootfs')] = r
            vals = list(drives)
        chooser['values'] = vals
        choice.set(vals[0] if vals else '')
        if not vals:
            status.set('No card found. Put the microSD card in (or plug in the card reader), then press Refresh.')
        else:
            status.set('')

    def prepare_setup_page():
        m = mode.get()
        work['stage'] = None
        draw_stages()
        if m == 'ssh':
            lead.configure(text='Kevin will be installed on %s over your network. Keep this window open until it finishes.' % v['ssh_host'].get())
            pick.pack_forget()
            go_btn.configure(text='Install Kevin')
        else:
            lead.configure(text=('Choose the microSD card. Everything on it will be erased, then Raspberry Pi OS (about 550 MB) is '
                                 'downloaded, written and checked, and your settings are added.' if m == 'card' else
                                 'Choose the card\'s "bootfs" drive. Your settings are added; nothing else changes.'))
            pick.pack(fill='x', before=go_btn)
            go_btn.configure(text='Write the card' if m == 'card' else 'Add the settings')
            refresh_choices()
    refresh_btn.configure(command=refresh_choices)

    def busy(on):
        work['busy'] = on
        go_btn.state(['disabled'] if on else ['!disabled'])
        refresh_btn.state(['disabled'] if on else ['!disabled'])
        cancel_btn.state(['!disabled'] if on and mode.get() == 'card' else ['disabled'])
        back_btn.state(['disabled'] if on else ['!disabled'])
        if not on:
            work['progress'] = None

    def confirm_erase(desc):
        top = tk.Toplevel(root)
        top.title('Erase this card?')
        top.transient(root)
        top.grab_set()
        top.configure(bg=PANEL)
        ttk.Label(top, text='Everything on this card will be erased:\n\n%s\n\nType ERASE to continue.' % desc,
                  padding=16, wraplength=440).pack()
        typed = tk.StringVar()
        ent = ttk.Entry(top, textvariable=typed)
        ent.pack(padx=16, fill='x')
        ent.focus_set()
        res = {}

        def ok(_e=None):
            if typed.get().strip().upper() == 'ERASE':
                res['ok'] = True
                top.destroy()
            else:
                messagebox.showerror('Kevin Setup', 'Type ERASE to erase the card, or press Cancel.', parent=top)
        btns = ttk.Frame(top, padding=16, style='Card.TFrame')
        btns.pack()
        ttk.Button(btns, text='Erase and write', style='Accent.TButton', command=ok).pack(side='left', padx=4)
        ttk.Button(btns, text='Cancel', command=top.destroy).pack(side='left', padx=4)
        ent.bind('<Return>', ok)
        root.wait_window(top)
        return res.get('ok', False)

    def finished(d, where):
        """Move to Done and wait for Kevin to answer on the network."""
        host = where
        names = STAGES[mode.get()]
        work['stage'] = len(names)
        steps = wanted_steps()
        cur['i'] = steps.index('Done')
        show('Done')
        first = mode.get() != 'ssh'
        done_lead.configure(text=(
            'Put the card in the Pi, plug in the USB speakerphone, and switch it on. The first start takes 10-20 minutes: '
            'it joins your Wi-Fi, updates and installs Kevin by itself. A rising three-note chime means he is ready.'
            if first else 'Kevin is installed.'))
        wait_say.configure(text='Waiting for Kevin to come online…', foreground=DIM)
        wait_bar.start(12)
        tips.configure(text='Then say "%s". Try: "what\'s the weather", "set a timer for 5 minutes", "play Radio Paradise".'
                            % d.get('wake_phrase', 'hey kevin'))
        url = 'http://%s:8080' % host
        open_btn.configure(command=lambda: webbrowser.open(url))
        app_btn.configure(command=lambda: webbrowser.open(url + '/app'))
        started = __import__('time').time()

        def poll():
            if not root.winfo_exists():
                return
            in_background(lambda: kevin_answers(host), lambda ok: ready() if ok else again())

        def again():
            mins = (__import__('time').time() - started) / 60
            if mins > 40:
                wait_bar.stop()
                wait_say.configure(text='Kevin has not appeared yet. Is the Pi on, with a green light flickering? '
                                        'Try %s in a browser, or the Pi\'s address from your router.' % url, foreground=BAD)
                return
            wait_say.configure(text='Waiting for Kevin to come online… (%d min)' % mins)
            root.after(15000, poll)

        def ready():
            wait_bar.stop()
            wait_bar.pack_forget()
            wait_say.configure(text='✓ Kevin is online at %s' % url, foreground=GOOD)
            open_btn.state(['!disabled'])
            app_btn.state(['!disabled'])
        root.after(20000 if first else 2000, poll)

    def start():
        d = data()
        m = mode.get()
        if m == 'card':
            disk = disks.get(choice.get())
            if not disk:
                messagebox.showerror('Kevin Setup', 'Choose the microSD card (press Refresh after putting it in).')
                return
            if not flasher.is_admin():
                messagebox.showerror('Kevin Setup', 'Writing a card needs administrator rights: close Kevin Setup, right-click it '
                                                  'and choose "Run as administrator". Your answers are remembered.')
                return
            if not confirm_erase(flasher.describe(disk)):
                return
            stop.clear()
            busy(True)

            def job():
                try:
                    stage(0)
                    out('Looking up the newest Raspberry Pi OS Lite (64-bit)...')
                    img = flasher.latest_os()
                    out('Using %s (released %s).' % (img['url'].rsplit('/', 1)[-1], img.get('release_date') or '?'))
                    if int(disk['Size']) < int(img['extract_size']):
                        raise IOError('the card is too small for the image')
                    flasher.clear_disk(disk)
                    target = flasher.DiskTarget(disk['Number'])

                    def progress(kind, done, total):
                        stage(1 if kind == 'write' else 2)
                        work['progress'] = (kind, done, total)
                    try:
                        flasher.write_image(flasher.http_opener(img['url']), target, int(img['extract_size']),
                                            img['extract_sha256'], progress, stop.is_set)
                    finally:
                        target.close()
                    work['progress'] = None
                    stage(3)
                    boot = flasher.boot_drive_of(disk['Number'])
                    for line in prepare_card(boot, d):
                        out(line)
                    stage(4)
                    ejected = flasher.eject(boot)
                    out('Ejected.' if ejected else 'Use "Eject" on the bootfs drive in File Explorer before taking the card out.')
                    root.after(0, lambda: finished(d, d['hostname'] + '.local'))
                except flasher.Cancelled:
                    out('Stopped. The card is blank now: write it again before using it.')
                    root.after(0, lambda: status.set('Stopped. Write the card again before using it.'))
                except Exception as e:
                    out('Could not write the card: %s' % e)
                    root.after(0, lambda e=e: messagebox.showerror('Kevin Setup', 'Could not write the card:\n\n%s' % e))
                finally:
                    root.after(0, lambda: busy(False))
            threading.Thread(target=job, daemon=True).start()
        elif m == 'imager':
            r = drives.get(choice.get())
            if not r or not is_boot_partition(r):
                messagebox.showerror('Kevin Setup', 'Choose the card\'s bootfs drive (press Refresh if you swapped cards).')
                return
            try:
                stage(0)
                for line in prepare_card(r, d):
                    out(line)
                out('Use "Eject" on the bootfs drive in File Explorer before taking the card out.')
                finished(d, d['hostname'] + '.local')
            except Exception as e:
                messagebox.showerror('Kevin Setup', 'Could not write the settings:\n\n%s' % e)
        else:
            host = d.get('ssh_host') or 'kevin.local'
            busy(True)

            def confirm_key(fp):
                ans, ev = {}, threading.Event()

                def ask():
                    ans['ok'] = messagebox.askyesno('Kevin Setup', 'First time connecting to this Pi.\nIts key is:\n\n%s\n\nConnect?' % fp)
                    ev.set()
                root.after(0, ask)
                ev.wait()
                return ans.get('ok', False)

            def job():
                try:
                    stage(0)
                    progress_lines = {'n': 0}

                    def line(t):
                        progress_lines['n'] += 1
                        if progress_lines['n'] == 2:
                            stage(1)
                        out(t)
                        root.after(0, lambda: status.set(t[:110]))
                    code = install_over_ssh(host, d['username'], d['password'], d, line, confirm_key)
                    if code == 0:
                        root.after(0, lambda: finished(d, host))
                    else:
                        root.after(0, lambda code=code: messagebox.showerror('Kevin Setup', 'The installer stopped (code %s). '
                                                                   'Tick "Show details" to see why.' % code))
                except Exception as e:
                    root.after(0, lambda e=e: messagebox.showerror('Kevin Setup', 'Could not install:\n\n%s' % e))
                finally:
                    root.after(0, lambda: busy(False))
            threading.Thread(target=job, daemon=True).start()
    go_btn.configure(command=start)
    cancel_btn.configure(command=stop.set)

    def pump():
        try:
            while True:
                log.insert('end', lines.get_nowait() + '\n')
                log.see('end')
        except queue.Empty:
            pass
        pr = work['progress']
        if pr:
            kind, done_b, total = pr
            bar['value'] = 1000 * done_b / max(total, 1)
            status.set('%s  %.1f of %.1f GB' % ('Writing' if kind == 'write' else 'Checking', done_b / 1e9, total / 1e9))
        elif work['busy'] and mode.get() != 'ssh':
            bar['value'] = 0
        root.after(150, pump)

    def closing():
        if work['busy'] and not messagebox.askyesno('Kevin Setup', 'Setup is still running. Stop it and close?'):
            return
        stop.set()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', closing)
    show('Welcome')
    pump()
    animate()
    root.mainloop()


DEMO = {'hostname': 'kevin', 'username': 'pi', 'password': 'pa"ss word1', 'wifi_ssid': 'Home "Net"',
        'wifi_password': 'secret123', 'country': 'GB', 'gemini_api_key': 'AIza-demo', 'web_password': 'webpass',
        'name': 'Kevin', 'wake_phrase': 'hey kevin', 'town': 'London', 'voice': 'Charon'}


if __name__ == '__main__':
    if '--print' in sys.argv:                 # show what would be written
        for n, t in cloud_init_files(DEMO).items():
            print('==== %s\n%s' % (n, t))
        print('==== firstrun.sh\n' + firstrun_script(DEMO))
    elif '--selftest' in sys.argv:            # the release build runs this: writes a report next to the exe
        import tempfile
        ok = True
        try:
            assert validate_card(DEMO) == [] and validate_ssh(DEMO) == []
            tmp = tempfile.mkdtemp()
            for n in ('config.txt', 'cmdline.txt'):
                open(os.path.join(tmp, n), 'w').write('console=tty1 rootwait\n' if n == 'cmdline.txt' else '')
            prepare_card(tmp, DEMO)
            import importlib.util
            import hashlib
            import lzma
            img = os.urandom(3 << 20)                     # a small "image": the writer's whole path, minus the card
            xz = lzma.compress(img)
            target = flasher.FileTarget(os.path.join(tmp, 'card.img'))
            flasher.write_image(lambda off: __import__('io').BytesIO(xz[off:]), target, len(img), hashlib.sha256(img).hexdigest())
            target.close()
            assert open(os.path.join(tmp, 'card.img'), 'rb').read()[:len(img)] == img
            assert importlib.util.find_spec('paramiko'), 'paramiko is not bundled'
        except Exception as e:
            ok = False
            msg = repr(e)
        with open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'selftest.txt'), 'w') as f:
            f.write('ok\n' if ok else 'FAILED %s\n' % msg)
        sys.exit(0 if ok else 1)
    else:
        gui()
