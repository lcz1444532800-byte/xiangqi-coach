"""Recognition accuracy on real screenshots at several display sizes.

    .venv\\Scripts\\python.exe tools\\eval_recognition.py

Reports wrong pieces (after the rule-constrained assignment) per setting,
for generic recognition (mid-game start, skin never seen) and after the
skin was learned from the opening screenshot. Also raw per-piece accuracy.
"""
import json
import sys
from pathlib import Path
import cv2
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coach.board import Board
from coach.vision import detect_grids, Observer, Recognizer, TYPES, orient

FIX = ROOT / "tests/fixtures"
def path(name):
    return next((FIX / (name + e) for e in (".jpg", ".png") if (FIX / (name + e)).exists()), None)


TRUTH = {k: Board.from_fen(v) for k, v in json.loads((FIX / "truth.json").read_text(encoding="utf-8")).items()
         if not k.startswith("_") and not k.startswith("jj_popup") and path(k)}
SCALES = (1.0, .5)


class Cached:
    """Observer stand-in that replays pre-extracted stroke masks."""
    def __init__(self, ob, image, obs):
        self.ob = ob; self.obs = obs
        self.masks = {i: ob.ink(image, i, bool(obs.lift[i])) for i, c in enumerate(obs.screen) if c}

    def ink(self, image, i, lifted=False): return self.masks[i]
    def glyph(self, image, i, lifted=False):
        from coach.vision import glyph_vector
        m = self.masks.get(i); return None if m is None else glyph_vector(m)


def prepare():
    cases = []
    for scale in SCALES:
        for name, truth in TRUTH.items():
            img = cv2.imdecode(np.fromfile(str(path(name)), np.uint8), cv2.IMREAD_COLOR)
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            g = detect_grids(img)[0]; h, w = img.shape[:2]
            rect = g.capture_rect({"left": 0, "top": 0, "width": w, "height": h})
            crop = img[rect["top"]:rect["top"] + rect["height"], rect["left"]:rect["left"] + rect["width"]]
            ob = Observer(g, rect); obs = ob.observe(crop)
            cases.append((scale, name, truth, Cached(ob, crop, obs), obs, obs.colors == truth.colors()))
    return cases


def errors(board, truth):
    return sum(board.cells[r][c] != truth.cells[r][c] for r in range(10) for c in range(9))


def evaluate(cases, verbose=False):
    total_generic = total_skin = 0; raw_ok = raw_n = 0; rows = []
    skins = {}
    for scale, name, truth, cached, obs, colours_ok in cases:
        if name == "jj_initial":   # "with skin" = learned from this opening screenshot
            rec = Recognizer(None); rec.library_labels = rec.library_labels[:0]; rec.learn(cached, None, Board.initial(), True, obs); skins[scale] = rec
    for scale, name, truth, cached, obs, colours_ok in cases:
        gen = Recognizer(None); gen.library_vectors = gen.library_vectors[:0]; gen.library_labels = gen.library_labels[:0]
        e1 = errors(gen.recognize(cached, None, obs)[0], truth)
        skin = skins[scale]
        e2 = errors(skin.recognize(cached, None, obs)[0], truth)
        for i, mask in cached.masks.items():     # raw classifier/template argmax, no rules
            c, r = orient(i % 9, i // 9, True); p = truth.cells[r][c]
            if p is None: continue
            sc = gen.type_scores(mask, "red" if p.isupper() else "black")
            raw_ok += max(sc, key=sc.get) == p.lower(); raw_n += 1
        total_generic += e1; total_skin += e2
        rows.append(f"  {scale:>4} {name:<22} colours {'OK' if colours_ok else 'BAD'}  generic errors {e1}  with skin {e2}")
    if verbose: print("\n".join(rows))
    return total_generic, total_skin, raw_ok / max(1, raw_n)


if __name__ == "__main__":
    cases = prepare()
    print(f"{len(cases)} boards ({len(TRUTH)} screenshots x scales {SCALES})")
    g, s, raw = evaluate(cases, verbose=True)
    print(f"wrong pieces: generic {g}, with skin {s}; raw per-piece accuracy (no rules) {raw:.3f}")
