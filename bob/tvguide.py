"""A TV guide: what is on now and next, or tonight, from the BBC's free public schedule service (no key). Only the BBC
publishes an open listing like this; for other channels Kevin can search the web instead.

The regional BBC One / Two variants are settings (tv_bbc_one, tv_bbc_two), e.g. bbc_one_scotland or bbc_two_wales.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

URL = 'https://ess.api.bbci.co.uk/schedules?serviceId=%s&d=%s'
NAMES = {'one': 'BBC One', 'two': 'BBC Two', 'three': 'BBC Three', 'four': 'BBC Four', 'news': 'BBC News',
         'cbbc': 'CBBC', 'cbeebies': 'CBeebies'}
FIXED = {'three': 'bbc_three', 'four': 'bbc_four', 'news': 'bbc_news24', 'cbbc': 'cbbc', 'cbeebies': 'cbeebies'}

DECLARATIONS = [
    {'name': 'tv_guide', 'description': 'The TV guide for the BBC channels: what is on now and next, or tonight, on BBC One, Two, '
     'Three, Four, News, CBBC or CBeebies. For other broadcasters there is no free listing: search the web instead.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'channel': {'type': 'STRING', 'description': 'bbc one, bbc two, bbc three, bbc four, bbc news, cbbc or cbeebies (default: One and Two)'},
         'when': {'type': 'STRING', 'description': 'now (default), tonight or today'}}}},
]


def channel_key(text):
    """'BBC1', 'bbc one', 'one' -> 'one'; '' -> None (the main two); unknown -> False."""
    t = str(text or '').lower().replace('bbc', '').replace(' ', '').strip()
    t = {'1': 'one', '2': 'two', '3': 'three', '4': 'four', 'news24': 'news'}.get(t, t)
    if not t:
        return None
    return t if t in NAMES else False


def service(key, cfg):
    if key == 'one':
        return cfg.get('tv_bbc_one') or 'bbc_one_london'
    if key == 'two':
        return cfg.get('tv_bbc_two') or 'bbc_two_england'
    return FIXED[key]


def _day(sid, day):
    req = urllib.request.Request(URL % (sid, day), headers={'User-Agent': 'kevin-assistant'})
    with urllib.request.urlopen(req, timeout=9) as r:
        return json.load(r).get('items') or []


def _title(it):
    b = (it.get('brand') or {}).get('title')
    if b and str(b).startswith('no_brand'):
        b = None
    e = (it.get('episode') or {}).get('title')
    return b if b and (not e or e == b) else ('%s: %s' % (b, e) if b and e else (e or b or 'something'))


def programmes(items, now):
    """[(start, end, title)] still to finish, local time, one per slot (the BBC lists each version separately)."""
    rows = set()
    for it in items:
        try:
            s = datetime.fromisoformat(it['published_time']['start'].replace('Z', '+00:00')).astimezone()
            e = datetime.fromisoformat(it['published_time']['end'].replace('Z', '+00:00')).astimezone()
        except (KeyError, ValueError, TypeError):
            continue
        if e > now:
            rows.add((s, e, _title(it)))
    return sorted(rows)


def summary(name, rows, when, now):
    if when in ('tonight', 'today'):
        lo = now.replace(hour=18, minute=0, second=0) if when == 'tonight' else now
        hi = now.replace(hour=23, minute=59, second=0)
        pick = [r for r in rows if r[0] < hi and r[1] > lo][:6]
        return ('%s: %s.' % (name, '; '.join('%s %s' % (r[0].strftime('%H:%M'), r[2]) for r in pick))) if pick else ''
    cur = next((r for r in rows if r[0] <= now < r[1]), None)
    nxt = next((r for r in rows if r[0] > now), None)
    parts = []
    if cur:
        parts.append('%s now, until %s' % (cur[2], cur[1].strftime('%H:%M')))
    if nxt:
        parts.append('then %s at %s' % (nxt[2], nxt[0].strftime('%H:%M')))
    return ('%s: %s.' % (name, ', '.join(parts))) if parts else ''


def guide(cfg, channel=None, when='now'):
    key = channel_key(channel)
    if key is False:
        return {'error': 'no free listing for that channel: only the BBC channels (One, Two, Three, Four, News, CBBC, CBeebies)'}
    keys = [key] if key else ['one', 'two']
    w = str(when or 'now').lower()
    now = datetime.now(timezone.utc).astimezone()
    said, out = [], {}
    for k in keys:
        try:
            items = _day(service(k, cfg), now.strftime('%Y-%m-%d'))
            if now.hour >= 20 or w == 'tonight':
                items += _day(service(k, cfg), (now + timedelta(days=1)).strftime('%Y-%m-%d'))
        except Exception as e:
            return {'error': 'the BBC schedule did not answer: %s' % str(e)[:80]}
        rows = programmes(items, now)
        out[NAMES[k]] = [(r[0].strftime('%H:%M'), r[2]) for r in rows[:8]]
        line = summary(NAMES[k], rows, w, now)
        if line:
            said.append(line)
    return {'ok': True, 'listings': out, 'say': ' '.join(said) or 'Nothing is listed.'}


class TVGuideTools:
    def t_tv_guide(self, channel=None, when='now'):
        return guide(self.cfg, channel, when)
