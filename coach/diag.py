"""Diagnostic recording: what the helper saw and decided (data/diag/<session>/).

events.log  - one line per event (positions, re-reads, hints, warnings)
NNNN-*.jpg  - the board capture at that moment, with a .json describing it
Only the last few sessions and the last KEEP captures per session are kept.
"""
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path
import cv2

KEEP = 60
SESSIONS = 3


class Diagnostics:
    def __init__(self, root):
        self.lock = threading.Lock(); self.n = 0; self.folder = None
        try:
            base = Path(root) / "data/diag"; base.mkdir(parents=True, exist_ok=True)
            for old in sorted(p for p in base.iterdir() if p.is_dir())[:-(SESSIONS - 1) or None]:
                shutil.rmtree(old, ignore_errors=True)
            self.folder = base / datetime.now().strftime("%Y%m%d-%H%M%S"); self.folder.mkdir()
        except OSError:
            self.folder = None

    def event(self, text):
        if self.folder is None: return
        with self.lock:
            try:
                with open(self.folder / "events.log", "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}  {text}\n")
            except OSError:
                pass

    def capture(self, tag, image, info):
        """Save a board capture plus a JSON description; returns the file stem."""
        if self.folder is None or image is None: return None
        with self.lock:
            self.n += 1; stem = f"{self.n:04d}-{tag}"
            try:
                ok, enc = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
                if ok: enc.tofile(str(self.folder / (stem + ".jpg")))
                (self.folder / (stem + ".json")).write_text(json.dumps(info, ensure_ascii=False, indent=1, default=_plain), encoding="utf-8")
                shots = sorted(self.folder.glob("*.jpg"))
                for old in shots[:-KEEP]:
                    old.unlink(missing_ok=True); old.with_suffix(".json").unlink(missing_ok=True)
            except Exception:          # diagnostics must never stop the helper
                pass
        return stem


def _plain(value):
    """numpy scalars / sets etc. -> plain JSON values."""
    if hasattr(value, "item"): return value.item()
    if isinstance(value, (set, frozenset, tuple)): return list(value)
    return str(value)


def describe(board, turn=None):
    """Text diagram of a board (canonical, red at the bottom)."""
    from .board import NAMES
    rows = [" ".join(NAMES[p] if p else "·" for p in row) for row in board.cells]
    return rows + ([f"轮到：{'红' if turn == 'red' else '黑'}"] if turn else [])


def colours_text(colors):
    return ["".join({None: "·", "red": "红", "black": "黑"}[colors[r * 9 + c]] for c in range(9)) for r in range(10)]

