"""Add a built-in skin to coach/assets/skins/ from screenshots with known positions.

    .venv\\Scripts\\python.exe tools\\make_skin.py jj_battle tests\\fixtures\\jj_initial.jpg [more.jpg ...]

Each screenshot's position is looked up in tests/fixtures/truth.json by file
name; without an entry it must show the opening position.
"""
import json
import sys
from pathlib import Path
import cv2
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coach.board import Board
from coach.vision import detect_grids, Observer, ASSETS, orient

TRUTH = json.loads((ROOT / "tests/fixtures/truth.json").read_text(encoding="utf-8"))


def samples(path):
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    board = Board.from_fen(TRUTH.get(Path(path).stem, Board.initial().fen("red")))
    g = detect_grids(img)[0]; h, w = img.shape[:2]
    rect = g.capture_rect({"left": 0, "top": 0, "width": w, "height": h})
    crop = img[rect["top"]:rect["top"] + rect["height"], rect["left"]:rect["left"] + rect["width"]]
    ob = Observer(g, rect); obs = ob.observe(crop)
    for red_bottom in (True, False):
        if obs.oriented(red_bottom) == board.colors(): break
    else:
        raise SystemExit(f"{path}: screenshot does not match its known position")
    out = []
    for r in range(10):
        for c in range(9):
            p = board.cells[r][c]
            if not p: continue
            sc, sr = orient(c, r, red_bottom); i = sr * 9 + sc
            v = ob.glyph(crop, i, bool(obs.lift[i]))
            if v is not None: out.append((v, p))
    return out


def main():
    name, paths = sys.argv[1], sys.argv[2:]
    data = [s for p in paths for s in samples(p)]
    if len({p for _, p in data}) < 14: raise SystemExit("need all 14 piece kinds")
    folder = ASSETS / "skins"; folder.mkdir(exist_ok=True)
    np.savez_compressed(folder / f"{name}.npz", vectors=np.array([v for v, _ in data], np.float16),
                        labels=np.array([p for _, p in data]))
    print(f"{folder / name}.npz: {len(data)} templates")


if __name__ == "__main__":
    main()
