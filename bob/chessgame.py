"""Chess by voice against Stockfish on the Pi itself: nothing leaves the Pi. The user says moves as squares ("e2 to
e4", "g1 f3", "e7 e8 queen"); Kevin checks they are legal, plays the engine's reply and says it in standard notation.

Needs python-chess (requirements.txt) and the stockfish program (the installer puts it in). The game is kept in the
state folder (chess.json), so it survives a restart.
"""
import json
import os
import re
import shutil
import threading

from . import config

GAME = os.path.join(config.STATE, 'chess.json')
_lock = threading.RLock()

DECLARATIONS = [
    {'name': 'chess_new', 'description': 'Start a game of chess against the Pi\'s own engine. The user plays white unless they say black.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'colour': {'type': 'STRING', 'description': 'white (default) or black, for the user'},
         'elo': {'type': 'NUMBER', 'description': 'engine strength, 400 (beginner) to 3190, default 1200'}}}},
    {'name': 'chess_move', 'description': 'The user\'s chess move as two squares ("e2e4", "g1 to f3"; add queen/knight for a '
     'promotion). Checks it is legal, plays it, and answers with the engine\'s move: say that move out loud.',
     'parameters': {'type': 'OBJECT', 'properties': {'move': {'type': 'STRING', 'description': 'from-square and to-square'}}, 'required': ['move']}},
    {'name': 'chess_board', 'description': 'Where every piece is in the chess game now, whose turn it is, and the moves so far.',
     'parameters': {'type': 'OBJECT', 'properties': {}}},
    {'name': 'chess_undo', 'description': 'Take back the user\'s last chess move (and the engine\'s reply).',
     'parameters': {'type': 'OBJECT', 'properties': {}}},
    {'name': 'chess_hint', 'description': 'A good move for the user in the chess game now, without playing it.',
     'parameters': {'type': 'OBJECT', 'properties': {}}},
    {'name': 'chess_set_elo', 'description': 'Change the chess engine\'s strength (400-3190) for "play stronger / weaker".',
     'parameters': {'type': 'OBJECT', 'properties': {'elo': {'type': 'NUMBER', 'description': 'rating 400-3190'}}, 'required': ['elo']}},
]


def _chess():
    try:
        import chess
        import chess.engine
        return chess
    except ImportError:
        raise RuntimeError('python-chess is not installed: run the installer again')


def normalise_move(text):
    """'e2 to e4', 'E2-E4', 'e7 e8 queen' -> 'e2e4' / 'e7e8q'; None if it is not two squares."""
    t = str(text or '').lower()
    promo = ''
    for word, letter in (('queen', 'q'), ('rook', 'r'), ('bishop', 'b'), ('knight', 'n')):
        if word in t:
            promo = letter
    sq = re.findall(r'[a-h]\s*[1-8]', t)
    if len(sq) < 2:
        return None
    m = re.search(r'[a-h][1-8][a-h][1-8]([qrbn])', re.sub(r'[^a-h1-8qrbn]', '', t))
    return sq[0].replace(' ', '') + sq[1].replace(' ', '') + (promo or (m.group(1) if m else ''))


def load():
    try:
        with open(GAME) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(g):
    os.makedirs(os.path.dirname(GAME), exist_ok=True)
    with open(GAME + '.tmp', 'w') as f:
        json.dump(g, f)
    os.replace(GAME + '.tmp', GAME)


def board_of(g):
    chess = _chess()
    b = chess.Board()
    for m in g.get('moves', []):
        b.push_uci(m)
    return b


def stockfish():
    return shutil.which('stockfish') or ('/usr/games/stockfish' if os.path.exists('/usr/games/stockfish') else None)


def engine_move(board, elo=1200, seconds=0.5, full=False):
    """The engine's move for this position, limited to about elo (Stockfish's Skill Level stands in below 1320)."""
    chess = _chess()
    path = stockfish()
    if not path:
        raise RuntimeError('the chess engine (stockfish) is not installed: run the installer again')
    eng = chess.engine.SimpleEngine.popen_uci(path)
    try:
        elo = max(400, min(3190, int(elo)))
        if full:
            pass                             # Stockfish's own default: full strength
        elif elo < 1320:
            eng.configure({'Skill Level': round((elo - 400) / 920.0 * 8)})
        else:
            eng.configure({'UCI_LimitStrength': True, 'UCI_Elo': elo})
        return eng.play(board, chess.engine.Limit(time=seconds)).move
    finally:
        eng.quit()


def status_of(board, g):
    chess = _chess()
    out = {'turn': 'white' if board.turn == chess.WHITE else 'black', 'moves': len(board.move_stack),
           'you_are': g.get('colour', 'white'), 'fen': board.fen()}
    if board.is_check():
        out['check'] = True
    if board.is_game_over():
        res = board.result()
        out['game_over'] = {'1-0': 'white wins', '0-1': 'black wins'}.get(res, 'a draw')
        if board.is_checkmate():
            out['game_over'] += ' by checkmate'
    return out


def pieces(board):
    """'White: Ke1 Qd1 ...; Black: ...', so the user can check it against the real board."""
    chess = _chess()
    side = {True: [], False: []}
    for sq, p in sorted(board.piece_map().items(), key=lambda kv: (-kv[1].piece_type, kv[0])):
        side[p.color].append((p.symbol().upper() if p.piece_type != chess.PAWN else '') + chess.square_name(sq))
    return 'White: %s. Black: %s.' % (' '.join(side[True]), ' '.join(side[False]))


def new_game(colour='white', elo=1200):
    with _lock:
        chess = _chess()
        col = 'black' if str(colour or '').lower().startswith('b') else 'white'
        g = {'colour': col, 'elo': int(max(400, min(3190, float(elo or 1200)))), 'moves': []}
        out = {'ok': True, 'you_are': col, 'elo': g['elo']}
        if col == 'black':
            b = chess.Board()
            mv = engine_move(b, g['elo'])
            out['engine_move'] = b.san(mv)
            g['moves'].append(mv.uci())
        save(g)
        return out


def play(move):
    """The user's move, then the engine's reply."""
    with _lock:
        chess = _chess()
        g = load()
        if not g:
            return {'error': 'no game is going: start one first'}
        b = board_of(g)
        if b.is_game_over():
            return dict(status_of(b, g), error='the game is over')
        uci = normalise_move(move)
        if not uci:
            return {'error': 'say the move as two squares, like e2 to e4'}
        try:
            mv = chess.Move.from_uci(uci)
        except ValueError:
            return {'error': 'that is not a move'}
        if mv not in b.legal_moves and len(uci) == 4:
            q = chess.Move.from_uci(uci + 'q')          # a pawn reaching the end becomes a queen unless told otherwise
            mv = q if q in b.legal_moves else mv
        if mv not in b.legal_moves:
            return {'error': '%s is not a legal move here' % uci, 'turn': 'white' if b.turn else 'black'}
        out = {'ok': True, 'your_move': b.san(mv)}
        b.push(mv)
        g['moves'].append(mv.uci())
        if not b.is_game_over():
            reply = engine_move(b, g.get('elo', 1200))
            out['engine_move'] = b.san(reply)
            b.push(reply)
            g['moves'].append(reply.uci())
        save(g)
        out.update(status_of(b, g))
        return out


def undo():
    with _lock:
        g = load()
        if not g or not g.get('moves'):
            return {'error': 'there is nothing to take back'}
        b = board_of(g)
        mine = (b.turn == (g.get('colour') == 'white'))       # the user's turn: the engine replied, take back two
        n = 2 if mine and len(g['moves']) >= 2 else 1
        del g['moves'][-n:]
        save(g)
        return dict(status_of(board_of(g), g), ok=True, took_back=n)


def hint():
    g = load()
    if not g:
        return {'error': 'no game is going'}
    b = board_of(g)
    if b.is_game_over():
        return {'error': 'the game is over'}
    mv = engine_move(b, 3190, 0.8, full=True)
    return {'hint': b.san(mv), 'uci': mv.uci()}


class ChessTools:
    def t_chess_new(self, colour='white', elo=1200):
        return new_game(colour, elo)

    def t_chess_move(self, move):
        return play(move)

    def t_chess_board(self):
        g = load()
        if not g:
            return {'error': 'no game is going'}
        b = board_of(g)
        return dict(status_of(b, g), pieces=pieces(b), elo=g.get('elo'))

    def t_chess_undo(self):
        return undo()

    def t_chess_hint(self):
        return hint()

    def t_chess_set_elo(self, elo):
        g = load()
        if not g:
            return {'error': 'no game is going'}
        g['elo'] = int(max(400, min(3190, float(elo))))
        save(g)
        return {'ok': True, 'elo': g['elo']}
