"""Real-desktop check with the user's JJ screenshots (scaled), real GUI and engine."""
import json
import shutil
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coach.capture import enable_dpi
enable_dpi()
import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel
from coach.board import Board
from coach.config import Settings
import coach.app as app_module

FIX = ROOT / "tests/fixtures"
TRUTH = json.loads((FIX / "truth.json").read_text(encoding="utf-8"))


def pix(name, scale):
    img = cv2.imdecode(np.fromfile(str(FIX / (name + ".jpg")), np.uint8), cv2.IMREAD_COLOR)
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    return QPixmap.fromImage(QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy())


def main():
    out = ROOT / "work/desktop-jj"; shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    app = QApplication(sys.argv)
    app_module.ROOT = out
    Settings.load = classmethod(lambda cls, path=None: Settings(side="red", engine_path=str(ROOT / "engine/pikafish.exe"), movetime_ms=1000))
    Settings.save = lambda self, path=None: None
    view = QLabel(); view.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint); view.setWindowTitle("JJ截图回放")

    def show(name):
        p = pix(name, .7); p.setDevicePixelRatio(view.devicePixelRatioF()); view.setPixmap(p); view.adjustSize()

    show("jj_initial"); view.move(40, 0); view.show()
    w = app_module.MainWindow(); w.move(view.x() + view.width() + 30, 60); w.show()
    report = {"checks": [], "errors": []}; t0 = time.monotonic(); step = {"n": 0, "t": t0}
    names = [n for n in ("jj_midgame", "jj_midgame2") if (FIX / (n + ".jpg")).exists()]

    def finish(err=None):
        if err: report["errors"].append(err)
        timer.stop(); w.close(); view.close()
        (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"); app.quit()

    def tick():
        if time.monotonic() - t0 > 80: finish("timeout at step %d" % step["n"]); return
        s = step["n"]
        if s == 0:
            w.start_btn.click(); step["n"] = 1; return
        if s == 1 and w.best and w.snap and w.snap.exact:
            report["checks"].append(f"opening found and hinted: {w.best} {w.hint.text()}")
            report["skin_learned"] = w.recognizer.has_skin
            step["n"] = 2; step["i"] = 0
        if s == 2:
            if step["i"] >= len(names): finish(); return
            show(names[step["i"]]); step["n"] = 3; step["t"] = time.monotonic(); return
        if s == 3 and time.monotonic() - step["t"] > 1.0:
            w.hint_btn.click(); step["n"] = 4; step["t"] = time.monotonic(); return
        if s == 4 and w.snap and w.best and w.snap.board == Board.from_fen(TRUTH[names[step["i"]]]):
            report["checks"].append(f"{names[step['i']]} read exactly, hint {w.best} {w.hint.text()}")
            w.grab().save(str(out / f"panel-{step['i']}.png"))
            step["i"] += 1; step["n"] = 2
        elif s == 4 and time.monotonic() - step["t"] > 15:
            finish(f"{names[step['i']]}: board read " + (w.snap.board.fen('red') if w.snap else "none"))

    timer = QTimer(); timer.setInterval(150); timer.timeout.connect(tick); QTimer.singleShot(800, timer.start)
    app.exec()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
