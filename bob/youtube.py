"""YouTube as a music source: play what the user names, their liked songs, or a shuffle of them. Audio only, no
account, no ads: yt-dlp finds the videos and mpv (the same player as the radio) plays them, so music_control's
stop / pause / next work for YouTube too.

"Liked songs" are Kevin's own list (state folder, youtube_liked.json): say "like this song" while something plays,
or "add X to my liked songs". A real YouTube Liked list would need the user's Google account signed in on the Pi,
which Kevin deliberately does not have.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import time

from . import config, music

LIKED = os.path.join(config.STATE, 'youtube_liked.json')
MAX_SHORT = 900              # without long=true only things up to 15 minutes (songs, not ten-hour mixes)

DECLARATIONS = [
    {'name': 'youtube_play', 'description': 'Play something from YouTube as audio: a song, an artist, a mix, a podcast, a sound '
     '("rain 10 hours"). Use for "play X on YouTube" or when the music folder and radio do not have it. queue lines up that many '
     'search results one after another. Say what was found.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'query': {'type': 'STRING', 'description': 'what to play, in the user\'s words'},
         'queue': {'type': 'NUMBER', 'description': 'how many results to line up (default 1, up to 10)'},
         'long': {'type': 'BOOLEAN', 'description': 'true to allow long things (mixes, podcasts); default up to 15 minutes'}},
         'required': ['query']}},
    {'name': 'youtube_liked', 'description': 'Play the user\'s liked songs (Kevin\'s own list) from YouTube, one after another. '
     'shuffle=true for a random order. Use for "play my liked songs" / "play my favourites".',
     'parameters': {'type': 'OBJECT', 'properties': {
         'count': {'type': 'NUMBER', 'description': 'how many songs to line up (default 15, up to 50)'},
         'shuffle': {'type': 'BOOLEAN', 'description': 'random order'}}}},
    {'name': 'youtube_shuffle', 'description': 'Shuffle the liked songs and play them from YouTube in a fresh random order. Calling it '
     'again reshuffles. Use for "shuffle my music" / "mix it up".',
     'parameters': {'type': 'OBJECT', 'properties': {'count': {'type': 'NUMBER', 'description': 'how many songs, default 15'}}}},
    {'name': 'youtube_like', 'description': 'Add a song to the liked songs: the one playing now (leave song empty), or one the user '
     'names. remove=true takes it off the list. list=true just reads the list.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'song': {'type': 'STRING', 'description': 'title and artist, or empty for what is playing'},
         'remove': {'type': 'BOOLEAN', 'description': 'true to remove it'},
         'list': {'type': 'BOOLEAN', 'description': 'true to only read the list'}}}},
]


def _yes(v):
    return v is True or str(v).lower() == 'true'


def ytdlp():
    """yt-dlp from Kevin's own venv (installed by requirements.txt), else one on the PATH."""
    here = os.path.join(os.path.dirname(sys.executable), 'yt-dlp')
    return here if os.path.exists(here) else shutil.which('yt-dlp')


def search(query, n=1, long=False):
    """[(video id, title, seconds)] for a YouTube search, short things only unless long."""
    yt = ytdlp()
    if not yt:
        raise RuntimeError('yt-dlp is not installed: run the installer again')
    out = subprocess.run([yt, '--no-warnings', '--flat-playlist', '--print', '%(id)s\t%(title)s\t%(duration)s',
                          'ytsearch%d:%s' % (max(6, n * 2), query)], capture_output=True, text=True, timeout=40).stdout
    return pick_rows(out, n, long)


def pick_rows(out, n, long=False):
    rows = []
    for line in out.splitlines():
        try:
            vid, title, dur = line.split('\t')
            d = float(dur) if dur not in ('NA', 'None', '') else 0
        except ValueError:
            continue
        if long or 30 <= d <= MAX_SHORT:
            rows.append((vid, title, d))
    return rows[:n]


def _play(urls, volume, what):
    """Hand mpv a playlist of YouTube addresses: its yt-dlp hook fetches each one's audio when it is reached."""
    extra = ['--ytdl-format=bestaudio/best']
    if ytdlp():
        extra.append('--script-opts=ytdl_hook-ytdl_path=' + ytdlp())
    music._start(extra + urls, volume)
    music._now.update(what=what, kind='youtube', volume=volume)


def play(query, queue=1, long=False, volume=60):
    q = str(query or '').strip()
    if not q:
        return {'error': 'what should I play?'}
    try:
        n = int(max(1, min(10, float(queue or 1))))
    except (TypeError, ValueError):
        n = 1
    try:
        rows = search(q, n, _yes(long))
    except Exception as e:
        return {'error': 'YouTube search failed: %s' % str(e)[:120]}
    if not rows:
        return {'error': 'YouTube had nothing for %s' % q}
    _play(['https://www.youtube.com/watch?v=' + vid for vid, _t, _d in rows], volume, rows[0][1])
    return {'ok': True, 'now': rows[0][1], 'queued': len(rows) - 1}


def liked():
    try:
        with open(LIKED) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save_liked(rows):
    os.makedirs(os.path.dirname(LIKED), exist_ok=True)
    with open(LIKED + '.tmp', 'w') as f:
        json.dump(rows[-1000:], f)
    os.replace(LIKED + '.tmp', LIKED)


def like(song='', remove=False):
    s = str(song or '').strip()
    if not s:
        s = (music.now_playing().get('title') or '').strip()
        if not s:
            return {'error': 'nothing is playing: say which song'}
    rows = liked()
    key = s.lower()
    if remove:
        keep = [r for r in rows if key not in r['song'].lower()]
        _save_liked(keep)
        return {'ok': True, 'removed': len(rows) - len(keep)}
    if not any(r['song'].lower() == key for r in rows):
        rows.append({'song': s, 'at': time.strftime('%Y-%m-%d')})
        _save_liked(rows)
    return {'ok': True, 'liked': s, 'total': len(rows)}


def play_liked(count=15, shuffle=False, volume=60):
    """Each liked song goes to mpv as a YouTube search (ytdl://ytsearch1:...), looked up only when its turn comes, so
    the first one starts straight away however long the list is."""
    songs = [r['song'] for r in liked()]
    if not songs:
        return {'error': 'there are no liked songs yet: say "like this song" while one plays'}
    if shuffle:
        random.shuffle(songs)
    try:
        n = int(max(1, min(50, float(count or 15))))
    except (TypeError, ValueError):
        n = 15
    songs = songs[:n]
    _play(['ytdl://ytsearch1:' + s for s in songs], volume, 'liked songs' + (' (shuffled)' if shuffle else ''))
    return {'ok': True, 'first': songs[0], 'queued': len(songs) - 1, 'shuffled': bool(shuffle)}


class YouTubeTools:
    def t_youtube_play(self, query, queue=1, long=False):
        return play(query, queue, long, int(self.cfg.get('music_volume', 60)))

    def t_youtube_liked(self, count=15, shuffle=False):
        return play_liked(count, _yes(shuffle), int(self.cfg.get('music_volume', 60)))

    def t_youtube_shuffle(self, count=15):
        return play_liked(count, True, int(self.cfg.get('music_volume', 60)))

    def t_youtube_like(self, song='', remove=False, list=False):
        if _yes(list):
            return {'liked': [r['song'] for r in liked()][-50:]}
        return like(song, _yes(remove))
