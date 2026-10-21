# Xiangqi Coach

A Windows overlay that helps beginners learn Chinese chess (xiangqi). It watches the board of the xiangqi program on your screen, follows every move automatically, and **when it is your turn it draws the best move as an arrow right on the board**, with the move in Chinese notation (e.g. 炮二平五). Moves come from [Pikafish](https://github.com/official-pikafish/Pikafish), one of the strongest open-source xiangqi engines.

It only reads screen pixels. It never touches, reads or controls the game program and never moves for you.

> **Download**: get the portable build from **Releases**, unzip it and run `象棋AI助手.exe` – no Python needed. Windows 10 (2004+) / 11, 64-bit.

## Usage

The window has three buttons:

| Button | What it does |
| --- | --- |
| **我执红 / 我执黑** (I play Red / Black) | toggle the side you play |
| **开始 / 停止** (Start / Stop) | find the board, follow the game, show an arrow on your turns |
| **提示走法** (Hint) | "it is my move now" – read the board and suggest a move immediately |

1. Open your xiangqi program so the whole board is visible; put the helper window beside it.
2. Pick your side, press **Start**.
3. On your turn a green arrow appears (green ring = piece to move, dashed yellow ring = target) and the move is shown in the window.

Starting at the opening position is best: the game is then followed exactly, and the piece style of this program is learned automatically. The JJ Xiangqi (JJ象棋) battle skin is built in, so starting mid-game works there too.

Right-click the window for **manual board selection** (if automatic search fails) and **open diagnostics** (captures and decisions to attach to a bug report).

## How it works

- **Board finding** – Hough circles → fit of the 9×10 lattice the pieces sit on, refined on precisely centred pieces. No manual calibration.
- **Per-frame observation** – every lattice point is read as *empty / red / black* (rim edge coverage, face texture, ink colour). Lifted (selected) and enlarged pieces are handled.
- **Move tracking** – piece identities come from the known previous position; the legal move (or two, if the opponent replied instantly) that turns it into the observed pattern is found. Take-backs, new games, sliding animations, pop-ups and capture effects covering pieces are handled; a piece that is only momentarily undetected is kept, never dropped.
- **Piece recognition** (only for a mid-game start) – stroke-direction (HOG) templates of the built-in / learned skins and of 20+ Chinese fonts, look-alike voting on the same board, then an assignment constrained by the rules (one king each, advisor/elephant points, piece counts).
- **Safety net** – an arrow is only drawn if the screen at that moment shows exactly the position the advice is for.
- **Playing style** – the engine returns its top lines and the suggestion is picked so that it
  - varies the opening (first 8 moves) among near-equal sound moves,
  - avoids repeating earlier positions (long chase / perpetual check is penalised in xiangqi),
  - avoids trades unless clearly winning; when clearly winning it prefers forcing moves and trades, and always plays the quickest mate.
- **Engine** – a persistent Pikafish process that ponders while the opponent thinks; 1 s per move by default.

## Limitations

- Pieces must be round (true for virtually all xiangqi programs).
- For an unknown skin started mid-game, a piece type can occasionally be misread; start at the opening so the skin is learned.
- The game clock of the xiangqi program is not read.
- If 3 or more moves are played while the board is covered, the position is read again from scratch.

## Run from source

Windows 10/11 64-bit, Python 3.11.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\install_engine.py   # downloads the official Pikafish release, verifies SHA-256
.\.venv\Scripts\python.exe main.py
```

Settings live in `data/config.json` (`movetime_ms` default 1000, `threads` 0 = auto, `hash_mb`). The learned skin is `data/skin.npz` – delete it after switching to a different xiangqi program.

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q                 # unit + end-to-end tests
.\.venv\Scripts\python.exe tools\desktop_smoke.py red   # real desktop: synthetic board + real GUI + real engine
.\.venv\Scripts\python.exe tools\desktop_jj.py          # real desktop replay of JJ screenshots
.\.venv\Scripts\python.exe tools\eval_recognition.py    # recognition accuracy on the screenshots
.\.venv\Scripts\python.exe tools\make_skin.py NAME opening.png   # add a built-in skin
.\.venv\Scripts\python.exe tools\build_portable.py      # portable build (PyInstaller)
```

| Module | Role |
| --- | --- |
| `coach/vision.py` | board finding, per-point observation, piece recognition |
| `coach/tracker.py` | move inference, take-backs, occlusion / unseen pieces |
| `coach/worker.py` | background loop: capture → observe → track → publish |
| `coach/engine.py` | persistent Pikafish client, pondering |
| `coach/style.py` | choosing the suggestion among the engine's top lines |
| `coach/board.py` | rules, move generation, Chinese notation |
| `coach/app.py`, `coach/overlay.py` | three-button window, arrow on the board |
| `coach/diag.py` | diagnostic captures and event log |

Test screenshots are in `tests/fixtures/` with their positions in `tests/fixtures/truth.json`. See [TEST_REPORT.md](TEST_REPORT.md).

## License

MIT for this project's code (see `LICENSE`). Pikafish is GPLv3 and runs as a separate program; it is not stored in this repository – `tools/install_engine.py` downloads it from the official release, and the portable build ships it with its license and matching source. Qt (PySide6) is LGPLv3, see `third-party-notices/`. Screenshots in `tests/fixtures/` are used for recognition tests only; the game artwork belongs to its owners, and other players' names have been blurred.
