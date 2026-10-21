"""Persistent Pikafish (UCI) client running in its own thread."""
import math
import os
import queue
import random
import re
import subprocess
import threading
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from .board import Board
from .style import choose


class EngineError(RuntimeError):
    pass


class UciEngine:
    def __init__(self, path, threads=None, hash_mb=256, command=None):
        self.path = Path(path)
        self.threads = threads or max(1, min(8, (os.cpu_count() or 2) // 2))
        self.hash_mb = hash_mb
        self.command = command or [str(self.path)]
        self.proc = None; self.lines = None; self.name = ""; self.multipv = 1
        self.last_lines = []        # [(move, score, pv)] of the last search, best first

    def _read(self, proc, lines):
        try:
            for line in proc.stdout: lines.put(line.strip())
        finally:
            lines.put(None)

    def send(self, line):
        if not self.proc or self.proc.poll() is not None: raise EngineError("引擎已退出")
        try:
            self.proc.stdin.write(line + "\n"); self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise EngineError("引擎通信中断") from e

    def next_line(self, timeout):
        try: line = self.lines.get(timeout=timeout)
        except queue.Empty: return ""
        if line is None: raise EngineError("引擎异常退出")
        return line

    def wait_for(self, token, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.next_line(.1)
            if line.startswith("id name "): self.name = line[8:]
            if line == token: return
        raise EngineError("引擎响应超时")

    def start(self):
        self.close()
        if not self.path.exists() and self.command == [str(self.path)]:
            raise EngineError("找不到引擎：" + str(self.path))
        try:
            self.proc = subprocess.Popen(self.command, cwd=str(self.path.parent), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace", bufsize=1,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.proc = None; raise EngineError("无法启动引擎：" + str(e)) from e
        self.lines = queue.Queue()
        threading.Thread(target=self._read, args=(self.proc, self.lines), daemon=True).start()
        self.send("uci"); self.wait_for("uciok")
        self.send(f"setoption name Threads value {self.threads}")
        self.send(f"setoption name Hash value {self.hash_mb}")
        self.send("isready"); self.wait_for("readyok"); self.multipv = 1

    def search(self, base_fen, moves, movetime_ms, cancel, multipv=1):
        """Best move, or None when cancelled. Raises EngineError on failure.

        With multipv > 1 the top lines are kept in self.last_lines.
        """
        if not self.proc: self.start()
        if multipv != self.multipv:
            self.send(f"setoption name MultiPV value {multipv}"); self.multipv = multipv
        self.send("position fen " + base_fen + (" moves " + " ".join(moves) if moves else ""))
        self.send(f"go movetime {int(movetime_ms)}")
        deadline = time.monotonic() + movetime_ms / 1000 + 8; stopped = False
        lines = {}; self.last_lines = []
        while True:
            if cancel.is_set() and not stopped:
                self.send("stop"); stopped = True; deadline = time.monotonic() + 5
            if time.monotonic() > deadline: self.close(); raise EngineError("引擎响应超时")
            line = self.next_line(.03)
            if line.startswith("info ") and " pv " in line and " score " in line and "bound" not in line:
                m = re.search(r"\bdepth (\d+).*?\bscore (cp|mate) (-?\d+).*?\bpv (\S+)", line)
                k = re.search(r"\bmultipv (\d+)", line)
                if m:
                    value = int(m[3]) if m[2] == "cp" else (100000 - abs(int(m[3]))) * (1 if int(m[3]) > 0 else -1)
                    lines[int(k[1]) if k else 1] = (int(m[1]), m[4], value, line.split(" pv ", 1)[1].split())
            if line.startswith("bestmove"):
                if lines:
                    top = max(v[0] for v in lines.values()); best = {}
                    for d, mv, sc, pv in lines.values():      # one entry per move, deepest wins
                        if d >= top - 1 and (mv not in best or d > best[mv][0]): best[mv] = (d, sc, pv)
                    self.last_lines = sorted(((mv, sc, pv) for mv, (d, sc, pv) in best.items()), key=lambda t: -t[1])
                move = line.split()[1] if len(line.split()) > 1 else "(none)"
                if stopped: return None
                if not re.fullmatch(r"[a-i][0-9][a-i][0-9]", move): return ""
                return move

    def close(self):
        p = self.proc; self.proc = None
        if p is None: return
        try:
            if p.poll() is None:
                try: p.stdin.write("quit\n"); p.stdin.flush()
                except OSError: pass
                try: p.wait(timeout=1)
                except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=2)
        finally:
            for s in (p.stdin, p.stdout):
                try: s.close()
                except OSError: pass


def mirror(move):
    f = lambda ch: "abcdefghi"[8 - "abcdefghi".index(ch)]
    return f(move[0]) + move[1] + f(move[2]) + move[3]


def pick_varied(lines, rng, margin=35, temperature=18, symmetric=False):
    """Choose among near-equal top moves (opening variety). lines: [(move, score)] best first.

    On a left-right symmetric board mirrored moves count as one choice, so the
    different opening systems come up about equally often.
    """
    if not lines: return None
    best = lines[0][1]
    if abs(best) >= 90000: return lines[0][0]           # forced mate: never gamble
    pool = {}
    for m, sc, *_ in lines:
        if sc < best - margin: continue
        key = min(m, mirror(m)) if symmetric else m
        pool.setdefault(key, []).append((m, sc))
    groups = list(pool.values())
    weights = [math.exp((max(sc for _, sc in g) - best) / temperature) for g in groups]
    group = rng.choices(groups, weights)[0]
    return rng.choice(group)[0]


class EngineService(QThread):
    """Always keeps only the latest request; older searches are stopped.

    While the opponent thinks the engine "ponders" the current position, so
    the hash table is warm when our turn comes.
    """
    result = Signal(object, str)        # request key, best move ("" = no legal move)
    failed = Signal(str)
    ready = Signal(str)
    PONDER_MS = 15000

    def __init__(self, path, movetime_ms=1000, threads=None, hash_mb=256, command=None, parent=None):
        super().__init__(parent)
        self.engine = UciEngine(path, threads, hash_mb, command); self.movetime_ms = movetime_ms
        self.requests = queue.Queue(); self.cancel = threading.Event(); self.running = True
        self.rng = random.Random()

    def request(self, key, base_fen, moves, variety=0, seen=()):
        """variety: allowed loss (centipawns) for a varied opening choice; seen: earlier positions."""
        self.cancel.set(); self.requests.put((key, base_fen, list(moves), variety, frozenset(seen)))

    def ponder(self, base_fen, moves):
        self.cancel.set(); self.requests.put((None, base_fen, list(moves), -1, frozenset()))

    def stop_search(self):
        self.cancel.set(); self.requests.put(None)

    def shutdown(self):
        self.running = False; self.cancel.set(); self.requests.put(None)

    def run(self):
        try:
            self.engine.start(); self.ready.emit(self.engine.name)
        except EngineError as e:
            self.failed.emit(str(e))
        while self.running:
            item = self.requests.get()
            while not self.requests.empty(): item = self.requests.get()     # newest only
            if item is None or not self.running: continue
            self.cancel.clear()
            key, fen, moves, mode, seen = item
            try:
                if mode < 0:                                          # ponder
                    self.engine.search(fen, moves, self.PONDER_MS, self.cancel); continue
                move = self.engine.search(fen, moves, self.movetime_ms, self.cancel, 8 if mode else 5)
                if move and self.engine.last_lines:
                    board = Board.from_fen(fen); turn = "red" if fen.split()[1] == "w" else "black"
                    for m in moves: board = board.apply(m); turn = "black" if turn == "red" else "red"
                    move = choose(self.engine.last_lines, board, turn, seen, mode, self.rng) or move
                if move is not None and not self.cancel.is_set(): self.result.emit(key, move)
            except EngineError as e:
                self.failed.emit(str(e))
                try: self.engine.start()
                except EngineError: pass
        self.engine.close()
