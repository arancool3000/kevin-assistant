"""Health checks, a bug watcher and gentle self-healing for Kevin's own services.

Run every 5 minutes as root by bob-assistant-health.timer (`python -m bob.health --heal`). Each run:

  * checks Kevin's services (systemctl is-active), the CPU temperature, free disk and memory;
  * restarts a Kevin service that has failed or stopped -- at most once per 30 minutes per service (only the units
    listed in the health_units setting are ever touched; a running service is never restarted);
  * reads the new journal lines of those services and turns each new Python crash (a Traceback) into one bug
    record: the error and the file and line, deduplicated, at most one per bug per hour.

Results go to the state folder (health.json, bugs.jsonl) so the health_report tool and the settings page can show
them. Transcripts are never looked at: any line containing 'heard:' or 'said:' is dropped before parsing.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import config

REPORT = os.path.join(config.STATE, 'health.json')
BUGS = os.path.join(config.STATE, 'bugs.jsonl')
COOLDOWN = 1800
BUG_REPEAT = 3600
UNITS = ['bob-assistant', 'bob-assistant-web', 'bob-assistant-skills']
TEMP_WARN, DISK_WARN_GB, MEM_WARN_MB = 80.0, 1.0, 100
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
EXC = re.compile(r'^(\w+(?:\.\w+)*(?:Error|Exception))(?::\s*(.*))?$')
PRIVATE = re.compile(r'heard:|said:', re.I)

DECLARATIONS = [
    {'name': 'health_report', 'description': 'Is Kevin healthy? His services, temperature, disk and memory, recent restarts by the '
     'self-healer, and recent crashes the bug watcher found.', 'parameters': {'type': 'OBJECT', 'properties': {}}},
]


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w') as f:
        json.dump(d, f)
    os.replace(path + '.tmp', path)


def unit_state(unit):
    try:
        return subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=10).stdout.strip() or 'unknown'
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def checks(units):
    """{'services': {unit: state}, 'faults': [sentences]} -- everything a person would want to hear about."""
    faults, services = [], {}
    for u in units:
        services[u] = unit_state(u)
        if services[u] not in ('active', 'activating', 'reloading', 'unknown'):
            faults.append('%s is %s' % (u, services[u]))
    out = {'services': services}
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            out['cpu_temp_c'] = round(int(f.read()) / 1000.0, 1)
        if out['cpu_temp_c'] >= TEMP_WARN:
            faults.append('the CPU is hot (%.0f C)' % out['cpu_temp_c'])
    except (OSError, ValueError):
        pass
    out['disk_free_gb'] = round(shutil.disk_usage('/').free / 1e9, 1)
    if out['disk_free_gb'] < DISK_WARN_GB:
        faults.append('the disk is nearly full (%.1f GB free)' % out['disk_free_gb'])
    try:
        with open('/proc/meminfo') as f:
            m = {l.split(':')[0]: int(l.split()[1]) for l in f}
        out['memory_free_mb'] = round(m.get('MemAvailable', 0) / 1024)
        if out['memory_free_mb'] < MEM_WARN_MB:
            faults.append('memory is low (%d MB free)' % out['memory_free_mb'])
    except (OSError, ValueError):
        pass
    out['faults'] = faults
    return out


def heal(services, done, now=None, restart=None):
    """Restart failed/stopped units (cooldown per unit). Returns the units restarted. restart: for tests."""
    now = now or time.time()
    restart = restart or (lambda u: subprocess.run(['systemctl', 'restart', u], timeout=60))
    out = []
    for u, st in services.items():
        if st not in ('failed', 'inactive'):
            continue
        if now - done.get(u, 0) < COOLDOWN:
            continue
        done[u] = now
        restart(u)
        out.append(u)
    return out


def tracebacks(lines):
    """[(error, 'file:line in func')] for each Python crash in some log lines (transcript lines dropped first)."""
    found, frame, inside = [], None, False
    for raw in lines:
        if PRIVATE.search(raw):
            continue
        line = raw.split(': ', 1)[-1].strip() if ']: ' in raw else raw.strip()
        if line.startswith('Traceback (most recent call last)'):
            inside, frame = True, None
            continue
        if not inside:
            continue
        m = FRAME.search(line)
        if m:
            frame = '%s:%s in %s' % (os.path.basename(m.group(1)), m.group(2), m.group(3))
            continue
        e = EXC.match(line)
        if e:
            found.append(((e.group(1) + (': ' + e.group(2) if e.group(2) else ''))[:200], frame or '?'))
            inside = False
    return found


def watch_bugs(units, st, now=None):
    """New crashes in the journal since the last run, as bug records (each bug at most once an hour)."""
    now = now or time.time()
    since = st.get('since', now - 300)
    cmd = ['journalctl', '--no-pager', '-o', 'short', '--since', '@%d' % int(since)]
    for u in units:
        cmd += ['-u', u]
    try:
        lines = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        lines = []
    st['since'] = now
    seen = st.setdefault('seen', {})
    new = []
    for err, where in tracebacks(lines):
        key = err.split(':')[0] + '@' + where
        if now - seen.get(key, 0) < BUG_REPEAT:
            continue
        seen[key] = now
        new.append({'at': time.strftime('%Y-%m-%d %H:%M', time.localtime(now)), 'error': err, 'where': where})
    if new:
        os.makedirs(os.path.dirname(BUGS), exist_ok=True)
        with open(BUGS, 'a') as f:
            for b in new:
                f.write(json.dumps(b) + '\n')
    for k in [k for k, t in seen.items() if now - t > 7 * 86400]:
        del seen[k]
    return new


def recent_bugs(n=10):
    try:
        with open(BUGS) as f:
            rows = [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        return []
    return rows[-n:]


def run(do_heal=True):
    cfg = config.load()
    units = cfg.get('health_units') or UNITS
    st = _load(REPORT, {})
    rep = checks(units)
    rep['restarted'] = heal(rep['services'], st.setdefault('restarted_at', {})) if do_heal and cfg.get('self_heal', True) else []
    rep['new_bugs'] = watch_bugs(units, st.setdefault('bugwatch', {}))
    rep['at'] = time.time()
    st['last'] = rep
    _save(REPORT, st)
    return rep


class HealthTools:
    def t_health_report(self):
        st = _load(REPORT, {})
        last = st.get('last') or {}
        live = checks(self.cfg.get('health_units') or UNITS)
        restarts = {u: time.strftime('%d %b %H:%M', time.localtime(t)) for u, t in (st.get('restarted_at') or {}).items()}
        return {'faults': live['faults'], 'services': live['services'], 'cpu_temp_c': live.get('cpu_temp_c'),
                'disk_free_gb': live['disk_free_gb'], 'memory_free_mb': live.get('memory_free_mb'),
                'last_check': time.strftime('%H:%M', time.localtime(last['at'])) if last.get('at') else None,
                'self_heal_restarts': restarts, 'recent_bugs': recent_bugs(5),
                'say': ('All well.' if not live['faults'] else 'Problems: ' + '; '.join(live['faults']) + '.')}


if __name__ == '__main__':
    r = run('--heal' in sys.argv)
    print(json.dumps({k: r[k] for k in ('faults', 'restarted', 'new_bugs')}))
