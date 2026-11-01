"""The chess camera: a webcam over a real chess board reads the user's moves, so they can play the engine on a real
board without saying every move. OFF unless the setting chess_camera is set to a camera (e.g. /dev/video0, or 0).

Everything happens on the Pi and nothing is sent anywhere. No picture is ever saved: each look grabs one still,
warps the board flat, and keeps only small numbers per square (a 256x256 grey-ish reference of the last position,
and, if trained, a few numbers per square per example).

  calibrate  once, with the camera fixed: finds the board's four corners (an empty board is found by itself; with
             pieces on it, give the corners by hand as percentages of the picture), then fine-tunes them.
  see move   compares the board with the last look; the squares that changed, checked against the game's legal
             moves, say which move was played (so a shadow cannot invent an illegal move).
  train      optional: each "train" labels the squares with what the game says is on them, and from about five
             positions on the reader recognises empty / white / black squares by itself (chess_look).

Needs OpenCV and numpy (sudo apt install python3-opencv, or pip install opencv-python-headless numpy).
"""
import json
import os
import time

from . import chessgame, config

CALIB = os.path.join(config.STATE, 'chess_board_calib.json')
REF = os.path.join(config.STATE, 'chess_board_ref.npy')
TRAIN = os.path.join(config.STATE, 'chess_train.npz')
N = 256                      # the flat board is N x N pixels, each square N/8
MIN_ROWS = 300               # about five trained positions
MAX_ROWS = 6000

DECLARATIONS = [
    {'name': 'chess_calibrate_board', 'description': 'Set up the chess camera on the real board (once, with the camera fixed). '
     'Finds an empty board by itself; with pieces on it, give the four corners. rotate turns the result a quarter turn at a time '
     'if white ends up on the wrong side.',
     'parameters': {'type': 'OBJECT', 'properties': {
         'corners': {'type': 'STRING', 'description': 'optional: a1, h1, h8, a8 corners as x,y percentages of the picture, e.g. "20,80 80,80 80,20 20,20"'},
         'rotate': {'type': 'NUMBER', 'description': 'optional: quarter turns, 0-3'}}}},
    {'name': 'chess_see_move', 'description': 'Read the move the user just made on the real chess board through the camera and '
     'play it in the game (then say the engine\'s reply). Use when the user says "my move is done" / "your turn".',
     'parameters': {'type': 'OBJECT', 'properties': {}}},
    {'name': 'chess_look', 'description': 'Check the real board against the game through the camera: which squares look different '
     'from what the game says. Needs training first (chess_train).',
     'parameters': {'type': 'OBJECT', 'properties': {}}},
    {'name': 'chess_train', 'description': 'Teach the chess camera what the pieces look like: action add (the board on the table '
     'matches the game right now), status, or reset.',
     'parameters': {'type': 'OBJECT', 'properties': {'action': {'type': 'STRING', 'description': 'add, status or reset'}}}},
]


def _cv():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError:
        raise RuntimeError('the chess camera needs OpenCV: sudo apt install python3-opencv')


def enabled(cfg):
    return bool(str(cfg.get('chess_camera') or '').strip())


def grab(device):
    """One still from the camera, opened only for this look and closed straight after."""
    cv2, _np = _cv()
    dev = int(device) if str(device).isdigit() else str(device)
    cap = cv2.VideoCapture(dev)
    try:
        if not cap.isOpened():
            raise RuntimeError('cannot open the chess camera %s' % device)
        img = None
        for _ in range(5):                   # the first frames are often dark while exposure settles
            ok, frame = cap.read()
            if ok:
                img = frame
        if img is None:
            raise RuntimeError('the chess camera gave no picture')
        return img
    finally:
        cap.release()


def load_calib():
    try:
        with open(CALIB) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_calib(corners, w, h):
    """corners: [[x, y] a1, h1, h8, a8] in picture pixels."""
    os.makedirs(os.path.dirname(CALIB), exist_ok=True)
    with open(CALIB + '.tmp', 'w') as f:
        json.dump({'corners': corners, 'size': [w, h], 'at': time.time()}, f)
    os.replace(CALIB + '.tmp', CALIB)


def _matrix(img, calib):
    cv2, np = _cv()
    h, w = img.shape[:2]
    sw, sh = calib['size']
    src = np.array([[x * w / float(sw), y * h / float(sh)] for x, y in calib['corners']], dtype=np.float32)
    dst = np.array([[0, N], [N, N], [N, 0], [0, 0]], dtype=np.float32)       # a1 bottom-left, h1, h8, a8 clockwise
    return cv2.getPerspectiveTransform(src, dst)


def flat(img, calib):
    """The board from straight above, a1 bottom-left, blurred, in Lab colour as floats."""
    cv2, np = _cv()
    out = cv2.warpPerspective(img, _matrix(img, calib), (N, N))
    out = cv2.GaussianBlur(out, (5, 5), 0)
    return cv2.cvtColor(out, cv2.COLOR_BGR2LAB).astype(np.float32)


def _texture(lab):
    """Edge strength of the lightness: a piece on a square of a similar colour still has an outline."""
    cv2, np = _cv()
    gx = cv2.Sobel(lab[:, :, 0], cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lab[:, :, 0], cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


def square_diffs(ref, cur):
    """8x8, [rank][file]: how different each square's middle looks (the middle only: edges move with perspective)."""
    _cv2, np = _cv()
    s = N // 8
    d = np.zeros((8, 8), dtype=np.float32)
    shift = np.median((cur - ref).reshape(-1, 3), axis=0)           # a lighting change shifts every square alike
    tr, tc = _texture(ref), _texture(cur)
    for r in range(8):
        for f in range(8):
            y0, x0 = (7 - r) * s, f * s
            sl = (slice(y0 + 8, y0 + s - 8), slice(x0 + 8, x0 + s - 8))
            d[r, f] = float(np.mean(np.abs(ref[sl] - (cur[sl] - shift)))) + 0.6 * float(abs(np.mean(tr[sl]) - np.mean(tc[sl])))
    return d


def expected_changes(board, move):
    """Squares a physical move changes: from, to, the rook's two for castling, the taken pawn for en passant."""
    import chess
    sq = {move.from_square, move.to_square}
    if board.is_castling(move):
        rank = chess.square_rank(move.from_square)
        if chess.square_file(move.to_square) > chess.square_file(move.from_square):
            sq |= {chess.square(7, rank), chess.square(5, rank)}
        else:
            sq |= {chess.square(0, rank), chess.square(3, rank)}
    if board.is_en_passant(move):
        sq.add(chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square)))
    return sq


def pick_move(board, prev_move, d):
    """Which legal move do the changed squares show? prev_move: the engine's reply, moved on the real board by the user
    since the reference was taken (or None). Returns (uci, confidence 0-1) or (None, why)."""
    import chess
    mx = float(d.max())
    if mx < 6.0:
        return None, 'nothing seems to have moved'
    thr = max(6.0, 0.22 * mx)
    changed = {chess.square(f, r) for r in range(8) for f in range(8) if d[r, f] > thr}
    base = set()
    if prev_move is not None:
        pb = board.copy()
        pb.pop()
        base = expected_changes(pb, prev_move)
    scored = []
    for mv in board.legal_moves:
        mine = expected_changes(board, mv)
        exp = base | mine
        optional = base & mine          # touched by both moves: may end up looking unchanged
        required = exp - optional
        score = len(changed & exp) - 0.8 * len(changed - exp) - 1.0 * len(required - changed)
        scored.append((score, mv.uci(), len(required)))
    if not scored:
        return None, 'there are no legal moves'
    scored.sort(reverse=True)
    best = scored[0]
    second = scored[1] if len(scored) > 1 else (-99, '', 0)
    if best[0] < best[2] * 0.6 or best[0] - second[0] < 0.9:
        return None, 'unsure which move it was'
    return best[1], min(1.0, (best[0] - second[0]) / 3.0)


def stable_flat(device, calib, tries=6, gap=0.35):
    """The board once nothing is moving: two looks a moment apart must agree (a hand over the board does not)."""
    prev = None
    for _ in range(tries):
        cur = flat(grab(device), calib)
        if prev is not None and float(square_diffs(prev, cur).max()) < 9.0:
            return cur
        prev = cur
        time.sleep(gap)
    return prev


def checker_score(f):
    """0..1: how much the flat picture looks like a chessboard, from the corners of every square (which stay free of
    pieces, so it works mid-game). Near 1 means the corners are right."""
    _cv2, np = _cv()
    s = N // 8
    vals, par = [], []
    for r in range(8):
        for fl in range(8):
            y0, x0 = (7 - r) * s, fl * s
            c = [f[y0 + 2:y0 + 7, x0 + 2:x0 + 7, 0], f[y0 + 2:y0 + 7, x0 + s - 7:x0 + s - 2, 0],
                 f[y0 + s - 7:y0 + s - 2, x0 + 2:x0 + 7, 0], f[y0 + s - 7:y0 + s - 2, x0 + s - 7:x0 + s - 2, 0]]
            vals.append(float(np.mean([np.mean(x) for x in c])))
            par.append(1.0 if (r + fl) % 2 == 0 else -1.0)
    ys = np.array(vals) - np.mean(vals)
    if ys.std() < 1e-6:
        return 0.0
    return abs(float(np.corrcoef(np.array(par), ys)[0, 1]))


def refine_corners(img, corners, rounds=4):
    """Nudge each corner a little at a time while the board looks more like a chessboard. Returns (corners, score)."""
    h, w = img.shape[:2]
    size = [w, h]
    cur = [list(map(float, c)) for c in corners]
    best = checker_score(flat(img, {'corners': cur, 'size': size}))
    step = max(w, h) * 0.02
    for _ in range(rounds):
        for ci in range(4):
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                trial = [c[:] for c in cur]
                trial[ci][0] += dx * step
                trial[ci][1] += dy * step
                sc = checker_score(flat(img, {'corners': trial, 'size': size}))
                if sc > best + 1e-4:
                    best, cur = sc, trial
        step *= 0.55
    return cur, best


def find_board(img):
    """An empty board's four outer corners [a1, h1, h8, a8] from OpenCV's chessboard finder (7x7 inner corners), or None.
    Which corner is a1 is a guess (the one nearest the bottom-left of the picture); rotate fixes it."""
    cv2, np = _cv()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ok, pts = cv2.findChessboardCornersSB(gray, (7, 7))
    if not ok:
        return None
    pts = pts.reshape(-1, 2).astype(np.float32)
    grid = np.array([[i + 1, j + 1] for j in range(7) for i in range(7)], dtype=np.float32)
    H, _m = cv2.findHomography(grid, pts)
    outer = cv2.perspectiveTransform(np.array([[[0, 0], [8, 0], [8, 8], [0, 8]]], dtype=np.float32), H)[0]
    h = img.shape[0]
    start = int(np.argmin([x - (y - h) for x, y in outer]))           # nearest the bottom-left
    ring = [outer[(start + i) % 4] for i in range(4)]
    # keep the order going round the board the same way as a1 -> h1 -> h8 -> a8 on screen (h1 to the right of a1)
    if ring[1][0] < ring[3][0]:
        ring = [ring[0], ring[3], ring[2], ring[1]]
    return [[float(x), float(y)] for x, y in ring]


def parse_corners(text, w, h):
    nums = [float(x) for x in text.replace(',', ' ').split()]
    if len(nums) != 8 or not all(0 <= v <= 100 for v in nums):
        raise ValueError('give four corners as x,y percentages: a1, h1, h8, a8')
    return [[nums[i] * w / 100.0, nums[i + 1] * h / 100.0] for i in range(0, 8, 2)]


def save_ref(f):
    _cv2, np = _cv()
    np.save(REF, f.astype(np.float16))


def load_ref():
    _cv2, np = _cv()
    try:
        return np.load(REF).astype(np.float32)
    except (OSError, ValueError):
        return None


# ---- the trained square reader: a nearest-neighbour vote over labelled squares (empty / white / black) -------------

def square_features(f):
    """(64, 110): rows a1, b1 ... h8. A 6x6 colour thumbnail of each square's middle, its outline strength and its
    colour on the board; a lighting shift over the whole board is taken out."""
    cv2, np = _cv()
    s = N // 8
    shift = np.median(f.reshape(-1, 3), axis=0)
    tex = _texture(f)
    out = np.zeros((64, 6 * 6 * 3 + 2), dtype=np.float32)
    for r in range(8):
        for fl in range(8):
            y0, x0 = (7 - r) * s, fl * s
            small = cv2.resize(f[y0 + 6:y0 + s - 6, x0 + 6:x0 + s - 6] - shift, (6, 6), interpolation=cv2.INTER_AREA).reshape(-1)
            t = tex[y0 + 6:y0 + s - 6, x0 + 6:x0 + s - 6]
            out[r * 8 + fl] = np.concatenate([small, [float(np.mean(t)), 60.0 * ((r + fl) % 2)]])
    return out


def _load_train():
    _cv2, np = _cv()
    try:
        d = np.load(TRAIN)
        return d['X'], d['y']
    except (OSError, ValueError, KeyError):
        return None, None


def train_rows():
    X, _y = _load_train()
    return 0 if X is None else len(X)


def labels_of(board):
    import chess
    return [0 if board.piece_at(q) is None else (1 if board.piece_at(q).color else 2) for q in chess.SQUARES]


def add_sample(f, board):
    _cv2, np = _cv()
    X, y = _load_train()
    feats, labels = square_features(f), np.array(labels_of(board), dtype=np.uint8)
    X = feats if X is None else np.vstack([X, feats])
    y = labels if y is None else np.concatenate([y, labels])
    if len(X) > MAX_ROWS:
        keep = np.random.default_rng(1).choice(len(X), MAX_ROWS, replace=False)
        X, y = X[keep], y[keep]
    np.savez(TRAIN + '.tmp.npz', X=X.astype(np.float32), y=y)
    os.replace(TRAIN + '.tmp.npz', TRAIN)
    return len(X)


def classify(f, k=5):
    """Per square (label 0 empty / 1 white / 2 black, confidence 0..1), or None while untrained."""
    _cv2, np = _cv()
    X, y = _load_train()
    if X is None or len(X) < MIN_ROWS:
        return None
    q = square_features(f)
    d = ((q[:, None, :] - X[None, :, :]) ** 2).sum(axis=2)
    idx = np.argsort(d, axis=1)[:, :k]
    out = []
    for i in range(64):
        votes = np.bincount(y[idx[i]], minlength=3).astype(float)
        lab = int(np.argmax(votes))
        out.append((lab, float(votes[lab] / votes.sum())))
    return out


def pick_move_trained(board, cls):
    """The legal move whose resulting board best matches what the trained reader sees: (uci, confidence) or (None, why)."""
    def cost(b):
        want = labels_of(b)
        return sum(c for q, (lab, c) in enumerate(cls) if lab != want[q])
    scored = []
    for mv in board.legal_moves:
        b2 = board.copy()
        b2.push(mv)
        scored.append((cost(b2), mv.uci()))
    if not scored:
        return None, 'there are no legal moves'
    scored.sort()
    best, second = scored[0], (scored[1] if len(scored) > 1 else (99.0, ''))
    if cost(board) <= best[0] + 0.5:
        return None, 'nothing seems to have moved'
    if best[0] > 2.5 or second[0] - best[0] < 0.9:
        return None, 'unsure which move it was'
    return best[1], min(1.0, (second[0] - best[0]) / 3.0)


class ChessCamTools:
    def _cam(self):
        if not enabled(self.cfg):
            raise RuntimeError('the chess camera is off: set chess_camera in the settings (see docs/CHESS.md)')
        return str(self.cfg.get('chess_camera')).strip()

    def t_chess_calibrate_board(self, corners='', rotate=0):
        dev = self._cam()
        img = grab(dev)
        h, w = img.shape[:2]
        cs = parse_corners(corners, w, h) if str(corners or '').strip() else find_board(img)
        if not cs:
            return {'error': 'I could not find the board by myself: clear the pieces off, or give the four corners'}
        r = int(float(rotate or 0)) % 4
        cs = cs[r:] + cs[:r]
        cs, score = refine_corners(img, cs)
        if score < 0.35:
            return {'error': 'that does not look like a chessboard (score %.2f): check the camera and the corners' % score}
        save_calib(cs, w, h)
        save_ref(flat(img, load_calib()))
        return {'ok': True, 'score': round(score, 2), 'say': 'The board camera is set up.'}

    def t_chess_see_move(self):
        dev = self._cam()
        calib = load_calib()
        if not calib:
            return {'error': 'the board camera is not set up yet: calibrate it first'}
        g = chessgame.load()
        if not g:
            return {'error': 'no game is going'}
        board = chessgame.board_of(g)
        cur = stable_flat(dev, calib)
        cls = classify(cur)
        if cls:
            uci, how = pick_move_trained(board, cls)
        else:
            ref = load_ref()
            if ref is None:
                save_ref(cur)
                return {'error': 'I had no earlier look at the board: make the move again after this, or say it'}
            prev = board.peek() if board.move_stack and board.turn == (g.get('colour') == 'white') else None
            uci, how = pick_move(board, prev, square_diffs(ref, cur))
        if not uci:
            return {'error': how, 'say': 'I could not read the move (%s): please say it.' % how}
        out = chessgame.play(uci)
        if out.get('ok'):
            save_ref(cur)            # the next look compares with this one (plus the engine's reply, moved by hand)
        out['read'] = uci
        return out

    def t_chess_look(self):
        dev = self._cam()
        calib = load_calib()
        g = chessgame.load()
        if not calib or not g:
            return {'error': 'needs the board camera set up and a game going'}
        cls = classify(stable_flat(dev, calib))
        if not cls:
            return {'error': 'the camera reader is not trained yet: use chess_train a few times'}
        import chess
        want = labels_of(chessgame.board_of(g))
        names = ['empty', 'white', 'black']
        diff = ['%s looks %s, should be %s' % (chess.square_name(q), names[lab], names[want[q]])
                for q, (lab, _c) in enumerate(cls) if lab != want[q]]
        return {'ok': True, 'matches': not diff, 'differences': diff[:10]}

    def t_chess_train(self, action='status'):
        a = str(action or 'status').lower()
        if a == 'reset':
            for p in (TRAIN, REF):
                try:
                    os.remove(p)
                except OSError:
                    pass
            return {'ok': True, 'say': 'Training forgotten.'}
        if a == 'add':
            dev = self._cam()
            calib = load_calib()
            g = chessgame.load()
            if not calib or not g:
                return {'error': 'needs the board camera set up and a game going'}
            n = add_sample(stable_flat(dev, calib), chessgame.board_of(g))
            return {'ok': True, 'examples': n, 'ready': n >= MIN_ROWS}
        n = train_rows()
        return {'examples': n, 'ready': n >= MIN_ROWS, 'positions_needed': max(0, (MIN_ROWS - n + 63) // 64)}
