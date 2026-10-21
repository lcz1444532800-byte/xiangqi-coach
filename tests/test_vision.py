from pathlib import Path
import json
import cv2
import numpy as np
import pytest
from coach.board import Board
from coach.vision import detect_grids, Observer, Recognizer

FIX = Path(__file__).with_name("fixtures")
ALL = {k: Board.from_fen(v) for k, v in json.loads((FIX / "truth.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
def path(name):
    return next((FIX / (name + ext) for ext in (".jpg", ".png") if (FIX / (name + ext)).exists()), None)


TRUTH = {k: v for k, v in ALL.items() if path(k) and not k.startswith("jj_popup")}
POPUPS = {k: v for k, v in ALL.items() if path(k) and k.startswith("jj_popup")}
MID = ALL["jj_midgame2"]


def read(image, grid_index=0):
    grids = detect_grids(image)
    assert grids, "board not found"
    g = grids[grid_index]; h, w = image.shape[:2]
    rect = g.capture_rect({"left": 0, "top": 0, "width": w, "height": h})
    crop = image[rect["top"]:rect["top"] + rect["height"], rect["left"]:rect["left"] + rect["width"]]
    return g, Observer(g, rect), crop


def load(name):
    return cv2.imdecode(np.fromfile(str(path(name)), np.uint8), cv2.IMREAD_COLOR)


@pytest.mark.parametrize("name", list(TRUTH))
def test_real_screenshot_grid_and_colours(name):
    g, ob, crop = read(load(name))
    if name in ("jj_initial", "jj_midgame", "jj_midgame2"):     # these share one known layout
        tl, _, br, _ = g.corners
        assert abs(tl[0] - 62) < 6 and abs(tl[1] - 561) < 6 and abs(br[0] - 858) < 6 and abs(br[1] - 1426) < 6
    assert ob.observe(crop).colors == TRUTH[name].colors()


def generic():
    """Recognizer that knows no skin at all: fonts + rules only."""
    rec = Recognizer(None)
    rec.library_vectors = rec.library_vectors[:0]; rec.library_labels = rec.library_labels[:0]
    return rec


def wrong(a, b):
    return sum(x != y for ra, rb in zip(a.cells, b.cells) for x, y in zip(ra, rb))


@pytest.mark.parametrize("name", list(TRUTH))
def test_real_screenshot_full_recognition(name):
    """Normal path (built-in skin library + fonts + rules): every piece right."""
    g, ob, crop = read(load(name))
    board, red_bottom, _ = Recognizer(None).recognize(ob, crop, ob.observe(crop))
    assert red_bottom and board == TRUTH[name]


@pytest.mark.parametrize("name", list(TRUTH))
def test_real_screenshot_full_recognition_generic_fonts(name):
    """Fallback for an unknown skin: fonts + rules only, at most one piece off."""
    g, ob, crop = read(load(name))
    board, red_bottom, _ = generic().recognize(ob, crop, ob.observe(crop))
    assert red_bottom and wrong(board, TRUTH[name]) <= 1


@pytest.mark.parametrize("scale", [.7, .5, .4])
@pytest.mark.parametrize("name", [n for n in TRUTH if n.startswith("jj_mid")])
def test_builtin_jj_skin_small_boards(name, scale):
    image = cv2.resize(load(name), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    g, ob, crop = read(image); o = ob.observe(crop)
    assert o.colors == TRUTH[name].colors()
    assert Recognizer(None).recognize(ob, crop, o)[0] == TRUTH[name]


def test_learned_skin_from_opening(tmp_path):
    g, ob, crop = read(load("jj_initial"))
    rec = Recognizer(tmp_path / "skin.npz")
    assert rec.learn(ob, crop, Board.initial(), True, ob.observe(crop))
    rec = Recognizer(tmp_path / "skin.npz"); assert rec.has_skin
    rec.library_vectors = rec.library_vectors[:0]; rec.library_labels = rec.library_labels[:0]
    for name in [n for n in TRUTH if n != "jj_initial"]:
        g, ob, crop = read(load(name)); o = ob.observe(crop)
        assert rec.recognize(ob, crop, o)[0] == TRUTH[name]


def test_board_inside_large_desktop():
    image = load("jj_midgame2")
    desk = np.full((1600, 2560, 3), 35, np.uint8); desk[:1600, 900:1814] = image[200:1800]
    g, ob, crop = read(desk)
    assert abs(g.corners[0][0] - 962) < 6 and abs(g.corners[0][1] - 361) < 6
    assert ob.observe(crop).colors == MID.colors()


@pytest.fixture(scope="module")
def skins(qapp):
    from render import render, SKINS
    return render, SKINS


@pytest.mark.parametrize("skin", range(4))
@pytest.mark.parametrize("red_bottom", [True, False])
def test_synthetic_skins(skins, skin, red_bottom):
    render, SKINS = skins
    for board in (Board.initial(), MID):
        image = render(board, SKINS[skin], red_bottom, last_move=[(4, 6), (4, 3)], lifted=(7, 3), noise=4)
        g, ob, crop = read(image)
        o = ob.observe(crop, red_bottom)
        assert o.colors == board.colors()
        got, rb, _ = generic().recognize(ob, crop, o)
        assert rb == red_bottom and got == board
