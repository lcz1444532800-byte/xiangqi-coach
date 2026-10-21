"""End-to-end: the real CoachWorker thread follows a simulated game on screen."""
import random
import time
import numpy as np
import pytest
from PySide6.QtCore import Qt
from coach.board import Board, parse_move
import coach.worker as worker_module
from coach.worker import CoachWorker
from coach.vision import Recognizer


def frames_for_game(render, skin, moves, red_bottom, quick_every=5):
    """Screen frames: opening, then per move a lifted piece, a mid-slide frame, the result."""
    b = Board.initial(); out = [render(b, skin, red_bottom)] * 4
    for n, m in enumerate(moves):
        (x, y), (a, c) = parse_move(m); piece = b.cells[y][x]
        out += [render(b, skin, red_bottom, lifted=(x, y))] * 3
        mid = b.copy(); mid.cells[y][x] = None
        sx, sy = ((x + a) / 2, (y + c) / 2) if red_bottom else (8 - (x + a) / 2, 9 - (y + c) / 2)
        out += [render(mid, skin, red_bottom, moving=(piece, (sx, sy)))] * 2
        b = b.apply(m)
        quick = n % quick_every == 0 and n + 1 < len(moves)
        if not quick:   # opponent "instantly" replying skips the settled frame
            out += [render(b, skin, red_bottom, last_move=[(x, y), (a, c)])] * 5
    out += [render(b, skin, red_bottom)] * 8
    return out, b


class FakeScreen:
    def __init__(self, frames):
        self.frames = frames; self.i = 0; self.done = False

    def grab(self, rect):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        if self.i >= len(self.frames) + 10: self.done = True
        return f[rect["top"]:rect["top"] + rect["height"], rect["left"]:rect["left"] + rect["width"]]


@pytest.mark.parametrize("skin_index,red_bottom,side", [(0, True, "red"), (2, False, "black")])
def test_worker_follows_whole_game(qapp, tmp_path, monkeypatch, skin_index, red_bottom, side):
    from render import render, SKINS
    rng = random.Random(skin_index); b = Board.initial(); turn = "red"; moves = []
    for _ in range(24):
        m = rng.choice(b.legal_moves(turn)); moves.append(m); b = b.apply(m); turn = "black" if turn == "red" else "red"
    frames, final = frames_for_game(render, SKINS[skin_index], moves, red_bottom)
    screen = FakeScreen(frames)
    monkeypatch.setattr(worker_module, "INTERVAL", 0.0)
    monkeypatch.setattr(CoachWorker, "grab", lambda self, rect: screen.grab(rect))
    rec = Recognizer(tmp_path / "skin.npz")
    w = CoachWorker(rec, side, None, [{"name": "fake", "left": 0, "top": 0, "width": 900, "height": 900}])
    w.tracker.patience = 0.05
    seen = []
    w.position.connect(lambda snap: seen.append(snap), Qt.ConnectionType.DirectConnection)
    w.start()
    deadline = time.monotonic() + 120
    while not screen.done and time.monotonic() < deadline: time.sleep(.05)
    w.stop(); w.wait(5000)
    assert seen, "no position published"
    last = seen[-1]
    assert last.board == final and last.moves == tuple(moves) and last.exact
    assert last.red_bottom == red_bottom and last.turn == turn
    assert rec.has_skin                     # opening taught the skin
    # Every published position is a real position of the game (no garbage states).
    truth = [Board.initial()]
    for m in moves: truth.append(truth[-1].apply(m))
    bad = [s.moves for s in seen if not any(s.board == t for t in truth)]
    assert not bad, (" ".join(moves), [" ".join(b) for b in bad[:3]])


def test_board_window_dragged_mid_game(qapp, tmp_path, monkeypatch):
    from render import render, SKINS
    skin = SKINS[1]; b = Board.initial()
    moves = ["h2e2", "h9g7", "h0g2", "i9h9", "i0h0", "b7b3"]
    frames = [render(b, skin, True)] * 5
    for n, m in enumerate(moves):
        if n == 3:      # the user drags the board window, then play continues
            frames += [render(b, skin, True, origin=(150, 105))] * 200
        b = b.apply(m)
        frames += [render(b, skin, True, origin=(120, 80) if n < 3 else (150, 105))] * 6
    frames += [frames[-1]] * 30
    screen = FakeScreen(frames)
    monkeypatch.setattr(worker_module, "INTERVAL", 0.012)      # 200 frames ~ 2.4 s: longer than the 1.5 s "lost" delay
    monkeypatch.setattr(CoachWorker, "grab", lambda self, rect: screen.grab(rect))
    w = CoachWorker(Recognizer(tmp_path / "skin.npz"), "red", None,
                    [{"name": "fake", "left": 0, "top": 0, "width": 900, "height": 900}])
    seen = []; found = []
    w.position.connect(lambda snap: seen.append(snap), Qt.ConnectionType.DirectConnection)
    w.board_found.connect(lambda g: found.append(g), Qt.ConnectionType.DirectConnection)
    w.start()
    deadline = time.monotonic() + 60
    while not screen.done and time.monotonic() < deadline: time.sleep(.05)
    w.stop(); w.wait(5000)
    assert len(found) >= 2 and abs(found[-1].corners[0][0] - 150) < 4
    assert seen[-1].board == b and seen[-1].turn == "red" and seen[-1].exact and len(seen[-1].moves) == 6


def _fixture(name):
    import cv2, json
    from pathlib import Path
    fix = Path(__file__).with_name("fixtures")
    truth = json.loads((fix / "truth.json").read_text(encoding="utf-8"))
    img = cv2.imdecode(np.fromfile(str(fix / (name + ".png")), np.uint8), cv2.IMREAD_COLOR)
    return img, Board.from_fen(truth[name])


@pytest.mark.parametrize("name", ["jj_popup_self", "jj_popup_opponent"])
def test_real_popup_is_occlusion_not_a_new_board(qapp, tmp_path, monkeypatch, name):
    """A profile/win-rate card over the board must neither move the lattice nor change the game."""
    from coach.tracker import GameState, Tracker
    img, truth = _fixture(name)
    h, w = img.shape[:2]
    monkeypatch.setattr(CoachWorker, "grab", lambda self, rect: img[rect["top"]:rect["top"] + rect["height"],
                                                                 rect["left"]:rect["left"] + rect["width"]])
    wk = CoachWorker(Recognizer(tmp_path / "s.npz"), "red", None, [{"name": "m", "left": 0, "top": 0, "width": w, "height": h}])
    wk.tracker.reset(GameState.from_position(truth, "red")); wk.mismatch_since = time.monotonic()
    assert wk.find_board()                                   # only a lattice showing this game is accepted
    obs = wk.observer.observe(wk.grab(wk.rect))
    assert all(o in (None, e) for o, e in zip(obs.colors, truth.colors()))   # nothing invented
    t = Tracker(stable_frames=1); t.reset(GameState.from_position(truth, "red"))
    assert t.feed(obs.colors, 0) == "occluded" and t.feed(obs.colors, 5) == "occluded"
    assert t.state.board == truth


def test_popup_during_game_then_opponent_moves(qapp, tmp_path, monkeypatch):
    import cv2
    from render import render, SKINS
    skin = SKINS[0]; b = Board.initial()
    frames = [render(b, skin, True)] * 6
    for m in ("h2e2", "h9g7", "h0g2"):
        b = b.apply(m); frames += [render(b, skin, True)] * 6

    def popup(img, top):
        img = img.copy(); y0, y1 = (40, 260) if top else (560, 820)
        cv2.rectangle(img, (150, y0), (560, y1), (230, 240, 245), -1)
        cv2.circle(img, (230, (y0 + y1) // 2), 40, (90, 120, 200), -1)     # round avatar
        return img
    frames += [popup(render(b, skin, True), False)] * 60                    # own card, ~3 s
    b = b.apply("i9h9")                                                     # opponent moves meanwhile
    frames += [popup(render(b, skin, True), True)] * 60                     # opponent card
    frames += [render(b, skin, True)] * 30
    screen = FakeScreen(frames)
    monkeypatch.setattr(worker_module, "INTERVAL", 0.05)
    monkeypatch.setattr(CoachWorker, "grab", lambda self, rect: screen.grab(rect))
    w = CoachWorker(Recognizer(tmp_path / "skin.npz"), "red", None, [{"name": "fake", "left": 0, "top": 0, "width": 900, "height": 900}])
    seen, status = [], []
    w.position.connect(lambda s: seen.append(s), Qt.ConnectionType.DirectConnection)
    w.status.connect(lambda s: status.append(s), Qt.ConnectionType.DirectConnection)
    w.start()
    deadline = time.monotonic() + 60
    while not screen.done and time.monotonic() < deadline: time.sleep(.05)
    w.stop(); w.wait(5000)
    assert any("遮挡" in s for s in status)
    assert seen[-1].board == b and seen[-1].exact and seen[-1].moves == ("h2e2", "h9g7", "h0g2", "i9h9")
    truth = [Board.initial()]
    for m in seen[-1].moves: truth.append(truth[-1].apply(m))
    assert all(any(s.board == t for t in truth) for s in seen)              # never a half-hidden board


def test_blinking_effect_does_not_stall_tracking(qapp, tmp_path, monkeypatch):
    """A pulsing effect that hides a piece every other frame must not freeze the game."""
    import cv2
    from render import render, SKINS
    skin = SKINS[0]; b = Board.initial(); frames = [render(b, skin, True)] * 6

    def blink(img, on):
        img = img.copy()
        if on:      # a pulsing effect washes out the black pawn on e6 every other frame
            c = (120 + 4 * 60, 80 + 3 * 60)
            cv2.circle(img, c, 30, (143, 201, 233), -1)
        return img
    for k, m in enumerate(("h2e2", "h9g7", "h0g2", "i9h9")):
        b = b.apply(m)
        img = render(b, skin, True)
        frames += [blink(img, i % 2 == 0) for i in range(14)]          # blinking the whole time
    screen = FakeScreen(frames)
    monkeypatch.setattr(worker_module, "INTERVAL", 0.0)
    monkeypatch.setattr(CoachWorker, "grab", lambda self, rect: screen.grab(rect))
    w = CoachWorker(Recognizer(tmp_path / "skin.npz"), "red", None, [{"name": "fake", "left": 0, "top": 0, "width": 900, "height": 900}])
    seen = []
    w.position.connect(lambda s: seen.append(s), Qt.ConnectionType.DirectConnection)
    w.start()
    deadline = time.monotonic() + 60
    while not screen.done and time.monotonic() < deadline: time.sleep(.05)
    w.stop(); w.wait(5000)
    assert seen[-1].board == b and seen[-1].exact and seen[-1].moves == ("h2e2", "h9g7", "h0g2", "i9h9")


@pytest.mark.parametrize("red_bottom", [True, False])
def test_missed_edge_pawn_never_drops_out_of_the_game(qapp, tmp_path, monkeypatch, red_bottom):
    """Reported bug: a piece missing from the tracked game made an illegal cannon capture look legal."""
    import cv2
    from render import render, SKINS
    skin = SKINS[0]; b = Board.initial()

    def hide_a3(img):           # an effect / misdetection wipes out the red a-file pawn
        img = img.copy(); c, r = (0, 6) if red_bottom else (8, 3)
        cv2.circle(img, (120 + c * 60, 80 + r * 60), 29, (143, 201, 233), -1)
        return img
    frames = [render(b, skin, red_bottom)] * 6
    moves = ["h2e2", "h9g7", "h0g2", "b7a7", "b2c2", "i9i8"]
    for k, m in enumerate(moves):
        b = b.apply(m); img = render(b, skin, red_bottom)
        frames += [hide_a3(img) if 1 <= k <= 4 else img] * 50       # ~2.5 s per move, pawn unseen for 4 moves
    frames += [render(b, skin, red_bottom)] * 20
    screen = FakeScreen(frames)
    monkeypatch.setattr(worker_module, "INTERVAL", 0.0)
    monkeypatch.setattr(CoachWorker, "grab", lambda self, rect: screen.grab(rect))
    w = CoachWorker(Recognizer(tmp_path / "skin.npz"), "black", None, [{"name": "fake", "left": 0, "top": 0, "width": 900, "height": 900}])
    seen = []
    w.position.connect(lambda s: seen.append(s), Qt.ConnectionType.DirectConnection)
    w.start()
    deadline = time.monotonic() + 90
    while not screen.done and time.monotonic() < deadline: time.sleep(.05)
    w.stop(); w.wait(5000)
    assert all(s.board.cells[6][0] == "P" for s in seen)          # the pawn is in every published position
    assert seen[-1].board == b and seen[-1].exact and seen[-1].moves == tuple(moves)
    # the cannon on a7 can never "capture" the rook on a0 through two pawns
    assert all(not s.board.legal_move("a7a0", "black") for s in seen if s.board.cells[2][0] == "c")
