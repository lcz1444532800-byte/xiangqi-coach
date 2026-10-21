import sys
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase, QAction
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMenu, QDialog
from .config import Settings, ROOT
from .capture import screen_maps, grab
from .board import parse_move
from .vision import Grid, Recognizer, orient
from .engine import EngineService
from .worker import CoachWorker
from .overlay import ArrowOverlay, exclude_from_capture
from .diag import Diagnostics

OPENING_PLIES = 16      # first 8 moves of each side get varied (still sound) suggestions

STYLE = """
QWidget#panel { background:#fbf7ee; }
QLabel#hint { font-size:30px; font-weight:bold; color:#0b7a3e; padding:6px 0; }
QLabel#status { font-size:13px; color:#555; }
QPushButton { font-size:15px; font-weight:bold; min-height:40px; border-radius:6px; padding:0 10px;
              border:1px solid #c9b993; background:#fff; color:#333; }
QPushButton:hover { background:#f3ecdc; }
QPushButton#start { background:#0b7a3e; color:white; border:none; }
QPushButton#start[running="true"] { background:#8a8a8a; }
QPushButton#side[side="red"] { color:#c62828; border:2px solid #c62828; }
QPushButton#side[side="black"] { color:#222; border:2px solid #222; }
QPushButton#hintbtn { background:#f6c344; border:none; color:#3a2a00; }
"""


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("panel"); self.setWindowTitle("象棋AI助手")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.settings = Settings.load()
        self.overlay = ArrowOverlay(); self.worker = None; self.snap = None; self.best = None; self.last_hint = None
        self.maps = screen_maps(QApplication.instance())
        self.recognizer = Recognizer(ROOT / "data/skin.npz")
        self.diag = Diagnostics(ROOT)

        box = QVBoxLayout(self); box.setContentsMargins(14, 10, 14, 12); box.setSpacing(6)
        self.hint = QLabel("—"); self.hint.setObjectName("hint"); self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel("点击「开始」，程序会自动找到棋盘并在轮到你时提示最佳走法。")
        self.status.setObjectName("status"); self.status.setWordWrap(True); self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.hint); box.addWidget(self.status)
        row = QHBoxLayout(); row.setSpacing(8)
        self.start_btn = QPushButton("开始"); self.start_btn.setObjectName("start")
        self.side_btn = QPushButton(); self.side_btn.setObjectName("side")
        self.hint_btn = QPushButton("提示走法"); self.hint_btn.setObjectName("hintbtn")
        for b in (self.start_btn, self.side_btn, self.hint_btn): row.addWidget(b, 1)
        box.addLayout(row)
        self.start_btn.clicked.connect(self.toggle)
        self.side_btn.clicked.connect(self.toggle_side)
        self.hint_btn.clicked.connect(self.hint_now)
        self.setStyleSheet(STYLE); self.update_side_button()
        self.setFixedWidth(340)

        if len(self.settings.geometry) == 4: self.move(self.settings.geometry[0], self.settings.geometry[1])
        else:
            x, y, w, h = self.maps[0].logical; self.move(x + w - 380, y + 60)

        self.engine = EngineService(self.settings.engine(), self.settings.movetime_ms, self.settings.threads or None,
                                    self.settings.hash_mb, parent=self)
        self.engine.result.connect(self.on_best); self.engine.failed.connect(self.on_engine_failed)
        self.engine.start()
        QTimer.singleShot(0, lambda: exclude_from_capture(self))

    # ---- buttons ------------------------------------------------------------
    def update_side_button(self):
        side = self.settings.side
        self.side_btn.setText("我执红" if side == "red" else "我执黑")
        self.side_btn.setProperty("side", side); self.side_btn.style().unpolish(self.side_btn); self.side_btn.style().polish(self.side_btn)

    def toggle(self):
        if self.worker: self.stop("已停止。")
        else: self.start()

    def start(self, hint=False):
        if self.worker: return
        self.maps = screen_maps(QApplication.instance())
        monitors = [dict(m.rect(), name=m.name) for m in self.maps]
        saved = None
        if self.settings.grid:
            try: saved = Grid.from_dict(self.settings.grid)
            except (ValueError, KeyError, TypeError): saved = None
        self.worker = CoachWorker(self.recognizer, self.settings.side, saved, monitors, self, diag=self.diag)
        self.worker.status.connect(self.set_status)
        self.worker.position.connect(self.on_position)
        self.worker.board_found.connect(self.on_board_found)
        self.worker.stopped.connect(self.stop)
        if hint: self.worker.request_hint()
        self.worker.start()
        self.start_btn.setText("停止"); self.start_btn.setProperty("running", "true")
        self.start_btn.style().unpolish(self.start_btn); self.start_btn.style().polish(self.start_btn)
        self.hint.setText("—"); self.set_status("正在寻找棋盘…")

    def stop(self, message=""):
        w = self.worker; self.worker = None
        if w:
            w.stop(); w.wait(3000)
        self.engine.stop_search(); self.overlay.clear(); self.snap = None
        self.start_btn.setText("开始"); self.start_btn.setProperty("running", "false")
        self.start_btn.style().unpolish(self.start_btn); self.start_btn.style().polish(self.start_btn)
        self.hint.setText("—")
        if message: self.set_status(message)

    def toggle_side(self):
        self.settings.side = "black" if self.settings.side == "red" else "red"
        self.update_side_button(); self.save()
        if self.worker: self.worker.set_side(self.settings.side)
        if self.snap: self.on_position(self.snap)

    def hint_now(self):
        if not self.worker: self.start(hint=True)
        else:
            self.set_status("正在读取当前局面…"); self.worker.request_hint()

    # ---- worker / engine events ---------------------------------------------
    def set_status(self, text):
        self.status.setText(text)
        if "遮挡" in text: self.overlay.clear()       # never draw over a pop-up

    def on_board_found(self, grid):
        self.settings.grid = grid.to_dict(); self.save()

    def on_position(self, snap):
        self.snap = snap; self.best = None; self.overlay.clear()
        mine = snap.turn == self.settings.side
        if not snap.board.legal_moves(snap.turn):
            self.engine.stop_search()
            self.hint.setText("对局结束"); self.set_status("你已无棋可走。" if mine else "对方已无棋可走，你赢了！")
            return
        if mine and self.last_hint and self.last_hint[0] == (snap.key, self.settings.side):
            self.on_best(snap.key, self.last_hint[1]); return        # same position again: same advice
        if mine:
            self.hint.setText("思考中…"); self.set_status("轮到你走棋")
            # Opening: pick among near-equal good moves so games are not all the same.
            ply = snap.ply
            margin = (45 if ply < 2 else 35) if snap.exact and ply < OPENING_PLIES else 0
            self.engine.request(snap.key, snap.base_fen, snap.moves, variety=margin, seen=snap.seen)
        else:
            self.engine.ponder(snap.base_fen, snap.moves)       # warm up while the opponent thinks
            self.hint.setText("—"); self.set_status("等待对方走棋…")

    def on_best(self, key, move):
        snap = self.snap
        if not snap or key != snap.key or snap.turn != self.settings.side: return
        if not move or not snap.board.legal_move(move, snap.turn):
            self.hint.setText("—"); self.set_status("引擎没有给出可用着法"); return
        # Last safety net: the screen right now must show exactly the position the advice is for.
        w = self.worker
        if w is not None and w.latest_colors is not None and w.red_bottom == snap.red_bottom and any(
                seen != known and not (i in snap.unseen and seen is None)
                for i, (seen, known) in enumerate(zip(w.latest_colors, snap.board.colors()))):
            self.diag.event(f"hint {move} withheld: screen differs from tracked position {snap.board.fen(snap.turn)}")
            self.hint.setText("—"); self.set_status("画面与记录的局面不一致，正在重新读取…")
            w.request_recheck(); return
        self.diag.event(f"hint {move} {snap.board.notation(move)} for {snap.board.fen(snap.turn)} ply={snap.ply}")
        self.best = move; self.last_hint = ((key, self.settings.side), move)
        self.hint.setText(snap.board.notation(move)); self.set_status("轮到你走棋 · 按箭头走")
        (a, b) = parse_move(move)
        points = [snap.grid.point(*orient(c, r, snap.red_bottom)) for c, r in (a, b)]
        mapping = next((m for m in self.maps if m.name == snap.grid.monitor), self.maps[0])
        self.overlay.show_arrow(mapping, points, snap.grid.spacing)

    def on_engine_failed(self, message):
        self.set_status("引擎问题：" + message)

    # ---- misc -----------------------------------------------------------------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act = QAction("手动框选棋盘（自动找不到时）", self); act.triggered.connect(self.select_region); menu.addAction(act)
        logs = QAction("打开诊断记录（识别出错时发给开发者）", self); logs.triggered.connect(self.open_diag); menu.addAction(logs)
        menu.exec(event.globalPos())

    def open_diag(self):
        import os
        if self.diag.folder is not None: os.startfile(str(self.diag.folder))

    def select_region(self):
        self.stop(); self.hide()
        QTimer.singleShot(250, self._select_region)

    def _select_region(self):
        from .selection import Selector
        from .vision import detect_grids
        try:
            self.maps = screen_maps(QApplication.instance())
            mapping = self.maps[0]
            for m in self.maps:
                x, y, w, h = m.logical
                if x <= self.geometry().center().x() < x + w and y <= self.geometry().center().y() < y + h: mapping = m
            image = grab(mapping.rect()); dialog = Selector(image, mapping)
            if dialog.exec() != QDialog.DialogCode.Accepted: return
            r = dialog.selected; ox, oy = r["left"] - mapping.physical[0], r["top"] - mapping.physical[1]
            grids = detect_grids(image[oy:oy + r["height"], ox:ox + r["width"]], (r["left"], r["top"]), mapping.name)
            if not grids:
                self.set_status("框选区域里没有识别到棋盘，请包含整个棋盘再试。"); return
            self.settings.grid = grids[0].to_dict(); self.save()
            self.set_status("已记住棋盘位置。"); self.start()
        finally:
            self.show()

    def save(self):
        g = self.geometry(); self.settings.geometry = [g.x(), g.y(), g.width(), g.height()]
        try: self.settings.save()
        except OSError as e: self.set_status("保存设置失败：" + str(e))

    def closeEvent(self, event):
        self.stop(); self.save()
        self.engine.shutdown(); self.engine.wait(3000)
        self.overlay.close(); event.accept()


def run():
    app = QApplication(sys.argv); app.setApplicationName("象棋AI助手")
    font = Path("C:/Windows/Fonts/msyh.ttc")
    if font.exists(): QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet("* { font-family:'Microsoft YaHei'; }")
    w = MainWindow(); w.show(); return app.exec()
