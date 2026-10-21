# Test report – v0.5.1

Environment: Windows 11 (build 26200), 2560×1600 at 150 % scaling, Python 3.11.9, PySide6 6.12, OpenCV 4.14, Pikafish 2026-09-06.

## Automated tests: 116 passed

`.\.venv\Scripts\python.exe -m pytest -q`

| Area | Covered |
| --- | --- |
| Rules & notation | move generation (44 opening moves), checks, flying general, 400 random plies, Chinese notation incl. 前/后 |
| Real screenshots (18 JJ Xiangqi screens) | lattice position, empty/red/black for every point, full piece recognition with the built-in skin (every piece correct), fonts-only fallback (≤ 1 piece off per board), learned skin |
| Synthetic skins (4 skins × red top/bottom) | grid, colours, orientation, recognition with lifted pieces, glow rings and markers |
| Tracking | every move of random games, instant replies (2 plies), wrong turn guess, take-backs, new game, slide pausing on a point, missed/unseen pieces, consistent engine input after turn changes |
| End-to-end (real worker thread) | whole games with animations, board window dragged, profile pop-ups during play, blinking effects, an edge pawn hidden for several moves |
| Engine | cancel, newest-request-only, ponder interrupted, crash recovery, real Pikafish, opening variety |
| GUI | arrow withheld when the screen differs from the tracked position |

## Recognition accuracy (real screenshots)

18 JJ Xiangqi screenshots (day/night battle scenes, high resolution, end-of-game review board, many glow rings, lifted/enlarged pieces, overlapping pieces) plus 50 % downscaled copies:

- normal path (built-in skin + fonts + rules): **every piece correct**; the skin templates come from opening screenshots only, mid-game screenshots are independent;
- fonts-only fallback (unknown skin): 3 wrong pieces over 28 boards;
- empty/red/black per point (what tracking uses): all correct.

A neural-network classifier trained on 35 000 synthetic pieces reached 99 % on synthetic data but was worse than the templates on the real screenshots, so it was not adopted.

## Real desktop tests (real capture, real GUI, real Pikafish)

- `tools/desktop_smoke.py red` / `black`: 5 consecutive turns each; every hint legal, arrow on the right points, ~1.2 s from the opponent's move to the hint, first hint ~4.4 s after Start.
- `tools/desktop_jj.py`: JJ screenshots replayed at 70 % size; opening and two mid-game positions read exactly, hints given.

## Portable build

`tools/build_portable.py` → PyInstaller one-folder build, copied to a path with Chinese characters and spaces and started with Python/Qt variables removed and `PATH` limited to the Windows folders: window opens, bundled engine starts, clean exit.

## Not yet verified

- Long live games in the real JJ Xiangqi client.
- Other PCs, multiple monitors, Windows 10.
