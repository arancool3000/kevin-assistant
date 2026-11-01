"""Gmail, read-only: how many unread emails, and who the newest are from. OFF until the user sets it up with their OWN
Google Cloud OAuth client (docs/GMAIL.md); this project ships no Google credentials.

Setup (as the bob-assistant user, once):

    sudo -u bob-assistant /opt/bob-assistant/venv/bin/python -m bob.gmail setup client_secret.json

prints a Google sign-in link; after allowing access, the browser goes to a localhost address that does not load:
paste that whole address back in. The client id/secret and the refresh token go into /etc/bob/secrets.json (0600,
Kevin's user only). The only permission asked for is gmail.readonly: Kevin cannot send, delete or change anything.
`python -m bob.gmail forget` removes them again.
"""
import json
import sys
import time
import urllib.parse
import urllib.request

from . import config

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API = 'https://gmail.googleapis.com/gmail/v1/users/me/'
REDIRECT = 'http://localhost'
_token = {'access': None, 'until': 0}

DECLARATIONS = [
    {'name': 'gmail_inbox', 'description': 'The user\'s Gmail inbox, read-only: how many unread emails, and the newest ones (sender '
     'and subject). query narrows it with Gmail search words, e.g. "from:school" or "is:important". Never reads anything out '
     'loud the user did not ask for.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'count': {'type': 'NUMBER', 'description': 'how many of the newest to list (default 5, up to 20)'},
         'query': {'type': 'STRING', 'description': 'optional Gmail search, default unread in the inbox'}}}},
]


def creds():
    s = config.load_secrets()
    g = s.get('gmail') or {}
    return g if g.get('client_id') and g.get('refresh_token') else None


def enabled(cfg):
    return bool(cfg.get('gmail_enabled')) and creds() is not None


def auth_link(client_id):
    return AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': client_id, 'redirect_uri': REDIRECT, 'response_type': 'code', 'scope': SCOPE,
        'access_type': 'offline', 'prompt': 'consent'})


def code_from(pasted):
    """The 'code' from the localhost address the browser was sent to (or the bare code)."""
    p = str(pasted or '').strip()
    if '://' in p or p.startswith('localhost'):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(p if '://' in p else 'http://' + p).query)
        if 'error' in q:
            raise ValueError('Google said: %s' % q['error'][0])
        p = (q.get('code') or [''])[0]
    if not p:
        raise ValueError('no code in that address')
    return p


def _post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def access_token():
    if _token['access'] and time.time() < _token['until'] - 60:
        return _token['access']
    c = creds()
    if not c:
        raise RuntimeError('Gmail is not set up (docs/GMAIL.md)')
    d = _post(TOKEN_URL, {'client_id': c['client_id'], 'client_secret': c.get('client_secret', ''),
                          'refresh_token': c['refresh_token'], 'grant_type': 'refresh_token'})
    _token.update(access=d['access_token'], until=time.time() + int(d.get('expires_in', 3600)))
    return _token['access']


def _get(path, **q):
    url = API + path + ('?' + urllib.parse.urlencode(q, doseq=True) if q else '')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + access_token()})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _sender(v):
    """'Jane Doe <jane@example.com>' -> 'Jane Doe' (the name is what is said; the address only if there is no name)."""
    v = str(v or '').strip()
    if '<' in v:
        name = v.split('<')[0].strip().strip('"')
        return name or v.split('<')[1].rstrip('>')
    return v


def inbox(count=5, query=''):
    try:
        n = int(max(1, min(20, float(count or 5))))
    except (TypeError, ValueError):
        n = 5
    q = str(query or '').strip() or 'is:unread in:inbox'
    lst = _get('messages', q=q, maxResults=n)
    out = []
    for m in lst.get('messages', [])[:n]:
        d = _get('messages/' + m['id'], format='metadata', metadataHeaders=['From', 'Subject'])
        h = {x['name'].lower(): x['value'] for x in d.get('payload', {}).get('headers', [])}
        out.append({'from': _sender(h.get('from')), 'subject': h.get('subject', '(no subject)')[:120]})
    unread = _get('labels/INBOX').get('messagesUnread')
    return {'ok': True, 'unread_in_inbox': unread, 'query': q, 'emails': out}


class GmailTools:
    def t_gmail_inbox(self, count=5, query=''):
        if not enabled(self.cfg):
            return {'error': 'Gmail is off: the owner can set it up (docs/GMAIL.md)'}
        return inbox(count, query)


def main(argv):
    if len(argv) >= 2 and argv[0] == 'setup':
        with open(argv[1]) as f:
            raw = json.load(f)
        c = raw.get('installed') or raw.get('web') or raw
        cid, secret = c['client_id'], c.get('client_secret', '')
        print('Open this link, sign in and allow read-only access:\n\n' + auth_link(cid) + '\n')
        print('The browser then goes to a localhost address that does not load. Copy that whole address and paste it here.')
        code = code_from(input('> '))
        d = _post(TOKEN_URL, {'client_id': cid, 'client_secret': secret, 'code': code, 'redirect_uri': REDIRECT,
                              'grant_type': 'authorization_code'})
        if not d.get('refresh_token'):
            raise SystemExit('Google gave no refresh token: remove Kevin under myaccount.google.com > Security > third-party access, then try again')
        s = config.load_secrets()
        s['gmail'] = {'client_id': cid, 'client_secret': secret, 'refresh_token': d['refresh_token']}
        config.save_secrets(s)
        cfg = config.load()
        cfg['gmail_enabled'] = True
        config.save(cfg)
        print('Done: Gmail is connected (read-only). Restart Kevin: sudo systemctl restart bob-assistant')
    elif argv[:1] == ['forget']:
        s = config.load_secrets()
        s.pop('gmail', None)
        config.save_secrets(s)
        cfg = config.load()
        cfg['gmail_enabled'] = False
        config.save(cfg)
        print('Gmail disconnected. Also remove access at myaccount.google.com > Security > third-party access.')
    else:
        print('usage: python -m bob.gmail setup client_secret.json | forget')


if __name__ == '__main__':
    main(sys.argv[1:])
