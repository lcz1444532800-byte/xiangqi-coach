"""Real-desktop smoke test: real screen capture, real GUI, real Pikafish.

Shows a board in a window, clicks 开始 on the real main window and plays the
hinted moves (plus engine replies for the opponent) by redrawing that board.
Writes work/desktop-smoke/result.json and screenshots. Touches no other program.
"""
import json
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from coach.capture import enable_dpi
enable_dpi()
import threading
import mss
import numpy as np
import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel
from coach.board import Board
from coach.config import Settings
from coach.engine import UciEngine
import coach.app as app_module


def to_pixmap(bgr):
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    return QPixmap.fromImage(QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy())


def main():
    side = sys.argv[1] if len(sys.argv) > 1 else "red"
    out = ROOT / ("work/desktop-smoke-" + side); out.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    from render import render, SKINS
    app_module.ROOT = out           # learned skin goes to the test folder
    Settings.load = classmethod(lambda cls, path=None: Settings(side=side, engine_path=str(ROOT / "engine/pikafish.exe"), movetime_ms=1000))
    Settings.save = lambda self, path=None: None
    skin = SKINS[0]; red_bottom = side == "red"
    board = Board.initial(); turn = "red"; moves = []
    fixture = QLabel(); fixture.setWindowTitle("测试棋盘（模拟）")
    fixture.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

    def show(last=None):
        img = render(board, skin, red_bottom, size=(760, 800), origin=(140, 120), last_move=last)
        fixture.setPixmap(to_pixmap(img).scaledToHeight(int(800 / fixture.devicePixelRatioF()), Qt.TransformationMode.SmoothTransformation))
        fixture.adjustSize()

    show(); fixture.move(60, 40); fixture.show()
    w = app_module.MainWindow(); w.move(fixture.x() + fixture.width() + 40, 60); w.show()
    opponent = UciEngine(ROOT / "engine/pikafish.exe", 2, 64); opponent.start()
    report = {"side": side, "events": [], "errors": [], "hints": []}
    state = {"phase": "start", "t": time.monotonic(), "plies": 0, "last_hint": None}

    def log(msg):
        report["events"].append(f"{time.monotonic() - t0:6.2f}s {msg}")

    def finish(err=None):
        if err: report["errors"].append(err)
        timer.stop()
        try:
            with mss.mss() as s:
                shot = np.asarray(s.grab(s.monitors[1]))[:, :, :3]
            cv2.imencode(".png", shot)[1].tofile(str(out / "desktop-end.png"))
        except Exception as e:
            report["errors"].append("screenshot: " + repr(e))
        w.grab().save(str(out / "panel.png"))
        report["overlay_capture_excluded"] = w.overlay.capture_excluded
        w.close(); fixture.close(); opponent.close()
        (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        app.quit()

    def play(move):
        nonlocal board, turn
        from coach.board import parse_move
        a, b = parse_move(move); board = board.apply(move); moves.append(move)
        turn = "black" if turn == "red" else "red"; show([a, b]); state["plies"] += 1

    def tick():
        now = time.monotonic()
        if now - t0 > 90: finish("timeout in phase " + state["phase"]); return
        if state["phase"] == "start":
            w.start_btn.click(); state["phase"] = "follow"; log("clicked 开始")
            w.worker.status.connect(lambda text: log("status: " + text))
            w.worker.position.connect(lambda snap: log(f"position published ({len(snap.moves)} moves, {snap.turn} to move)"))
            w.engine.result.connect(lambda key, mv: log("engine result " + mv))
            return
        snap = w.snap
        if turn != side and snap is None: return          # let the helper find the board first
        if turn != side:
            if state["phase"] != "opp" and (snap is None or snap.turn == turn and len(snap.moves) == len(moves)):
                state["phase"] = "opp"; state["t"] = now
            if state["phase"] == "opp" and now - state["t"] > .6:
                mv = opponent.search(Board.initial().fen("red"), moves, 300, threading.Event())
                log("opponent plays " + mv); play(mv); state["phase"] = "follow"
            return
        if w.best and snap and len(snap.moves) == len(moves) and w.overlay.isVisible():
            hint = w.hint.text(); report["hints"].append({"ply": len(moves), "move": w.best, "text": hint})
            log(f"hint {w.best} {hint}")
            if not board.legal_move(w.best, side): finish("hint is illegal"); return
            if state["plies"] >= 8:
                w.grab().save(str(out / "panel-hint.png"))
                with mss.mss() as s:
                    shot = np.asarray(s.grab(s.monitors[1]))[:, :, :3]
                pm = w.overlay.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                ov = np.frombuffer(pm.constBits(), np.uint8).reshape(pm.height(), pm.bytesPerLine() // 4, 4)[:, :pm.width()]
                ov = cv2.resize(ov, (shot.shape[1], shot.shape[0]))
                alpha = ov[:, :, 3:4] / 255.0
                comp = (shot * (1 - alpha) + ov[:, :, 2::-1] * alpha).astype(np.uint8)
                cv2.imencode(".png", comp[:1300, :1400])[1].tofile(str(out / "arrow-composite.png"))
                finish(); return
            play(w.best); log("user plays the hint")

    t0 = time.monotonic()
    timer = QTimer(); timer.setInterval(100); timer.timeout.connect(tick); QTimer.singleShot(800, timer.start)
    app.exec()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
