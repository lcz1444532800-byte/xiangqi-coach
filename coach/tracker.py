"""Follow a game from a stream of colour/occupancy observations.

Piece identities come from the known previous position; a new frame only
has to tell which points are empty / red / black. The move (or the two
moves, when the opponent replied quickly) that turns the previous position
into the observed pattern is found among the legal moves, so the tracked
position stays exact without re-reading piece glyphs. Take-backs (悔棋) are
recognised by matching earlier positions of the game.
"""
import copy
from dataclasses import dataclass, field
from .board import Board, other
from .style import position_key

INITIAL = Board.initial()
HISTORY = 12
MAX_UNSEEN = 2          # pieces that may be momentarily undetected without re-reading the board


@dataclass
class GameState:
    board: Board
    turn: str
    base_fen: str
    moves: list = field(default_factory=list)
    exact: bool = False        # True when followed from the opening position
    history: list = field(default_factory=list)   # earlier (board, turn, n_moves)
    ply: int = 0               # half-moves since the opening (or since the position was read)
    unseen: set = field(default_factory=set)      # points whose piece is known but not detected right now
    seen: list = field(default_factory=list)      # every position of the game so far (repetition check)

    def __post_init__(self):
        if not self.seen: self.seen = [position_key(self.board, self.turn)]

    @classmethod
    def opening(cls):
        return cls(INITIAL.copy(), "red", INITIAL.fen("red"), [], True)

    @classmethod
    def from_position(cls, board, turn):
        return cls(board.copy(), turn, board.fen(turn), [], False)

    def play(self, move):
        self.history.append((self.board, self.turn, len(self.moves)))
        self.history = self.history[-HISTORY:]
        self.board = self.board.apply(move); self.moves.append(move); self.turn = other(self.turn); self.ply += 1
        self.seen.append(position_key(self.board, self.turn))

    def undo_to(self, index):
        board, turn, n = self.history[index]
        back = len(self.moves) - n; self.ply -= back
        if back: self.seen = self.seen[:-back] or self.seen[:1]
        self.history = self.history[:index]
        self.board = board; self.turn = turn; self.moves = self.moves[:n]

    def set_turn(self, turn):
        """Change the side to move; the engine's base position + move list must follow."""
        if turn == self.turn: return
        self.turn = turn; self.base_fen = self.board.fen(turn); self.moves = []; self.history = []
        self.seen.append(position_key(self.board, turn))


def occlusion(expected, observed):
    """Pieces only vanished (>= 3), nothing new appeared: something covers the board."""
    vanished = sum(e is not None and o is None for e, o in zip(expected, observed))
    other = sum(o is not None and e != o for e, o in zip(expected, observed))
    return vanished >= 3 and other <= 1


def mover(board, move):
    p = board.cells[9 - int(move[1])][ord(move[0]) - 97]
    return "red" if p.isupper() else "black"


def differs(colors, target, wild=()):
    """Points where a board's colours disagree with the observation.

    wild: points whose piece is known to be there although it is not detected
    right now; an empty reading there is not a disagreement.
    """
    return {i for i, (a, b) in enumerate(zip(colors, target)) if a != b and not (i in wild and b is None)}


def single_move(board, side, target, wild=()):
    for m in board.legal_moves(side):
        if not differs(board.apply(m).colors(), target, wild): return m
    return None


def two_moves(board, side, target, wild=()):
    diff = differs(board.colors(), target, wild)
    if not diff or len(diff) > 4: return None
    for m1 in board.legal_moves(side):
        if not (_cells(m1) & diff): continue
        b1 = board.apply(m1)
        rest = differs(b1.colors(), target, wild)
        if not rest or len(rest) > 2: continue
        for m2 in b1.legal_moves(other(side)):
            if rest <= _cells(m2) and not differs(b1.apply(m2).colors(), target, wild): return [m1, m2]
    return None


def _cells(move):
    a = (ord(move[0]) - 97) + 9 * (9 - int(move[1]))
    b = (ord(move[2]) - 97) + 9 * (9 - int(move[3]))
    return {a, b}


def advance(state, target):
    """Update state to match the observed pattern. Returns description or None."""
    target = tuple(target); wild = set(state.unseen)
    result = _advance(state, target, wild)
    if not result:
        # A move plus pieces covered by its effect (capture animation): explain the move,
        # keep the covered pieces as unseen.
        gone = {i for i, (e, o) in enumerate(zip(state.board.colors(), target)) if e is not None and o is None} - wild
        if 1 <= len(gone) <= MAX_UNSEEN + 1:
            trial = copy.deepcopy(state)
            r = _advance(trial, target, wild | gone)
            left = {i for i in wild | gone if target[i] is None and trial.board.colors()[i] is not None}
            if r in ("moved", "undo") and len(left) <= MAX_UNSEEN:
                state.__dict__.update(trial.__dict__); result = r; wild = wild | gone
    if result:   # keep only the points that are still occupied in the game but not seen
        state.unseen = {i for i in wild if target[i] is None and state.board.colors()[i] is not None}
    return result


def _advance(state, target, wild):
    if not differs(state.board.colors(), target, wild): return "same"
    if target == INITIAL.colors() and not (state.exact and not state.moves):
        fresh = GameState.opening(); state.__dict__.update(fresh.__dict__); return "opening"
    m = single_move(state.board, state.turn, target, wild)
    if m: state.play(m); return "moved"
    if state.moves and state.history:                    # a slide briefly rested on a point on its way
        last = state.moves[-1]; prev_board, prev_turn, _ = state.history[-1]
        for m in state.board.legal_moves(other(state.turn)):
            if m[:2] != last[2:]: continue
            whole = last[:2] + m[2:]
            if whole[:2] != whole[2:] and whole in prev_board.legal_moves(prev_turn) and \
                    not differs(prev_board.apply(whole).colors(), target, wild):
                state.undo_to(len(state.history) - 1); state.play(whole); return "moved"
    for i in range(len(state.history) - 1, -1, -1):     # take-back
        if not differs(state.history[i][0].colors(), target, wild):
            state.undo_to(i); return "undo"
    m = single_move(state.board, other(state.turn), target, wild)
    if m: state.set_turn(other(state.turn)); state.play(m); return "moved"
    for side in (state.turn, other(state.turn)):
        mm = two_moves(state.board, side, target, wild)
        if mm:
            state.set_turn(side)
            for x in mm: state.play(x)
            return "moved"
    return None


def _long_slide(state, move):
    (a, b) = (ord(move[0]) - 97, 9 - int(move[1])), (ord(move[2]) - 97, 9 - int(move[3]))
    piece = state.board.cells[b[1]][b[0]]
    # Any rook/cannon stop may be a point the piece is still gliding through.
    return piece is not None and piece.lower() in "rc"


class Tracker:
    """Stabilises raw observations and advances the game state."""

    def __init__(self, stable_frames=3, patience=2.5):
        self.state = None; self.stable_frames = stable_frames; self.patience = patience
        self.last = None; self.count = 0; self.unexplained_since = 0.0

    def reset(self, state, colors=None):
        self.state = state; self.last = tuple(colors) if colors else None
        self.count = self.stable_frames if colors else 0; self.unexplained_since = 0.0

    def feed(self, colors, now):
        """Returns "wait", "same", "moved", "undo", "opening", "occluded", "unseen" or "unknown"."""
        colors = tuple(colors)
        if colors != self.last:
            self.last = colors; self.count = 1
            if self.stable_frames > 1: return "wait"
        else:
            self.count += 1
        if self.count < self.stable_frames: return "wait"
        if not differs(self.state.board.colors(), colors, self.state.unseen):
            self.state.unseen = {i for i in self.state.unseen if colors[i] is None}
            self.unexplained_since = 0.0; return "same"
        trial = copy.deepcopy(self.state)
        result = advance(trial, colors)
        # A gliding rook/cannon may pause on a point: confirm its moves one frame longer.
        if result == "moved" and self.count < self.stable_frames + 1:
            old = self.state.moves; keep = 0
            while keep < min(len(old), len(trial.moves)) and old[keep] == trial.moves[keep]: keep += 1
            if any(_long_slide(trial, m) for m in trial.moves[keep:]): return "wait"
        if result:
            self.state = trial
            self.unexplained_since = 0.0
            return result
        if occlusion(self.state.board.colors(), colors):
            self.unexplained_since = 0.0; return "occluded"     # pop-up / menu over the board: hold
        expected = self.state.board.colors()
        gone = {i for i in differs(expected, colors, self.state.unseen)}
        if gone and len(gone | self.state.unseen) <= MAX_UNSEEN and all(colors[i] is None for i in gone):
            # No legal move only removes a piece: it is hidden or missed, not gone.
            self.state.unseen |= gone; self.unexplained_since = 0.0; return "unseen"
        if not self.unexplained_since: self.unexplained_since = now
        # Give animations, drags and pop-ups time to settle before re-reading.
        return "unknown" if now - self.unexplained_since >= self.patience else "wait"
