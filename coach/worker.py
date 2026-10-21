"""Background loop: find the board, follow every move, publish positions."""
import copy
import math
from collections import deque
import time
import threading
from dataclasses import dataclass
import numpy as np
import cv2
import mss
from PySide6.QtCore import QThread, Signal
from .board import Board, other
from .tracker import Tracker, GameState, INITIAL, advance, occlusion, MAX_UNSEEN
from .diag import describe, colours_text
from .vision import detect_grids, Observer, Recognizer, Grid, Observation

INTERVAL = .06         # seconds between screen samples
STALL = 4.0            # seconds without a settled picture before the board is read afresh


@dataclass
class Snapshot:
    """Immutable view of the tracked game handed to the GUI."""
    board: Board
    turn: str
    base_fen: str
    moves: tuple
    red_bottom: bool
    grid: Grid
    key: tuple
    exact: bool
    ply: int = 0
    unseen: tuple = ()      # points holding a known piece that is not detected right now
    seen: frozenset = frozenset()   # earlier positions of the game (avoid repeating them)


def _near(a, b):
    return a.monitor == b.monitor and max(math.dist(p, q) for p, q in zip(a.corners, b.corners)) < a.spacing * .3


class CoachWorker(QThread):
    status = Signal(str)
    position = Signal(object)
    board_found = Signal(object)        # Grid
    stopped = Signal(str)

    def __init__(self, recognizer, side, saved_grid=None, monitors=None, parent=None, diag=None):
        super().__init__(parent)
        self.recognizer = recognizer; self.side = side; self.grid = None; self.saved = saved_grid
        self.monitors = monitors or []          # list of physical rect dicts with "name"
        self.running = True; self.hint_requested = threading.Event()
        self.tracker = Tracker(stable_frames=2); self.last_thumb = None; self.last_obs = None; self.red_bottom = True; self.observer = None; self.rect = None
        self.sct = None; self.mismatch_since = 0.0
        self.diag = diag; self.recheck_requested = threading.Event()
        self.recent = deque(maxlen=2); self.smoothed = None
        self.latest_colors = None          # smoothed, oriented colours of the newest frame (GUI check)
        self.last_image = None; self.last_progress = 0.0; self.last_full = 0.0; self.refused_since = 0.0

    # ---- GUI side ---------------------------------------------------------
    def request_hint(self):
        self.hint_requested.set()

    def request_recheck(self):
        """GUI found the screen and the tracked game disagree: read the board again."""
        self.recheck_requested.set()

    def set_side(self, side):
        self.side = side

    def stop(self):
        self.running = False

    # ---- helpers ----------------------------------------------------------
    def grab(self, rect):
        # BGRA -> contiguous BGR (a strided view makes every OpenCV call copy the whole frame)
        return cv2.cvtColor(np.asarray(self.sct.grab(rect)), cv2.COLOR_BGRA2BGR)

    def _bounds(self, grid):
        for m in self.monitors:
            if m["name"] == grid.monitor: return m
        return None

    def _use_grid(self, grid):
        self.grid = grid; self.rect = grid.capture_rect(self._bounds(grid)); self.last_obs = None
        self.recent.clear(); self.smoothed = None
        self.observer = Observer(grid, self.rect, self.recognizer.red_threshold)

    def _plausible(self, obs):
        reds = sum(c == "red" for c in obs.screen); blacks = sum(c == "black" for c in obs.screen)
        return 1 <= reds <= 16 and 1 <= blacks <= 16 and reds + blacks >= 3

    def find_board(self):
        """Search every monitor for the board.

        While a game is being followed, a location is only accepted when it shows
        that game (window dragged) -- never a lattice shifted by a pop-up.
        """
        self.status.emit("正在寻找棋盘…")
        cands = []
        for m in self.monitors:
            if not self.running: return False
            image = self.grab(m)
            for grid in detect_grids(image, (m["left"], m["top"]), m["name"])[:4]:
                self._use_grid(grid)
                rect = self.rect
                sub = image[rect["top"] - m["top"]:rect["top"] - m["top"] + rect["height"],
                            rect["left"] - m["left"]:rect["left"] - m["left"] + rect["width"]]
                obs = self.observer.observe(sub)
                if self._plausible(obs) and self._aligned(obs) and self._readable(obs):
                    cands.append((sum(c is not None for c in obs.screen), grid, obs))
        if self.saved is not None and not any(_near(g, self.saved) for _, g, _ in cands):
            self._use_grid(self.saved)
            try:
                obs = self.observer.observe(self.grab(self.rect))
                if self._plausible(obs) and self._aligned(obs): cands.append((sum(c is not None for c in obs.screen), self.saved, obs))
            except Exception:
                pass
        st = self.tracker.state
        if st is not None:
            fits = [c for c in cands if self._fits(st, c[2])]
            if fits: cands = fits
            elif time.monotonic() - self.mismatch_since < 20: cands = []   # covered: keep waiting
            else: self.tracker.reset(None)                                   # a different game now
        if not cands:
            self.grid = None; self.observer = None; return False
        best = max(c[0] for c in cands)
        tied = [c for c in cands if c[0] >= best - 1]
        # Several lattices fit equally when some rows are hidden: prefer the known location.
        pick = next((c for c in tied if self.saved is not None and _near(c[1], self.saved)), tied[0])
        self._use_grid(pick[1]); self.saved = pick[1]; self.board_found.emit(pick[1]); return True

    def _fits(self, st, obs):
        """Does this view show the followed game (possibly moved on, or partly covered)?"""
        target = st.board.colors()
        for rb in (self.red_bottom, not self.red_bottom):
            colors = obs.oriented(rb)
            if colors == target or colors == INITIAL.colors() or occlusion(target, colors) or                     advance(copy.deepcopy(st), colors) is not None:
                self.red_bottom = rb; return True
        return False

    @staticmethod
    def _aligned(obs):
        """Pieces sit centred on the lattice (fails when the board window moved)."""
        cov = [obs.coverage[i] for i, c in enumerate(obs.screen) if c]
        return bool(cov) and float(np.mean(cov)) >= .85

    def _readable(self, obs):
        for rb in (True, False):
            if obs.oriented(rb) == INITIAL.colors(): return True
        # Both kings must be identifiable for any other position.
        reds = [i for i, c in enumerate(obs.screen) if c == "red"]; blacks = [i for i, c in enumerate(obs.screen) if c == "black"]
        def palace(ix, bottom):
            return any(3 <= i % 9 <= 5 and ((i // 9 >= 7) if bottom else (i // 9 <= 2)) for i in ix)
        return (palace(reds, True) and palace(blacks, False)) or (palace(reds, False) and palace(blacks, True))

    def read_position(self, image, obs, turn_hint=None):
        """Initial state from one frame: opening pattern or full recognition."""
        for rb in (True, False):
            colors = obs.oriented(rb); start = INITIAL.colors()
            missing = {i for i, (o, e) in enumerate(zip(colors, start)) if o != e}
            # The opening, possibly with a piece or two not detected yet: follow it exactly.
            if all(colors[i] is None for i in missing) and len(missing) <= MAX_UNSEEN:
                self.red_bottom = rb
                if not missing:
                    self.recognizer.learn(self.observer, image, INITIAL, rb, obs)
                    self.observer.red_threshold = self.recognizer.red_threshold
                st = GameState.opening(); st.unseen = set(missing)
                return st
        board, rb, _ = self.recognizer.recognize(self.observer, image, obs)
        if board.king("red") is None or board.king("black") is None: return None
        self.red_bottom = rb
        if board.in_check(self.side) and not board.in_check(other(self.side)): turn = self.side
        elif board.in_check(other(self.side)) and not board.in_check(self.side): turn = other(self.side)
        else: turn = turn_hint or self.side
        return GameState.from_position(board, turn)

    def publish(self, why="position"):
        st = self.tracker.state
        snap = Snapshot(st.board.copy(), st.turn, st.base_fen, tuple(st.moves), self.red_bottom, self.grid,
                        (st.base_fen, tuple(st.moves), st.turn), st.exact, st.ply, tuple(sorted(st.unseen)),
                        frozenset(st.seen))
        self.record(why)
        self.position.emit(snap)

    def record(self, why, extra=None):
        """Diagnostics (never allowed to break tracking)."""
        try: self._record(why, extra)
        except Exception: pass

    def _record(self, why, extra=None):
        if self.diag is None: return
        st = self.tracker.state
        info = {"why": why, "red_bottom": self.red_bottom, "side": self.side,
                "grid": self.grid.to_dict() if self.grid else None,
                "seen": colours_text(self.latest_colors) if self.latest_colors else None}
        if st is not None:
            info.update(fen=st.board.fen(st.turn), exact=st.exact, ply=st.ply, moves=st.moves[-12:],
                        board=describe(st.board, st.turn), unseen=sorted(st.unseen))
        if extra: info.update(extra)
        stem = self.diag.capture(why, self.last_image, info)
        self.diag.event(f"{why}: {info.get('fen', '-')} exact={info.get('exact')} [{stem}]")

    # ---- main loop --------------------------------------------------------
    def run(self):
        self.sct = getattr(mss, "MSS", mss.mss)()
        try:
            self._loop()
        except Exception as e:      # keep the GUI alive, report the reason
            self.stopped.emit("自动辅助出错：" + str(e))
        finally:
            self.sct.close()

    def _loop(self):
        bad_since = None; last_search = 0.0; said = None

        def say(text):
            nonlocal said
            if text != said: said = text; self.status.emit(text)

        while self.running:
            t0 = time.monotonic()
            if self.grid is None or self.observer is None:
                if t0 - last_search < 1.5: self._sleep(t0); continue
                last_search = t0
                if not self.mismatch_since: self.mismatch_since = t0
                if not self.find_board():
                    say("棋盘被遮挡，等待恢复…" if self.tracker.state else "没有找到棋盘，请把象棋窗口完整显示在屏幕上")
                    continue
                self.mismatch_since = 0.0; bad_since = None
                say("已找到棋盘" if self.tracker.state else "已找到棋盘，正在读取局面…")
            image = self.grab(self.rect); self.last_image = image
            obs = self._smooth(self._observe(image))

            if not (self._plausible(obs) and self._aligned(obs)):
                bad_since = bad_since or t0
                if t0 - bad_since > 1.5:
                    say("棋盘被遮挡或已移动，正在重新寻找…")
                    if self.saved is None: self.saved = self.grid
                    self.grid = None; self.observer = None; bad_since = None; last_search = 0.0
                self._sleep(t0); continue
            bad_since = None

            st = self.tracker.state
            if st is None:
                st = self.read_position(image, obs)
                if st is None:
                    say("无法读取局面，正在重新寻找棋盘…"); self.grid = None; self.observer = None
                    self._sleep(t0); continue
                self.tracker.reset(st, obs.colors); self.publish("read"); said = None; self.last_progress = t0
            elif self.hint_requested.is_set():
                self.hint_requested.clear()
                if occlusion(st.board.colors(), obs.colors):
                    say("棋盘被遮挡，请先关闭弹窗"); self._sleep(t0); continue
                if not st.exact or st.board.colors() != obs.colors:
                    st = self._reread(image, obs, st) or st
                # "提示走法" means: it is my move now (except at a fresh opening).
                if not (st.exact and st.ply == 0): st.set_turn(self.side)
                self.tracker.reset(st, obs.colors); self.publish("hint-button"); said = None; self.last_progress = t0
            elif self.recheck_requested.is_set():
                self.recheck_requested.clear()
                if st.board.colors() != obs.colors and not occlusion(st.board.colors(), obs.colors):
                    fresh = self._reread(image, obs, st)
                    if fresh is not None:
                        fresh.set_turn(st.turn)
                        self.tracker.reset(fresh, obs.colors); self.publish("recheck"); said = None
                else:
                    self.publish("recheck-same")
                self.last_progress = t0
            else:
                result = self.tracker.feed(obs.colors, t0)
                if result != "wait": self.last_progress = t0
                if result == "unseen":
                    self.record("unseen", {"points": sorted(st.unseen)})
                if result == "occluded":
                    if said is None or "遮挡" not in said: self.record("occluded")
                    say("棋盘被遮挡，等待恢复…")
                elif result == "opening":
                    self.recognizer.learn(self.observer, image, INITIAL, self.red_bottom, obs)
                if result in ("moved", "undo", "opening"):
                    self.publish(result); said = None
                elif result == "same" and said and "遮挡" in said:
                    said = None; self.publish("uncovered")             # pop-up closed: show the hint again
                elif result == "unknown" or (result == "wait" and t0 - self.last_progress > STALL
                                             and st.board.colors() != obs.colors):
                    # unexplained change, or a picture that never settles: read the board afresh
                    fresh = self._reread(image, obs, st)
                    self.last_progress = t0
                    if fresh is not None:
                        self.tracker.reset(fresh, obs.colors); self.publish("reread"); said = None
                    else:
                        self.tracker.unexplained_since = t0          # try again later, keep the game
                        self.record("reread-refused")
            self._sleep(t0)

    def _smooth(self, obs):
        """Per point, a change counts only once two frames in a row agree.

        A blinking effect then keeps its point at the old value instead of
        making the whole board "unsettled", so tracking never stalls.
        """
        cur = obs.screen; prev = self.recent[-1] if self.recent else None
        self.recent.append(cur)
        if self.smoothed is None or prev is None:
            screen = cur
        else:
            screen = tuple(c if c == p else s for c, p, s in zip(cur, prev, self.smoothed))
        self.smoothed = screen
        out = Observation((), screen, obs.coverage, obs.redness, obs.lift)
        out.colors = out.oriented(self.red_bottom); self.latest_colors = out.colors
        return out

    def _reread(self, image, obs, st):
        """Full recognition, refused when it would lose pieces of the followed game."""
        fresh = self.read_position(image, obs, self.side)
        if fresh is None: return None
        if st is not None and not fresh.exact:
            if occlusion(st.board.colors(), obs.oriented(self.red_bottom)):
                return None                                   # board partly hidden: keep the game
            # Far fewer pieces than the followed game: an effect is covering them, not a new game.
            if len(st.board.pieces()) - len(fresh.board.pieces()) >= 3:
                now = time.monotonic(); self.refused_since = self.refused_since or now
                if now - self.refused_since < 10: return None   # persists 10 s: it really is another position
        self.refused_since = 0.0
        return fresh

    def _observe(self, image):
        """Full per-point analysis only when the picture actually changed."""
        thumb = cv2.resize(image, (max(8, image.shape[1] // 3), max(8, image.shape[0] // 3)), interpolation=cv2.INTER_AREA).astype(np.int16)
        now = time.monotonic()
        same = (self.last_obs is not None and self.last_thumb is not None and thumb.shape == self.last_thumb.shape
                and int(np.abs(thumb - self.last_thumb).max()) < 6 and now - self.last_full < .5)
        self.last_thumb = thumb
        if same:
            obs = self.last_obs; obs.colors = obs.oriented(self.red_bottom); return obs
        self.last_obs = self.observer.observe(image, self.red_bottom); self.last_full = now
        return self.last_obs

    def _sleep(self, t0):
        left = INTERVAL - (time.monotonic() - t0)
        if left > 0: time.sleep(left)
