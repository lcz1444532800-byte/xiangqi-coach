import sys
import threading
import time
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from coach.board import Board, INITIAL_FEN
from coach.config import ROOT
import random
from coach.engine import UciEngine, EngineError, EngineService, pick_varied

FAKE = Path(__file__).with_name("fake_engine.py")
PIKAFISH = ROOT / "engine/pikafish.exe"


def fake(mode):
    return UciEngine(FAKE, 1, 16, command=[sys.executable, str(FAKE), mode])


def test_search_and_cancel():
    e = fake("ok")
    try:
        e.start(); assert e.search(INITIAL_FEN, [], 300, threading.Event()) == "h2e2"
        e.command = [sys.executable, str(FAKE), "slow"]; e.start()
        cancel = threading.Event(); threading.Timer(.2, cancel.set).start()
        assert e.search(INITIAL_FEN, [], 5000, cancel) is None      # stopped, result discarded
        assert e.proc is not None                                   # engine stays loaded
    finally: e.close()


def test_no_legal_move_and_crash():
    e = fake("none")
    try:
        e.start(); assert e.search(INITIAL_FEN, [], 300, threading.Event()) == ""
        e.command = [sys.executable, str(FAKE), "crash"]; e.start()
        with pytest.raises(EngineError): e.search(INITIAL_FEN, [], 300, threading.Event())
    finally: e.close()


def test_missing_engine():
    with pytest.raises(EngineError): UciEngine(ROOT / "engine/missing.exe").start()


def test_service_keeps_only_latest_request(qapp):
    svc = EngineService(FAKE, 300, 1, 16, command=[sys.executable, str(FAKE), "ok"])
    got = []
    svc.result.connect(lambda key, move: got.append((key, move)), Qt.ConnectionType.DirectConnection)
    svc.start()
    try:
        for i in range(5): svc.request(i, INITIAL_FEN, [])
        deadline = time.monotonic() + 10
        while not any(k == 4 for k, _ in got) and time.monotonic() < deadline: time.sleep(.05)
        assert got and got[-1] == (4, "h2e2")
    finally:
        svc.shutdown(); svc.wait(5000)


@pytest.mark.skipif(not PIKAFISH.exists(), reason="需要 Pikafish")
def test_real_pikafish_with_move_history():
    e = UciEngine(PIKAFISH, 2, 64)
    try:
        e.start(); assert "Pikafish" in e.name
        moves = ["h2e2", "h9g7"]
        best = e.search(INITIAL_FEN, moves, 500, threading.Event())
        b = Board.initial().apply("h2e2").apply("h9g7")
        assert b.legal_move(best, "red")
        # a hanging rook next to the red king is taken
        b = Board.from_fen("3k5/9/9/9/9/9/9/9/4r4/4K4 w")
        assert e.search(b.fen("red"), [], 500, threading.Event()) == "e0e1"
    finally: e.close()


def test_opening_variety_only_among_near_best():
    lines = [("h2e2", 26), ("g3g4", 23), ("b2e2", 22), ("b0c2", 13), ("i3i4", -40)]
    picks = {pick_varied(lines, random.Random(i)) for i in range(300)}
    assert {"h2e2", "g3g4", "b2e2"} <= picks and "i3i4" not in picks
    assert pick_varied([("a0a9", 99990), ("b0c2", 99980)], random.Random(0)) == "a0a9"   # mate: no gamble


def test_ponder_is_interrupted_by_a_real_request(qapp):
    svc = EngineService(FAKE, 300, 1, 16, command=[sys.executable, str(FAKE), "slow"])
    svc.PONDER_MS = 60000
    got = []
    svc.result.connect(lambda key, move: got.append((key, move)), Qt.ConnectionType.DirectConnection)
    svc.start()
    try:
        svc.ponder(INITIAL_FEN, []); time.sleep(.5)
        svc.request("mine", INITIAL_FEN, ["h2e2"])     # stops the ponder, then a normal 300 ms search
        deadline = time.monotonic() + 10
        while not got and time.monotonic() < deadline: time.sleep(.05)
        assert got == [("mine", "h2e2")]              # the ponder's own result is never shown as a hint
    finally:
        svc.shutdown(); svc.wait(5000)
