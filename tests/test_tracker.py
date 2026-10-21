import random
from coach.board import Board
from coach.tracker import Tracker, GameState, advance


def random_game(seed, plies):
    rng = random.Random(seed); b = Board.initial(); turn = "red"; out = []
    for _ in range(plies):
        moves = b.legal_moves(turn)
        if not moves: break
        m = rng.choice(moves); out.append(m); b = b.apply(m); turn = "black" if turn == "red" else "red"
    return out


def test_follows_every_move_exactly():
    for seed in range(4):
        moves = random_game(seed, 60); st = GameState.opening(); truth = Board.initial()
        for m in moves:
            truth = truth.apply(m)
            assert advance(st, truth.colors()) == "moved"
            assert st.board == truth
        assert st.moves == moves and st.exact


def test_quick_reply_two_plies_at_once():
    moves = random_game(7, 40); st = GameState.opening(); truth = Board.initial()
    for a, b in zip(moves[::2], moves[1::2]):
        truth = truth.apply(a).apply(b)
        assert advance(st, truth.colors()) == "moved"
        assert st.board == truth and st.turn == "red"


def test_wrong_turn_guess_is_corrected():
    b = Board.initial().apply("h2e2")
    st = GameState.from_position(b, "red")          # wrongly assumes red to move
    after = b.apply("h9g7")
    assert advance(st, after.colors()) == "moved"
    assert st.board == after and st.turn == "red"


def test_take_back_restores_position():
    st = GameState.opening(); b = Board.initial()
    for m in ("h2e2", "h9g7", "e2e6"):                # cannon captures a pawn
        b = b.apply(m); advance(st, b.colors())
    before_capture = Board.initial().apply("h2e2").apply("h9g7")
    assert advance(st, before_capture.colors()) == "undo"
    assert st.board == before_capture and st.turn == "red" and st.moves == ["h2e2", "h9g7"]


def test_new_game_detected():
    st = GameState.opening(); b = Board.initial().apply("h2e2"); advance(st, b.colors())
    assert advance(st, Board.initial().colors()) == "opening"
    assert st.board == Board.initial() and st.turn == "red" and not st.moves


def test_stability_and_patience():
    t = Tracker(stable_frames=3, patience=1.0); t.reset(GameState.opening())
    after = Board.initial().apply("b0c2").colors()
    garbage = list(after); garbage[0] = None; garbage[40] = "red"     # half-finished animation: piece mid-air
    assert t.feed(garbage, 0.0) == "wait"
    assert t.feed(after, 0.1) == "wait" and t.feed(after, 0.2) == "wait"
    assert t.feed(after, 0.3) == "moved" and t.state.turn == "black"
    for i in range(3): t.feed(garbage, 1 + i * .1)
    assert t.feed(garbage, 1.5) == "wait"
    assert t.feed(garbage, 2.6) == "unknown"


def test_slide_resting_on_intermediate_point_is_merged():
    st = GameState.opening(); b = Board.initial()
    assert advance(st, b.apply("h2h4").colors()) == "moved"      # cannon seen on h4 mid-slide
    assert advance(st, b.apply("h2h6").colors()) == "moved"      # ... it really went to h6
    assert st.moves == ["h2h6"] and st.board == b.apply("h2h6") and st.turn == "black"


def engine_board(st):
    """What the engine will analyse: base position + move list."""
    b = Board.from_fen(st.base_fen); turn = "red" if st.base_fen.split()[1] == "w" else "black"
    for m in st.moves:
        assert b.legal_move(m, turn), "engine would reject the move list"
        b = b.apply(m); turn = "black" if turn == "red" else "red"
    return b, turn


def test_engine_input_always_matches_tracked_position():
    b = Board.initial().apply("h2e2")
    st = GameState.from_position(b, "red")              # wrong turn guess
    for m in ("h9g7", "h0g2", "i9h9"):                  # first one corrects the turn
        b = b.apply(m); assert advance(st, b.colors()) == "moved"
        assert engine_board(st) == (st.board, st.turn)
    st.set_turn("black")                                # e.g. "提示走法" forcing the turn
    assert engine_board(st) == (st.board, "black")
    st = GameState.opening(); b = Board.initial()
    for m in ("h2e2", "h9g7"):
        b = b.apply(m)
    assert advance(st, b.colors()) == "moved"           # two plies at once
    assert engine_board(st) == (st.board, st.turn) and st.ply == 2


def test_momentarily_missed_piece_is_kept_not_reread():
    """A piece that is not detected for a while must stay in the game (the reported bug)."""
    t = Tracker(stable_frames=1, patience=.5); t.reset(GameState.opening())
    b = Board.initial(); seen = list(b.colors()); seen[6 * 9 + 0] = None      # red pawn a3 not detected
    for k in range(20): assert t.feed(tuple(seen), k * .1) in ("unseen", "same")
    assert t.state.board == b and t.state.exact and 54 in t.state.unseen
    b = b.apply("h2e2"); seen = list(b.colors()); seen[54] = None              # play on while still missed
    t.feed(tuple(seen), 3)                                                      # cannon: confirmed one frame later
    assert t.feed(tuple(seen), 3.1) == "moved" and t.state.board == b
    b = b.apply("h9g7"); assert t.feed(b.colors(), 4) == "moved"                # pawn visible again
    assert t.state.board == b and not t.state.unseen
    # the missed pawn really moves away: legal and followed
    b = b.apply("a3a4"); assert t.feed(b.colors(), 5) == "moved" and t.state.board == b
