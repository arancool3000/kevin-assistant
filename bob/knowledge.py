"""Kevin's general-knowledge tools: weather extras, facts, maths, conversions, games.

All free public APIs with no key (Open-Meteo, Wikipedia, Frankfurter, USGS, ...) or computed locally.
Every network call has a 10 second timeout, every tool returns a small dict and never raises -- on failure
it returns {'error': 'short plain words'}. Results are spoken aloud, so lists are capped at 5.
"""
import ast
import datetime
import functools
import html
import json
import math
import operator
import random
import re
import urllib.error
import urllib.parse
import urllib.request

S = lambda d: {'type': 'STRING', 'description': d}      # noqa: E731
N = lambda d: {'type': 'NUMBER', 'description': d}      # noqa: E731
OBJ = lambda props=None, req=None: {'type': 'OBJECT', 'properties': props or {}, 'required': req or []}   # noqa: E731

UA = 'Kevin-assistant (https://github.com/arancool3000/kevin-assistant)'

DECLARATIONS = [
    {'name': 'rain_next_hour', 'description': 'Will it rain in the next two hours here? When it starts and stops.', 'parameters': OBJ()},
    {'name': 'uv_index', 'description': 'The UV index now and today\'s maximum here, with sun cream advice.', 'parameters': OBJ()},
    {'name': 'air_quality', 'description': 'Air quality here right now (European AQI and PM2.5) in plain words.', 'parameters': OBJ()},
    {'name': 'sunrise_sunset', 'description': 'Sunrise, sunset and day length here, today and tomorrow.', 'parameters': OBJ()},
    {'name': 'wikipedia', 'description': 'A short Wikipedia summary of a topic, person or place.',
     'parameters': OBJ({'topic': S('what to look up')}, ['topic'])},
    {'name': 'on_this_day', 'description': 'Historical events that happened on today\'s date.',
     'parameters': OBJ({'count': N('how many events, default 3, max 5')})},
    {'name': 'define_word', 'description': 'The dictionary definition of an English word.',
     'parameters': OBJ({'word': S('the word')}, ['word'])},
    {'name': 'currency_convert', 'description': 'Convert money between currencies at the latest European Central Bank rate.',
     'parameters': OBJ({'amount': N('amount of money'), 'from_currency': S('3-letter code, e.g. GBP'),
                        'to_currency': S('3-letter code, e.g. USD')}, ['amount', 'from_currency', 'to_currency'])},
    {'name': 'public_holidays', 'description': 'The next public holidays in a country (default: where the user lives).',
     'parameters': OBJ({'country': S('optional: 2-letter code or country name'), 'count': N('how many, default 3, max 5')})},
    {'name': 'tell_joke', 'description': 'Tell a random dad joke.', 'parameters': OBJ()},
    {'name': 'where_is_the_iss', 'description': 'Where the International Space Station is right now, and how far from here.', 'parameters': OBJ()},
    {'name': 'people_in_space', 'description': 'Who is in space right now.', 'parameters': OBJ()},
    {'name': 'earthquakes', 'description': 'Recent earthquakes around the world, biggest first.',
     'parameters': OBJ({'period': S('day, week or significant (default day)'), 'min_magnitude': N('default 4.5')})},
    {'name': 'recipe_search', 'description': 'Find a recipe by dish name or by an ingredient you have.',
     'parameters': OBJ({'dish': S('dish name, e.g. lasagne'), 'ingredient': S('main ingredient, e.g. chicken')})},
    {'name': 'book_lookup', 'description': 'Look up a book: author, first year published, editions.',
     'parameters': OBJ({'title': S('book title')}, ['title'])},
    {'name': 'trivia_question', 'description': 'A multiple choice trivia question with the answer, to quiz the user.',
     'parameters': OBJ({'category': S('optional: general, books, film, music, science, computers, maths, sports, geography, history, animals, art')})},
    {'name': 'time_in', 'description': 'The current local time in any city or place.',
     'parameters': OBJ({'place': S('city or place')}, ['place'])},
    {'name': 'moon_phase', 'description': 'Tonight\'s moon phase, how lit it is, and the next full moon.', 'parameters': OBJ()},
    {'name': 'calculate', 'description': 'Work out a maths expression exactly. Supports + - * / // % **, brackets, sqrt sin cos tan log log10 abs round, pi, e.',
     'parameters': OBJ({'expression': S('e.g. (12.5*8)+sqrt(81)')}, ['expression'])},
    {'name': 'convert_units', 'description': 'Convert between units of length, mass, volume, temperature or speed.',
     'parameters': OBJ({'value': N('the number'), 'from_unit': S('e.g. miles, kg, c, tbsp'), 'to_unit': S('e.g. km, lb, f, ml')},
                       ['value', 'from_unit', 'to_unit'])},
    {'name': 'countdown_to', 'description': 'How many days until a date or holiday.',
     'parameters': OBJ({'date': S('e.g. 25 December, 2026-12-25, christmas, new year')}, ['date'])},
    {'name': 'flip_coin', 'description': 'Flip a coin.', 'parameters': OBJ()},
    {'name': 'roll_dice', 'description': 'Roll one or more dice.',
     'parameters': OBJ({'sides': N('sides per die, default 6'), 'count': N('number of dice, default 1')})},
    {'name': 'random_number', 'description': 'A random whole number between two values.',
     'parameters': OBJ({'low': N('default 1'), 'high': N('default 100')})},
    {'name': 'pick_one', 'description': 'Pick one option at random.',
     'parameters': OBJ({'options': S('options separated by commas')}, ['options'])},
    {'name': 'spell_word', 'description': 'Spell a word letter by letter and count its letters.',
     'parameters': OBJ({'word': S('the word')}, ['word'])},
]


# ---------------------------------------------------------------------------------------------- helpers

def _get(url, params=None, headers=None):
    """GET a URL and decode the JSON reply (10 second timeout)."""
    if params:
        url += '?' + urllib.parse.urlencode(params)
    h = {'User-Agent': UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _safe(fn):
    """Tools never raise: any failure becomes {'error': 'short plain words'}."""
    @functools.wraps(fn)
    def wrap(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except TypeError:
            raise                                   # wrong arguments: let the caller's handler say so
        except (OSError, ValueError, KeyError, IndexError):
            return {'error': 'I could not get that just now'}
        except Exception:
            return {'error': 'something went wrong with that'}
    return wrap


def _sentences(text, n=2):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', (text or '').strip())
    return ' '.join(parts[:n])


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1, math.sqrt(a)))


def _clock(iso):
    return iso[11:16] if iso and len(iso) >= 16 else iso


COUNTRIES = {'united kingdom': 'GB', 'uk': 'GB', 'britain': 'GB', 'great britain': 'GB', 'england': 'GB', 'scotland': 'GB',
             'wales': 'GB', 'united states': 'US', 'usa': 'US', 'america': 'US', 'canada': 'CA', 'australia': 'AU',
             'new zealand': 'NZ', 'ireland': 'IE', 'france': 'FR', 'germany': 'DE', 'spain': 'ES', 'italy': 'IT',
             'netherlands': 'NL', 'belgium': 'BE', 'portugal': 'PT', 'sweden': 'SE', 'norway': 'NO', 'denmark': 'DK',
             'poland': 'PL', 'japan': 'JP', 'india': 'IN', 'brazil': 'BR', 'mexico': 'MX', 'south africa': 'ZA'}

# ---------------------------------------------------------------------------------------------- maths

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_FUNCS = {'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos, 'tan': math.tan, 'log': math.log,
          'log10': math.log10, 'abs': abs, 'round': round}
_CONSTS = {'pi': math.pi, 'e': math.e}


def _eval(node, depth=0):
    if depth > 30:
        raise ValueError('too deep')
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth + 1)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, depth + 1)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left, depth + 1), _eval(node.right, depth + 1)
        if isinstance(node.op, ast.Pow):
            if abs(b) > 1000 or (abs(a) > 1 and abs(b) * math.log2(abs(a)) > 4000):
                raise ValueError('too big')
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        if not 1 <= len(node.args) <= 2:
            raise ValueError('arguments')
        return _FUNCS[node.func.id](*[_eval(a, depth + 1) for a in node.args])
    raise ValueError('not allowed')


# ---------------------------------------------------------------------------------------------- units

_UNITS = {   # name -> (kind, factor to base unit)
    'mm': ('length', 0.001), 'cm': ('length', 0.01), 'm': ('length', 1), 'km': ('length', 1000),
    'in': ('length', 0.0254), 'ft': ('length', 0.3048), 'yd': ('length', 0.9144), 'mi': ('length', 1609.344),
    'g': ('mass', 1), 'kg': ('mass', 1000), 'oz': ('mass', 28.349523125), 'lb': ('mass', 453.59237), 'st': ('mass', 6350.29318),
    'ml': ('volume', 1), 'l': ('volume', 1000), 'tsp': ('volume', 5), 'tbsp': ('volume', 15), 'cup': ('volume', 250),
    'floz': ('volume', 28.4130625), 'pint': ('volume', 568.26125), 'gallon': ('volume', 4546.09),
    'kmh': ('speed', 1 / 3.6), 'mph': ('speed', 0.44704), 'ms': ('speed', 1), 'knots': ('speed', 1852 / 3600.0),
    'c': ('temp', None), 'f': ('temp', None), 'k': ('temp', None)}
_ALIASES = {'millimetre': 'mm', 'millimeter': 'mm', 'centimetre': 'cm', 'centimeter': 'cm', 'metre': 'm', 'meter': 'm',
            'kilometre': 'km', 'kilometer': 'km', 'inch': 'in', 'inches': 'in', 'foot': 'ft', 'feet': 'ft', 'yard': 'yd',
            'mile': 'mi', 'gram': 'g', 'kilogram': 'kg', 'kilo': 'kg', 'ounce': 'oz', 'pound': 'lb', 'stone': 'st',
            'millilitre': 'ml', 'milliliter': 'ml', 'litre': 'l', 'liter': 'l', 'teaspoon': 'tsp', 'tablespoon': 'tbsp',
            'fluid ounce': 'floz', 'fl oz': 'floz', 'pints': 'pint', 'gallons': 'gallon', 'cups': 'cup',
            'celsius': 'c', 'centigrade': 'c', 'fahrenheit': 'f', 'kelvin': 'k', 'kph': 'kmh', 'km/h': 'kmh',
            'm/s': 'ms', 'knot': 'knots', 'kt': 'knots'}


def _unit(u):
    u = str(u).strip().lower().replace('°', '').replace('degrees ', '').replace('degree ', '')
    u = _ALIASES.get(u, u)
    if u not in _UNITS and u.endswith('s') and u[:-1] in _UNITS:
        u = u[:-1]
    u = _ALIASES.get(u, u)
    return u if u in _UNITS else None


def _to_c(v, u):
    return v if u == 'c' else (v - 32) * 5 / 9 if u == 'f' else v - 273.15


def _from_c(v, u):
    return v if u == 'c' else v * 9 / 5 + 32 if u == 'f' else v + 273.15


# ---------------------------------------------------------------------------------------------- dates

_MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
           'november', 'december']
_NAMED = {'christmas': (12, 25), 'christmas day': (12, 25), 'christmas eve': (12, 24), 'new year': (1, 1),
          'new years day': (1, 1), "new year's day": (1, 1), 'new year\'s eve': (12, 31), 'new years eve': (12, 31),
          'halloween': (10, 31), 'valentines day': (2, 14), "valentine's day": (2, 14), 'boxing day': (12, 26),
          'bonfire night': (11, 5), 'st patricks day': (3, 17), "st patrick's day": (3, 17)}


def _month_day(text):
    t = text.strip().lower().replace(',', ' ')
    t = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', t)
    t = re.sub(r'\b(the|of)\b', ' ', t)
    t = ' '.join(t.split())
    if t in _NAMED:
        return _NAMED[t] + (None,)
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', t)
    if m:
        return int(m.group(2)), int(m.group(3)), int(m.group(1))
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', t)          # UK style day/month/year
    if m:
        return int(m.group(2)), int(m.group(1)), int(m.group(3))
    m = re.match(r'^(\d{1,2}) ([a-z]+)(?: (\d{4}))?$', t)
    if m:
        d, mon, y = m.groups()
    else:
        m = re.match(r'^([a-z]+) (\d{1,2})(?: (\d{4}))?$', t)
        if not m:
            raise ValueError('date')
        mon, d, y = m.groups()
    months = [x for x in _MONTHS if len(mon) >= 3 and x.startswith(mon)]
    if not months:
        raise ValueError('month')
    return _MONTHS.index(months[0]) + 1, int(d), int(y) if y else None


# ---------------------------------------------------------------------------------------------- tools

class KnowledgeTools:
    def __init__(self, cfg=None):
        self.cfg = cfg if cfg is not None else {}

    # -- location

    def _here(self):
        """{'lat','lon','tz','country'?} for the user's town, or {'error': ...}."""
        c = self.cfg
        if c.get('latitude') is not None and c.get('longitude') is not None:
            return {'lat': float(c['latitude']), 'lon': float(c['longitude']), 'tz': c.get('timezone') or 'auto'}
        if c.get('town'):
            from .tools import geocode           # here, not at the top: tools.py is imported first
            lat, lon, tz, _label = geocode(c['town'])
            return {'lat': lat, 'lon': lon, 'tz': tz or 'auto'}
        return {'error': 'I do not know where you are: please set your town on the settings page'}

    def _geo(self, place):
        d = _get('https://geocoding-api.open-meteo.com/v1/search',
                 {'name': place, 'count': 1, 'language': 'en', 'format': 'json'})
        res = (d.get('results') or [None])[0]
        if not res:
            raise ValueError('place')
        return res

    # -- weather and sky

    @_safe
    def t_rain_next_hour(self):
        h = self._here()
        if 'error' in h:
            return h
        d = _get('https://api.open-meteo.com/v1/forecast',
                 {'latitude': h['lat'], 'longitude': h['lon'], 'timezone': h['tz'], 'minutely_15': 'precipitation',
                  'forecast_minutely_15': 8})
        m = d['minutely_15']
        times, mm = m['time'], m['precipitation']
        pts = [(t, v or 0) for t, v in zip(times, mm)][:8]
        wet = [i for i, (_, v) in enumerate(pts) if v >= 0.1]
        if not wet:
            return {'rain_expected': False, 'summary': 'No rain expected in the next two hours'}
        first = wet[0]
        out = {'rain_expected': True, 'total_mm': round(sum(v for _, v in pts), 1)}
        if first == 0:
            out['raining_now'] = True
            gap = [i for i, (_, v) in enumerate(pts) if v < 0.1]
            out['stops_around'] = _clock(pts[gap[0]][0]) if gap else None
            out['summary'] = 'It is raining now' + (', easing around %s' % out['stops_around'] if gap else ' and keeps going for two hours')
        else:
            out['starts_around'] = _clock(pts[first][0])
            out['summary'] = 'Rain starting around %s' % out['starts_around']
        return out

    @_safe
    def t_uv_index(self):
        h = self._here()
        if 'error' in h:
            return h
        d = _get('https://api.open-meteo.com/v1/forecast',
                 {'latitude': h['lat'], 'longitude': h['lon'], 'timezone': h['tz'], 'current': 'uv_index',
                  'daily': 'uv_index_max', 'forecast_days': 1})
        now, top = d['current']['uv_index'], d['daily']['uv_index_max'][0]
        lvl = 'low' if top < 3 else 'moderate' if top < 6 else 'high' if top < 8 else 'very high' if top < 11 else 'extreme'
        advice = 'Wear sun cream and a hat, and find shade at midday' if top >= 3 else 'No sun cream needed'
        return {'uv_now': now, 'uv_max_today': top, 'level': lvl, 'advice': advice}

    @_safe
    def t_air_quality(self):
        h = self._here()
        if 'error' in h:
            return h
        d = _get('https://air-quality-api.open-meteo.com/v1/air-quality',
                 {'latitude': h['lat'], 'longitude': h['lon'], 'timezone': h['tz'], 'current': 'european_aqi,pm2_5'})
        c = d['current']
        a = c['european_aqi']
        if a is None:
            return {'error': 'no air quality reading for here'}
        label = ('good' if a <= 20 else 'fair' if a <= 40 else 'moderate' if a <= 60 else 'poor' if a <= 80
                 else 'very poor' if a <= 100 else 'extremely poor')
        return {'european_aqi': a, 'pm2_5': c['pm2_5'], 'label': label}

    @_safe
    def t_sunrise_sunset(self):
        h = self._here()
        if 'error' in h:
            return h
        d = _get('https://api.open-meteo.com/v1/forecast',
                 {'latitude': h['lat'], 'longitude': h['lon'], 'timezone': h['tz'], 'forecast_days': 2,
                  'daily': 'sunrise,sunset,daylight_duration'})['daily']
        out = {}
        for i, day in enumerate(('today', 'tomorrow')):
            if i < len(d['sunrise']):
                secs = d['daylight_duration'][i] or 0
                out[day] = {'sunrise': _clock(d['sunrise'][i]), 'sunset': _clock(d['sunset'][i]),
                            'daylight': '%d hours %d minutes' % (secs // 3600, secs % 3600 // 60)}
        return out

    @_safe
    def t_moon_phase(self):
        synodic = 29.530588853
        ref = datetime.datetime(2000, 1, 6, 18, 14, tzinfo=datetime.timezone.utc)     # a known new moon
        now = datetime.datetime.now(datetime.timezone.utc)
        age = ((now - ref).total_seconds() / 86400.0) % synodic
        frac = age / synodic
        names = ['new moon', 'waxing crescent', 'first quarter', 'waxing gibbous', 'full moon', 'waning gibbous',
                 'last quarter', 'waning crescent']
        name = names[int(frac * 8 + 0.5) % 8]
        illum = round((1 - math.cos(2 * math.pi * frac)) / 2 * 100)
        to_full = (synodic / 2 - age) % synodic
        full = now + datetime.timedelta(days=to_full)
        return {'phase': name, 'illumination_pct': illum, 'next_full_moon': full.strftime('%A %d %B'),
                'days_to_full_moon': round(to_full)}

    # -- reference

    @_safe
    def t_wikipedia(self, topic):
        topic = (topic or '').strip()
        if not topic:
            return {'error': 'what should I look up?'}
        base = 'https://en.wikipedia.org/api/rest_v1/page/summary/'

        def summary(title):
            return _get(base + urllib.parse.quote(title.replace(' ', '_'), safe=''))
        try:
            d = summary(topic)
        except Exception:
            d = None
        if not d or d.get('type') == 'disambiguation' or not d.get('extract'):
            s = _get('https://en.wikipedia.org/w/api.php',
                     {'action': 'opensearch', 'search': topic, 'limit': 1, 'format': 'json'})
            if not s[1]:
                return {'error': 'I found nothing on Wikipedia for %s' % topic}
            d = summary(s[1][0])
        if not d.get('extract'):
            return {'error': 'I found nothing on Wikipedia for %s' % topic}
        return {'title': d.get('title', topic), 'summary': _sentences(d['extract'], 2)}

    @_safe
    def t_on_this_day(self, count=3):
        n = max(1, min(5, int(count or 3)))
        t = datetime.date.today()
        d = _get('https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/%02d/%02d' % (t.month, t.day))
        ev = d.get('events') or []
        if not ev:
            return {'error': 'I found no events for today'}
        picks = random.sample(ev, min(n, len(ev)))
        picks.sort(key=lambda e: e.get('year', 0))
        return {'date': t.strftime('%d %B'), 'events': [{'year': e.get('year'), 'what': e.get('text', '')[:200]} for e in picks]}

    @_safe
    def t_define_word(self, word):
        w = (word or '').strip().lower()
        if not w:
            return {'error': 'which word?'}
        try:
            d = _get('https://api.dictionaryapi.dev/api/v2/entries/en/' + urllib.parse.quote(w, safe=''))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {'error': 'I could not find the word %s' % w}
            raise
        meanings = []
        for m in (d[0].get('meanings') or []):
            for df in (m.get('definitions') or [])[:1]:
                item = {'part_of_speech': m.get('partOfSpeech', ''), 'meaning': df.get('definition', '')[:200]}
                if df.get('example'):
                    item['example'] = df['example'][:150]
                meanings.append(item)
            if len(meanings) >= 2:
                break
        if not meanings:
            return {'error': 'I could not find the word %s' % w}
        return {'word': d[0].get('word', w), 'meanings': meanings[:2]}

    @_safe
    def t_book_lookup(self, title):
        if not (title or '').strip():
            return {'error': 'which book?'}
        d = _get('https://openlibrary.org/search.json',
                 {'q': title, 'limit': 1, 'fields': 'title,author_name,first_publish_year,edition_count'})
        docs = d.get('docs') or []
        if not docs:
            return {'error': 'I could not find that book'}
        b = docs[0]
        return {'title': b.get('title'), 'author': ', '.join((b.get('author_name') or ['unknown'])[:2]),
                'first_published': b.get('first_publish_year'), 'editions': b.get('edition_count')}

    @_safe
    def t_recipe_search(self, dish='', ingredient=''):
        base = 'https://www.themealdb.com/api/json/v1/1/'
        if dish:
            meals = _get(base + 'search.php', {'s': dish}).get('meals')
        elif ingredient:
            found = _get(base + 'filter.php', {'i': ingredient.strip().replace(' ', '_')}).get('meals')
            meals = _get(base + 'lookup.php', {'i': random.choice(found)['idMeal']}).get('meals') if found else None
        else:
            return {'error': 'which dish or ingredient?'}
        if not meals:
            return {'error': 'I could not find a recipe for that'}
        m = meals[0]
        ing = []
        for i in range(1, 21):
            name = (m.get('strIngredient%d' % i) or '').strip()
            if name:
                ing.append(('%s %s' % ((m.get('strMeasure%d' % i) or '').strip(), name)).strip())
        method = ' '.join((m.get('strInstructions') or '').split())
        if len(method) > 600:
            method = method[:600].rsplit(' ', 1)[0] + '...'
        return {'name': m.get('strMeal'), 'ingredients': ing[:12], 'method': method}

    @_safe
    def t_trivia_question(self, category=''):
        cats = {'general': 9, 'books': 10, 'film': 11, 'music': 12, 'science': 17, 'computers': 18, 'maths': 19,
                'sports': 21, 'geography': 22, 'history': 23, 'animals': 27, 'art': 25}
        p = {'amount': 1, 'type': 'multiple'}
        c = (category or '').strip().lower()
        if c in cats:
            p['category'] = cats[c]
        d = _get('https://opentdb.com/api.php', p)
        r = (d.get('results') or [None])[0]
        if not r:
            return {'error': 'I could not get a question just now'}
        answer = html.unescape(r['correct_answer'])
        opts = [answer] + [html.unescape(x) for x in r['incorrect_answers']]
        random.shuffle(opts)
        return {'category': html.unescape(r.get('category', '')), 'question': html.unescape(r['question']),
                'options': opts, 'answer': answer}

    # -- money, places, time

    @_safe
    def t_currency_convert(self, amount, from_currency, to_currency):
        a, f, t = float(amount), str(from_currency).strip().upper(), str(to_currency).strip().upper()
        if not (len(f) == 3 and len(t) == 3):
            return {'error': 'use 3 letter currency codes like GBP and USD'}
        if f == t:
            return {'amount': a, 'from': f, 'to': t, 'result': a}
        try:
            d = _get('https://api.frankfurter.app/latest', {'amount': a, 'from': f, 'to': t})
        except urllib.error.HTTPError:
            return {'error': 'I do not know one of those currencies'}
        r = d['rates'][t]
        return {'amount': a, 'from': f, 'to': t, 'result': round(r, 2), 'rate_date': d.get('date')}

    @_safe
    def t_public_holidays(self, country='', count=3):
        n = max(1, min(5, int(count or 3)))
        cc = (country or '').strip()
        if cc:
            cc = cc.upper() if len(cc) == 2 and cc.isalpha() else COUNTRIES.get(cc.lower())
            if not cc:
                return {'error': 'I do not know that country: try its 2 letter code'}
        elif self.cfg.get('town'):
            try:
                cc = (self._geo(self.cfg['town']).get('country_code') or 'GB').upper()
            except Exception:
                cc = 'GB'
        else:
            cc = 'GB'
        d = _get('https://date.nager.at/api/v3/NextPublicHolidays/' + cc)
        if not d:
            return {'error': 'no holidays found'}
        return {'country': cc, 'holidays': [{'date': h['date'], 'name': h.get('localName') or h.get('name')} for h in d[:n]]}

    @_safe
    def t_time_in(self, place):
        import zoneinfo
        res = self._geo(place)
        tz = res.get('timezone')
        if not tz:
            return {'error': 'I could not work out the time zone'}
        now = datetime.datetime.now(zoneinfo.ZoneInfo(tz))
        return {'place': '%s, %s' % (res['name'], res.get('country', '')), 'time': now.strftime('%H:%M'),
                'date': now.strftime('%A %d %B'), 'timezone': tz}

    @_safe
    def t_tell_joke(self):
        d = _get('https://icanhazdadjoke.com/', headers={'Accept': 'application/json'})
        return {'joke': d['joke']}

    @_safe
    def t_where_is_the_iss(self):
        d = _get('https://api.wheretheiss.at/v1/satellites/25544')
        lat, lon = d['latitude'], d['longitude']
        out = {'latitude': round(lat, 1), 'longitude': round(lon, 1), 'altitude_km': round(d['altitude']),
               'speed_kmh': round(d['velocity'])}
        try:
            h = self._here()
            if 'error' not in h:
                out['distance_from_here_km'] = round(_haversine(h['lat'], h['lon'], lat, lon))
        except Exception:
            pass
        return out

    @_safe
    def t_people_in_space(self):
        d = _get('http://api.open-notify.org/astros.json')
        p = d['people']
        return {'count': d.get('number', len(p)), 'people': [{'name': x['name'], 'craft': x['craft']} for x in p[:5]]}

    @_safe
    def t_earthquakes(self, period='day', min_magnitude=4.5):
        per = (period or 'day').strip().lower()
        feed = 'significant_week' if per == 'significant' else '4.5_week' if per == 'week' else '4.5_day'
        d = _get('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/%s.geojson' % feed)
        mn = float(4.5 if min_magnitude is None else min_magnitude)
        q = [f['properties'] for f in d['features'] if (f['properties'].get('mag') or 0) >= mn]
        q.sort(key=lambda p: p['mag'], reverse=True)
        if not q:
            return {'count': 0, 'quakes': [], 'summary': 'No earthquakes that big in that time'}
        return {'count': len(q), 'quakes': [{'magnitude': p['mag'], 'where': p.get('place', '')} for p in q[:5]]}

    # -- local tools

    @_safe
    def t_calculate(self, expression):
        expr = str(expression or '').strip().replace('^', '**').replace('×', '*').replace('÷', '/')
        if not expr or len(expr) > 200:
            return {'error': 'give me a shorter sum'}
        try:
            r = _eval(ast.parse(expr, mode='eval'))
        except ZeroDivisionError:
            return {'error': 'cannot divide by zero'}
        except (ValueError, SyntaxError, TypeError, OverflowError, MemoryError, RecursionError):
            return {'error': 'I could not work that out'}
        if isinstance(r, float):
            if math.isnan(r) or math.isinf(r):
                return {'error': 'I could not work that out'}
            r = round(r, 10)
            if r == int(r) and abs(r) < 1e15:
                r = int(r)
        return {'expression': expr, 'result': r}

    @_safe
    def t_convert_units(self, value, from_unit, to_unit):
        v = float(value)
        f, t = _unit(from_unit), _unit(to_unit)
        if not f or not t:
            return {'error': 'I do not know the unit %s' % (from_unit if not f else to_unit)}
        kf, kt = _UNITS[f][0], _UNITS[t][0]
        if kf != kt:
            return {'error': 'cannot convert %s to %s: one is %s and the other is %s' % (f, t, kf, kt)}
        if kf == 'temp':
            r = _from_c(_to_c(v, f), t)
        else:
            r = v * _UNITS[f][1] / _UNITS[t][1]
        return {'value': v, 'from': f, 'to': t, 'result': round(r, 3)}

    @_safe
    def t_countdown_to(self, date):
        try:
            month, day, year = _month_day(str(date))
        except ValueError:
            return {'error': 'I did not understand that date'}
        today = datetime.date.today()
        try:
            if year:
                target = datetime.date(year, month, day)
            else:
                target = datetime.date(today.year, month, day)
                if target < today:
                    target = datetime.date(today.year + 1, month, day)
        except ValueError:
            return {'error': 'that date does not exist'}
        days = (target - today).days
        return {'date': target.strftime('%A %d %B %Y'), 'days': days,
                'summary': 'today' if days == 0 else '%d day%s %s' % (abs(days), '' if abs(days) == 1 else 's', 'to go' if days > 0 else 'ago')}

    @_safe
    def t_flip_coin(self):
        return {'result': random.choice(['heads', 'tails'])}

    @_safe
    def t_roll_dice(self, sides=6, count=1):
        s, c = max(2, min(1000, int(sides or 6))), max(1, min(20, int(count or 1)))
        rolls = [random.randint(1, s) for _ in range(c)]
        return {'sides': s, 'rolls': rolls, 'total': sum(rolls)}

    @_safe
    def t_random_number(self, low=1, high=100):
        lo, hi = int(1 if low is None else low), int(100 if high is None else high)
        if lo > hi:
            lo, hi = hi, lo
        return {'number': random.randint(lo, hi), 'low': lo, 'high': hi}

    @_safe
    def t_pick_one(self, options):
        opts = [o.strip() for o in str(options or '').split(',') if o.strip()]
        if not opts:
            return {'error': 'what are the options?'}
        return {'choice': random.choice(opts)}

    @_safe
    def t_spell_word(self, word):
        w = re.sub(r'\s+', '', str(word or ''))
        if not w:
            return {'error': 'which word?'}
        return {'word': w, 'spelled': ' '.join(w.upper()), 'letters': len(w)}
