"""Optional: let Kevin hand a hard question to YOUR Claude or ChatGPT account (your own subscription, through the
official command-line tools: Claude Code and OpenAI's Codex). Off until you connect one on the settings page;
see docs/AI-ACCOUNTS.md.

Both run with no tools at all -- they can't read files, run commands or browse; they only answer -- in an empty
temporary folder, with a time limit. Kevin uses them for questions that need careful thought (long maths, code,
planning, a tricky explanation); everyday questions stay with Gemini, which is much faster.
"""
import json
import os
import shutil
import subprocess
import tempfile

from . import config

CODEX_HOME = os.path.join(config.STATE, 'codex')         # where the ChatGPT sign-in (auth.json) is kept
SEARCH = ['/usr/local/bin', '/usr/bin', os.path.expanduser('~/.local/bin'), '/opt/bob-assistant/node/bin']
LIMIT_S = 120


def _which(name):
    for d in SEARCH:
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    return shutil.which(name)


def status():
    """What is installed and connected, for the settings page and the tool."""
    sec = config.load_secrets()
    return {'claude': {'installed': bool(_which('claude')), 'connected': bool(sec.get('claude_token'))},
            'chatgpt': {'installed': bool(_which('codex')), 'connected': os.path.exists(os.path.join(CODEX_HOME, 'auth.json'))}}


def save_chatgpt_signin(text):
    """The contents of ~/.codex/auth.json from a computer where `codex login` was done."""
    d = json.loads(text)                       # must be JSON
    if not isinstance(d, dict) or not (d.get('tokens') or d.get('OPENAI_API_KEY')):
        raise ValueError('that is not a Codex sign-in file (auth.json)')
    os.makedirs(CODEX_HOME, mode=0o700, exist_ok=True)
    path = os.path.join(CODEX_HOME, 'auth.json')
    with open(os.open(path + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        json.dump(d, f)
    os.replace(path + '.tmp', path)


def forget(which):
    if which == 'claude':
        sec = config.load_secrets()
        sec.pop('claude_token', None)
        config.save_secrets(sec)
    elif which == 'chatgpt':
        try:
            os.unlink(os.path.join(CODEX_HOME, 'auth.json'))
        except OSError:
            pass


def _run(cmd, env, prompt=None):
    with tempfile.TemporaryDirectory() as tmp:     # an empty folder: nothing of the Pi's to look at
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=LIMIT_S, cwd=tmp, env=env)
    out = (r.stdout or '').strip()
    if r.returncode != 0 or not out:
        raise RuntimeError((r.stderr or out or 'no answer').strip()[-200:])
    return out


def ask(question, which='auto'):
    st = status()
    order = [which] if which in ('claude', 'chatgpt') else ['claude', 'chatgpt']
    ready = [w for w in order if st[w]['installed'] and st[w]['connected']]
    if not ready:
        return {'error': 'no Claude or ChatGPT account is connected yet: the settings page explains how'}
    who = ready[0]
    prompt = ('Answer for a voice assistant to read aloud: plain sentences, no markdown, no lists unless needed, '
              'as short as the question allows.\n\nQuestion: %s' % str(question)[:4000])
    base = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': tempfile.gettempdir(), 'LANG': 'C.UTF-8'}
    try:
        if who == 'claude':
            env = dict(base, CLAUDE_CODE_OAUTH_TOKEN=config.load_secrets()['claude_token'])
            out = _run([_which('claude'), '-p', '--tools', '', '--no-session-persistence', '--output-format', 'text'], env, prompt)
        else:
            env = dict(base, CODEX_HOME=CODEX_HOME)
            out = _run([_which('codex'), 'exec', '-s', 'read-only', '--skip-git-repo-check', prompt], env)
    except subprocess.TimeoutExpired:
        return {'error': 'that took too long (over two minutes)'}
    except Exception as e:
        return {'error': '%s did not answer: %s' % ('Claude' if who == 'claude' else 'ChatGPT', str(e)[:160])}
    return {'from': 'Claude' if who == 'claude' else 'ChatGPT', 'answer': out[-3000:]}
