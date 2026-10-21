"""Board model, legal move generation and Chinese move notation.

Canonical coordinates: cells[row][col], row 0 = black home rank (top when red
is at the bottom), col 0 = file "a". UCI squares: file a..i, rank 0 = red home.
"""
from dataclasses import dataclass, field
from collections import Counter

INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
NAMES = dict(zip("KABNRCPkabnrcp", "帅仕相马车炮兵将士象马车炮卒"))
LIMITS = {"k": 1, "a": 2, "b": 2, "n": 2, "r": 2, "c": 2, "p": 5}
RED_DIGITS = "一二三四五六七八九"
BLACK_DIGITS = "１２３４５６７８９"


def color(piece):
    return "red" if piece.isupper() else "black"


def other(side):
    return "black" if side == "red" else "red"


def square(col, row):
    return "abcdefghi"[col] + str(9 - row)


def parse_move(move):
    if not (isinstance(move, str) and len(move) == 4 and move[0] in "abcdefghi" and move[2] in "abcdefghi"
            and move[1].isdigit() and move[3].isdigit()):
        raise ValueError(f"无效着法：{move}")
    a = (ord(move[0]) - 97, 9 - int(move[1]))
    b = (ord(move[2]) - 97, 9 - int(move[3]))
    if a == b:
        raise ValueError("着法起终点相同")
    return a, b


def in_palace(col, row, red):
    return 3 <= col <= 5 and (7 <= row <= 9 if red else 0 <= row <= 2)


ADVISOR_POINTS = {(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)}
ELEPHANT_POINTS = {(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)}


def placement_ok(piece, col, row):
    """Static legality of a piece on a square (from that side's own view)."""
    t = piece.lower(); red = piece.isupper(); rr = 9 - row if red else row
    if t == "k": return 3 <= col <= 5 and rr <= 2
    if t == "a": return (col, rr) in ADVISOR_POINTS
    if t == "b": return (col, rr) in ELEPHANT_POINTS
    if t == "p": return rr >= 3 and (rr >= 5 or col % 2 == 0)
    return True


@dataclass
class Board:
    cells: list = field(default_factory=lambda: [[None] * 9 for _ in range(10)])

    def __post_init__(self):
        if len(self.cells) != 10 or any(len(row) != 9 for row in self.cells):
            raise ValueError("棋盘必须为 9×10")
        if any(p is not None and p not in NAMES for row in self.cells for p in row):
            raise ValueError("未知棋子")

    def copy(self):
        return Board([row[:] for row in self.cells])

    def __eq__(self, other_board):
        return isinstance(other_board, Board) and self.cells == other_board.cells

    @classmethod
    def from_fen(cls, fen):
        rows = []
        for text in fen.split()[0].split("/"):
            row = []
            for ch in text:
                if ch.isdigit(): row.extend([None] * int(ch))
                else: row.append({"h": "n", "H": "N", "e": "b", "E": "B"}.get(ch, ch))
            rows.append(row)
        return cls(rows)

    @classmethod
    def initial(cls):
        return cls.from_fen(INITIAL_FEN)

    def fen(self, turn):
        rows = []
        for row in self.cells:
            text = ""; n = 0
            for p in row:
                if p is None: n += 1
                else:
                    if n: text += str(n); n = 0
                    text += p
            if n: text += str(n)
            rows.append(text)
        return "/".join(rows) + (" w" if turn == "red" else " b") + " - - 0 1"

    def pieces(self):
        return [(c, r, p) for r, row in enumerate(self.cells) for c, p in enumerate(row) if p]

    def colors(self):
        """Occupancy + colour pattern: what the camera can see robustly."""
        return tuple(None if p is None else color(p) for row in self.cells for p in row)

    def king(self, side):
        target = "K" if side == "red" else "k"
        for c, r, p in self.pieces():
            if p == target: return (c, r)
        return None

    # ---- move generation -------------------------------------------------
    def _targets(self, x, y):
        p = self.cells[y][x]; t = p.lower(); red = p.isupper(); cells = self.cells
        out = []

        def add(a, b):
            if 0 <= a < 9 and 0 <= b < 10:
                q = cells[b][a]
                if q is None or q.isupper() != red: out.append((a, b))

        if t in "rc":
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = x + dx, y + dy; jumped = False
                while 0 <= a < 9 and 0 <= b < 10:
                    q = cells[b][a]
                    if not jumped:
                        if q is None: out.append((a, b))
                        else:
                            if t == "r":
                                if q.isupper() != red: out.append((a, b))
                                break
                            jumped = True
                    else:
                        if q is not None:
                            if q.isupper() != red: out.append((a, b))
                            break
                    a += dx; b += dy
        elif t == "n":
            for dx, dy, lx, ly in ((1, 2, 0, 1), (-1, 2, 0, 1), (1, -2, 0, -1), (-1, -2, 0, -1),
                                   (2, 1, 1, 0), (2, -1, 1, 0), (-2, 1, -1, 0), (-2, -1, -1, 0)):
                if 0 <= x + lx < 9 and 0 <= y + ly < 10 and cells[y + ly][x + lx] is None: add(x + dx, y + dy)
        elif t == "b":
            for dx, dy in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
                a, b = x + dx, y + dy
                if 0 <= a < 9 and 0 <= b < 10 and (b >= 5 if red else b <= 4) and cells[y + dy // 2][x + dx // 2] is None:
                    add(a, b)
        elif t == "a":
            for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                if in_palace(x + dx, y + dy, red): add(x + dx, y + dy)
        elif t == "k":
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if in_palace(x + dx, y + dy, red): add(x + dx, y + dy)
        elif t == "p":
            add(x, y - 1 if red else y + 1)
            if (y <= 4) if red else (y >= 5):
                add(x - 1, y); add(x + 1, y)
        return out

    def attacked(self, square_, by_side):
        """Is square attacked by by_side (including flying-general)."""
        tx, ty = square_
        for c, r, p in self.pieces():
            if color(p) != by_side: continue
            if p.lower() == "k":
                if c == tx and self.cells[ty][tx] and self.cells[ty][tx].lower() == "k":
                    lo, hi = sorted((r, ty))
                    if all(self.cells[i][c] is None for i in range(lo + 1, hi)): return True
                if abs(c - tx) + abs(r - ty) == 1 and in_palace(tx, ty, p.isupper()): return True
                continue
            if (tx, ty) in self._targets(c, r): return True
        return False

    def in_check(self, side):
        k = self.king(side)
        return k is None or self.attacked(k, other(side))

    def apply(self, move):
        (x, y), (a, b) = parse_move(move)
        new = self.copy(); new.cells[b][a] = new.cells[y][x]; new.cells[y][x] = None
        return new

    def legal_moves(self, turn):
        moves = []
        for c, r, p in self.pieces():
            if color(p) != turn: continue
            for a, b in self._targets(c, r):
                q = self.cells[b][a]
                if q and q.lower() == "k": continue
                new = self.copy(); new.cells[b][a] = p; new.cells[r][c] = None
                if not new.in_check(turn): moves.append(square(c, r) + square(a, b))
        return moves

    def legal_move(self, move, turn):
        try: return move in self.legal_moves(turn)
        except ValueError: return False

    def validate(self):
        """Basic sanity used to accept a recognised position."""
        errors = []; counts = Counter(p for _, _, p in self.pieces())
        for side in ("red", "black"):
            red = side == "red"
            if counts["K" if red else "k"] != 1: errors.append(("红" if red else "黑") + "方将帅数量错误")
            for t, n in LIMITS.items():
                if counts[t.upper() if red else t] > n: errors.append(NAMES[t] + "数量超限")
        for c, r, p in self.pieces():
            if not placement_ok(p, c, r): errors.append(NAMES[p] + "位置不合法")
        rk, bk = self.king("red"), self.king("black")
        if rk and bk and rk[0] == bk[0] and all(self.cells[i][rk[0]] is None for i in range(bk[1] + 1, rk[1])):
            errors.append("将帅照面")
        return errors

    # ---- notation --------------------------------------------------------
    def notation(self, move):
        """Chinese notation such as 炮二平五 / 马８进７ for a legal move."""
        (x, y), (a, b) = parse_move(move)
        p = self.cells[y][x]
        if p is None: return move
        red = p.isupper(); t = p.lower()
        digits = RED_DIGITS if red else BLACK_DIGITS
        file_no = lambda col: (9 - col) if red else (col + 1)
        name = NAMES[p]
        # several identical pieces on the same file -> 前/中/后
        same = sorted((r for c, r, q in self.pieces() if q == p and c == x), key=lambda r: r if red else -r)
        if len(same) >= 2:
            index = same.index(y)
            labels = ["前", "后"] if len(same) == 2 else ["前", "中", "后"] if len(same) == 3 else ["一", "二", "三", "四", "五"]
            head = labels[index] + name
        else:
            head = name + digits[file_no(x) - 1]
        forward = (b < y) if red else (b > y)
        if b == y:
            return head + "平" + digits[file_no(a) - 1]
        action = "进" if forward else "退"
        if t in "rckp":
            return head + action + digits[abs(b - y) - 1]
        return head + action + digits[file_no(a) - 1]
