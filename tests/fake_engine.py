"""Minimal UCI stand-in for tests. Modes: ok, slow (long searches wait for stop), crash, none."""
import sys

mode = sys.argv[1]
searching = False
for line in sys.stdin:
    line = line.strip()
    if line == "uci": print("id name TestOnly\nuciok", flush=True)
    elif line == "isready": print("readyok", flush=True)
    elif line.startswith("go "):
        if mode == "crash": raise SystemExit(2)
        elif mode == "none": print("bestmove (none)", flush=True)
        elif mode == "slow" and int(line.split()[-1]) > 2000: searching = True
        elif mode == "slow": print("bestmove h2e2", flush=True)
        else: print("info depth 8 score cp 23 pv h2e2\nbestmove h2e2", flush=True)
    elif line == "stop" and searching:
        searching = False; print("bestmove b0c2", flush=True)
    elif line == "quit": break
