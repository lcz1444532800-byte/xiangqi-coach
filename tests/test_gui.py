"""Main window safety: never draw an arrow for a position the screen does not show."""
from PySide6.QtCore import QObject, Signal
from coach.board import Board
from coach.vision import Grid
from coach.worker import Snapshot


class DummyEngine(QObject):
    result = Signal(object, str); failed = Signal(str); ready = Signal(str)
    def __init__(self, *a, **k): super().__init__(); self.requests = []
    def request(self, *a, **k): self.requests.append(a)
    def ponder(self, *a): pass
    def stop_search(self): pass
    def shutdown(self): pass
    def start(self): pass
    def wait(self, *a): return True


class DummyWorker:
    def __init__(self, colors): self.latest_colors = colors; self.red_bottom = True; self.rechecks = 0
    def request_recheck(self): self.rechecks += 1
    def stop(self): pass
    def wait(self, *a): return True


def window(qapp, monkeypatch, tmp_path):
    import coach.app as app
    from coach.config import Settings
    monkeypatch.setattr(app, "EngineService", DummyEngine)
    monkeypatch.setattr(app, "ROOT", tmp_path)
    monkeypatch.setattr(app.Settings, "load", classmethod(lambda cls, path=None: Settings(side="red")))
    monkeypatch.setattr(app.Settings, "save", lambda self, path=None: None)
    return app.MainWindow()


def snapshot(board):
    g = Grid([[100, 100], [580, 100], [580, 640], [100, 640]], .4, "")
    return Snapshot(board, "red", board.fen("red"), (), True, g, ("k",), False, 0)


def test_arrow_withheld_when_screen_differs(qapp, monkeypatch, tmp_path):
    w = window(qapp, monkeypatch, tmp_path)
    tracked = Board.initial(); screen = Board.initial().apply("a3a4")     # a pawn the tracker does not know about
    w.worker = DummyWorker(screen.colors())
    w.on_position(snapshot(tracked)); w.on_best(("k",), "h2e2")
    assert w.worker.rechecks == 1 and not w.overlay.isVisible() and w.best is None
    w.worker = None; w.close()


def test_arrow_shown_when_screen_matches(qapp, monkeypatch, tmp_path):
    w = window(qapp, monkeypatch, tmp_path)
    board = Board.initial(); w.worker = DummyWorker(board.colors())
    w.on_position(snapshot(board)); w.on_best(("k",), "h2e2")
    assert w.best == "h2e2" and w.hint.text() == "炮二平五" and w.worker.rechecks == 0
    w.overlay.clear(); w.worker = None; w.close()
