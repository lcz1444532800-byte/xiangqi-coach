"""How the suggestion is picked among the engine's top lines (playing style).

- never repeat an earlier position when a reasonable alternative exists
  (long chase / perpetual repetition is penalised under xiangqi rules);
- unless clearly winning, avoid lines that start with a trade (兑子);
- when clearly winning, finish fast: prefer forcing moves and trades, always
  play the quickest mate.
"""
from .board import parse_move, other

WINNING = 300          # centipawns: clearly ahead -> simplify and finish
STYLE_MARGIN = 40      # what a preferred move may cost compared with the best
REPEAT_MARGIN = 80     # what avoiding a repeated position may cost


def position_key(board, turn):
    return board.fen(turn).split()[0] + turn[0]


def _captures(board, move):
    (_, _), (a, b) = parse_move(move)
    return board.cells[b][a] is not None


def is_trade(board, pv):
    """The line starts with an exchange: capture + recapture on that point,
    or a piece put en prise, taken and taken back."""
    try:
        if len(pv) < 2: return False
        m0, m1 = pv[0], pv[1]; b1 = board.apply(m0)
        if _captures(board, m0) and m1[2:] == m0[2:] and _captures(b1, m1): return True
        if len(pv) >= 3 and m1[2:] == m0[2:] and _captures(b1, m1):
            b2 = b1.apply(m1)
            return pv[2][2:] == m0[2:] and _captures(b2, pv[2])
    except (ValueError, AttributeError, TypeError):
        pass
    return False


def is_forcing(board, turn, move):
    return _captures(board, move) or board.apply(move).in_check(other(turn))


def choose(lines, board, turn, seen=(), variety=0, rng=None):
    """lines: [(move, score, pv)] best first, scores from the mover's view."""
    lines = [l for l in lines if board.legal_move(l[0], turn)]
    if not lines: return None
    best = lines[0][1]
    if best >= 90000: return lines[0][0]                          # mate found: the quickest one
    fresh = [l for l in lines if position_key(board.apply(l[0]), other(turn)) not in seen]
    pool = [l for l in fresh if l[1] >= best - REPEAT_MARGIN] or lines
    top = pool[0][1]
    near = [l for l in pool if l[1] >= top - max(STYLE_MARGIN, variety)]
    if top >= WINNING:
        quick = [l for l in near if is_forcing(board, turn, l[0]) or is_trade(board, l[2])]
        return (quick or near)[0][0]
    calm = [l for l in near if not is_trade(board, l[2])]
    if calm: near = calm
    if variety and rng is not None:
        from .engine import pick_varied
        symmetric = all(row == row[::-1] for row in board.cells)
        return pick_varied(near, rng, margin=variety, symmetric=symmetric) or near[0][0]
    return near[0][0]
