import random
import pytest
from coach.board import Board, INITIAL_FEN, parse_move


def test_initial_position():
    b = Board.initial()
    assert b.fen("red") == INITIAL_FEN
    assert len(b.legal_moves("red")) == 44 and len(b.legal_moves("black")) == 44
    assert b.validate() == []


def test_parse_move():
    assert parse_move("a0i9") == ((0, 9), (8, 0))
    for bad in ("j0a1", "a0a0", "none", "a10b2"):
        with pytest.raises(ValueError): parse_move(bad)


@pytest.mark.parametrize("move,text", [
    ("h2e2", "炮二平五"), ("b0c2", "马八进七"), ("h9g7", "马８进７"), ("a0a1", "车九进一"),
    ("c3c4", "兵七进一"), ("g6g5", "卒７进１"), ("b7e7", "炮２平５"), ("f0e1", "仕四进五"), ("g0e2", "相三进五"),
])
def test_notation(move, text):
    assert Board.initial().notation(move) == text


def test_notation_front_back_and_retreat():
    b = Board.from_fen("4k4/9/9/9/9/9/4P4/4P4/4R4/3K5 w")
    assert b.notation("e3e4") == "前兵进一"
    assert b.notation("e1h1") == "车五平二"
    b = Board.from_fen("4k4/9/9/9/4R4/9/9/9/9/3K5 w")
    assert b.notation("e5e2") == "车五退三"


def test_rules():
    b = Board.from_fen("4k4/9/9/9/9/9/9/9/4R4/3K5 w")
    assert "e1e8" in b.legal_moves("red") and "e1e9" not in b.legal_moves("red")   # never "capture" a king
    b = Board.from_fen("3k5/9/9/9/9/9/9/9/9/4K4 w")
    assert "e0d0" not in b.legal_moves("red")
    b = Board.from_fen("3k5/9/9/9/9/9/9/2n6/9/4K4 w")
    assert b.in_check("red") is False
    b = Board.from_fen("3k5/9/9/9/9/9/9/3n5/9/4K4 w")
    assert b.in_check("red")


def test_random_games_stay_legal():
    rng = random.Random(3)
    for _ in range(5):
        b = Board.initial(); turn = "red"
        for _ in range(80):
            moves = b.legal_moves(turn)
            if not moves: break
            b = b.apply(rng.choice(moves)); turn = "black" if turn == "red" else "red"
            assert b.king("red") and b.king("black")
            assert not b.in_check("black" if turn == "red" else "red")
