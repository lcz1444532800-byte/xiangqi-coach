"""Board localisation and piece recognition from plain screenshots.

Pipeline
1. detect_grids(): Hough circles -> fit the 9x10 lattice the pieces sit on.
2. Observer.observe(): per lattice point "empty / red piece / black piece".
   This is all the move tracker needs and is very robust on any skin.
3. Recognizer.recognize(): piece types, only needed when the game is not
   followed from the opening. Uses templates learned from this skin at the
   opening position, or generic font glyphs, and solves a constrained
   assignment (piece counts, palace, elephant/advisor points, pawns).
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import math
import cv2
import numpy as np
from .board import Board, LIMITS, placement_ok

HOME = Board.initial()

GLYPH_CHARS = {"k": "帅帥将將", "a": "仕士", "b": "相象", "n": "马馬傌", "r": "车車俥", "c": "炮砲包", "p": "兵卒"}
ASSETS = Path(__file__).resolve().parent / "assets"
P = 64          # occupancy patch size (patch spans one lattice spacing)
G = 128         # glyph patch size
LIFT = .3       # how far a selected piece may be drawn above its point (spacings)


def orient(col, row, red_bottom=True):
    """screen lattice <-> canonical board (an involution)."""
    return (col, row) if red_bottom else (8 - col, 9 - row)


# --------------------------------------------------------------------------
# Lattice
# --------------------------------------------------------------------------
@dataclass
class Grid:
    corners: list           # physical pixels of screen lattice TL, TR, BR, BL
    radius: float = 0.40    # piece radius / spacing
    monitor: str = ""

    def __post_init__(self):
        self.corners = [[float(x), float(y)] for x, y in self.corners]
        if len(self.corners) != 4: raise ValueError("需要四个角")
        tl, tr, br, bl = self.corners
        if tr[0] - tl[0] < 60 or bl[1] - tl[1] < 60: raise ValueError("棋盘过小")

    def point(self, col, row):
        u, v = col / 8, row / 9
        tl, tr, br, bl = self.corners
        return tuple((1 - u) * (1 - v) * tl[i] + u * (1 - v) * tr[i] + u * v * br[i] + (1 - u) * v * bl[i] for i in (0, 1))

    @property
    def spacing(self):
        tl, tr, br, bl = self.corners
        sx = (math.dist(tl, tr) + math.dist(bl, br)) / 16
        sy = (math.dist(tl, bl) + math.dist(tr, br)) / 18
        return (sx + sy) / 2

    def capture_rect(self, bounds=None):
        xs = [p[0] for p in self.corners]; ys = [p[1] for p in self.corners]; m = self.spacing * 0.75
        left, top = math.floor(min(xs) - m), math.floor(min(ys) - m)
        right, bottom = math.ceil(max(xs) + m), math.ceil(max(ys) + m)
        if bounds:
            bl, bt, bw, bh = bounds["left"], bounds["top"], bounds["width"], bounds["height"]
            left, top = max(left, bl), max(top, bt); right, bottom = min(right, bl + bw), min(bottom, bt + bh)
        return {"left": int(left), "top": int(top), "width": int(right - left), "height": int(bottom - top)}

    def shifted(self, dx, dy):
        return Grid([[x + dx, y + dy] for x, y in self.corners], self.radius, self.monitor)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        return cls(raw["corners"], raw.get("radius", 0.4), raw.get("monitor", ""))


def find_circles(gray, min_r, max_r, strictness=35):
    blur = cv2.medianBlur(gray, 5)
    found = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1, minDist=max(8, min_r * 1.5), param1=100,
                             param2=strictness, minRadius=int(min_r), maxRadius=int(max_r))
    return np.zeros((0, 3), np.float32) if found is None else found[0]


def _spacing(dist, lo, hi):
    dist = np.asarray(dist, np.float64)
    if len(dist) == 0 or hi <= lo: return None
    best = (0, None)
    for s in np.linspace(lo, hi, 300):
        k = np.round(dist / s); ok = (k >= 1) & (k <= 9)
        score = float(np.sum(np.exp(-(((dist - k * s) / s) / 0.05) ** 2) * ok))
        if score > best[0]: best = (score, s)
    return best[1]


def _fit_bilinear(points, cols, rows):
    u = np.asarray(cols, np.float64) / 8; v = np.asarray(rows, np.float64) / 9
    A = np.stack([np.ones_like(u), u, v, u * v], 1)
    coef, *_ = np.linalg.lstsq(A, np.asarray(points, np.float64), rcond=None)
    a, b, c, d = coef
    return [list(a), list(a + b), list(a + b + c + d), list(a + c)]


def line_evidence(gray, grid, offset=(0, 0)):
    """How much the lattice coincides with drawn board lines (tie-breaker)."""
    s = grid.spacing; h, w = gray.shape; total = []; ox, oy = offset
    for row in range(10):
        for col in range(9):
            for dc, dr in ((1, 0), (0, 1)):
                c2, r2 = col + dc, row + dr
                if c2 > 8 or r2 > 9 or (dr and row == 4 and 0 < col < 8): continue
                a = np.array(grid.point(col, row)) - (ox, oy); b = np.array(grid.point(c2, r2)) - (ox, oy)
                mid = (a + b) / 2; d = (b - a) / np.linalg.norm(b - a); n = np.array([-d[1], d[0]])
                vals = []
                for t in (-.12, -.06, 0, .06, .12):
                    q = mid + d * t * s
                    samples = [q + n * k * s * .05 for k in (-3, -2, 0, 2, 3)]
                    if not all(0 <= x < w and 0 <= y < h for x, y in samples): vals = None; break
                    g = [float(gray[int(y), int(x)]) for x, y in samples]
                    vals.append(abs(g[2] - (g[0] + g[1] + g[3] + g[4]) / 4))
                total.append(np.median(vals) if vals else 0.0)
    return float(np.mean(total)) if total else 0.0


DETECT_MAX = 1300      # longest side used for circle search (speed); refined at full size


def detect_grids(image, offset=(0, 0), monitor=""):
    """Return lattice candidates (physical coords), best first."""
    scale = min(1.0, DETECT_MAX / max(image.shape[:2]))
    if scale < .95:
        small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        found = _detect(small, "")
        found = [Grid([[x / scale, y / scale] for x, y in g.corners], g.radius) for g in found]
    else:
        found = _detect(image, "")
    out = []
    for i, g in enumerate(found):
        g = refine_grid(image, g) if i < 3 else g
        out.append(Grid(g.shifted(*offset).corners, g.radius, monitor))
    return out


def _detect(image, monitor):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY); h, w = gray.shape
    results = []
    # Separate radius bands: small false circles must not suppress real pieces.
    bands = [(lo, lo * 1.9) for lo in (9, 15, 26, 45, 78) if lo * 2 * 9 < max(h, w) * 1.2]
    for strict in (35, 26):
        for lo, hi in bands:
            circ = find_circles(gray, lo, hi, strict)
            if len(circ) < 5: continue
            rs = circ[:, 2]
            radius_modes = sorted({float(r) for r in rs}, key=lambda r: -np.sum(np.abs(rs - r) < .12 * r))
            tried = []
            for r in radius_modes[:3]:
                if any(abs(r - t) < .15 * t for t in tried): continue
                tried.append(r)
                c = circ[np.abs(rs - r) < .2 * r]
                if len(c) < 5: continue
                results += _lattice_candidates(c, r, gray, (0, 0), monitor)
        if results and max(s for s, _ in results) >= 12: break
    results.sort(key=lambda t: -t[0])
    out = []
    for _, g in results:
        if not any(max(math.dist(a, b) for a, b in zip(g.corners, o.corners)) < g.spacing * .3 for o in out): out.append(g)
    return out


def refine_grid(image, grid, offset=(0, 0)):
    """Refit the lattice to precisely centred pieces (robust least squares)."""
    h, w = image.shape[:2]; ox, oy = offset
    for _ in range(2):
        rect = {"left": ox, "top": oy, "width": w, "height": h}
        ob = Observer(grid, rect); obs = ob.observe(image)
        pts, cols, rows = [], [], []
        for i, c in enumerate(obs.screen):
            if not c or obs.lift[i] or obs.coverage[i] < .6: continue
            x0, y0 = ob.points[i]; x, y = ob.center(image, x0, y0)
            pts.append((x, y)); cols.append(i % 9); rows.append(i // 9)
        if len(pts) < 6 or len(set(cols)) < 3 or len(set(rows)) < 3: return grid
        pts = np.array(pts); cols = np.array(cols); rows = np.array(rows); keep = np.ones(len(pts), bool)
        for _ in range(3):
            corners = _fit_bilinear(pts[keep], cols[keep], rows[keep])
            try: g = Grid(corners, grid.radius, grid.monitor)
            except ValueError: return grid
            err = np.hypot(*(pts - np.array([g.point(a, b) for a, b in zip(cols, rows)])).T) / g.spacing
            new = err < max(.05, 2.5 * float(np.median(err)))
            if new.sum() < 6 or (new == keep).all(): break
            keep = new
        if max(math.dist(a, b) for a, b in zip(g.corners, grid.corners)) > grid.spacing * .5: return grid
        grid = g
    return grid


def _lattice_candidates(c, r, gray, offset, monitor):
    x, y = c[:, 0].astype(np.float64), c[:, 1].astype(np.float64)
    n = len(c); ix, iy = np.triu_indices(n, 1)
    ddx, ddy = np.abs(x[ix] - x[iy]), np.abs(y[ix] - y[iy])
    sx = _spacing(ddx[(ddy < .35 * r) & (ddx > 1.5 * r)], 1.9 * r, 3.4 * r)
    if sx is None: return []
    vert = ddy[(ddx < .35 * r) & (ddy > 1.5 * r)]
    sy = _spacing(vert, .85 * sx, 1.15 * sx) if len(vert) else sx
    phase = lambda v, s: (np.angle(np.mean(np.exp(2j * np.pi * v / s))) % (2 * np.pi)) * s / (2 * np.pi)
    x0, y0 = phase(x, sx), phase(y, sy)
    kc, kr = np.round((x - x0) / sx).astype(int), np.round((y - y0) / sy).astype(int)
    res = np.hypot(x - x0 - kc * sx, y - y0 - kr * sy) / sx
    inl = res < .2
    if inl.sum() < 5: return []
    kc, kr, px, py = kc[inl], kr[inl], x[inl], y[inl]
    counts = {}
    for c0 in range(kc.min() - 8, kc.max() + 1):
        for r0 in range(kr.min() - 9, kr.max() + 1):
            m = (kc >= c0) & (kc <= c0 + 8) & (kr >= r0) & (kr <= r0 + 9)
            counts[(c0, r0)] = int(m.sum())
    best = max(counts.values())
    out = []
    for (c0, r0), cnt in counts.items():
        if cnt < max(5, best - 1): continue
        m = (kc >= c0) & (kc <= c0 + 8) & (kr >= r0) & (kr <= r0 + 9)
        cols, rows = kc[m] - c0, kr[m] - r0
        if len(set(cols)) >= 3 and len(set(rows)) >= 3:
            pts = np.stack([px[m], py[m]], 1); keep = np.ones(len(pts), bool)
            for _ in range(3):   # drop off-centre detections (glow rings, shadows) and refit
                corners = _fit_bilinear(pts[keep], cols[keep], rows[keep])
                g0 = Grid(corners) if corners[1][0] - corners[0][0] > 60 else None
                if g0 is None: break
                pred = np.array([g0.point(a, b) for a, b in zip(cols, rows)])
                err = np.hypot(*(pts - pred).T) / g0.spacing
                new = err < max(.06, float(np.percentile(err, 70)) * 1.5)
                if new.sum() < 5 or (new == keep).all(): break
                keep = new
        else:
            corners = [[x0 + c0 * sx, y0 + r0 * sy], [x0 + (c0 + 8) * sx, y0 + r0 * sy],
                       [x0 + (c0 + 8) * sx, y0 + (r0 + 9) * sy], [x0 + c0 * sx, y0 + (r0 + 9) * sy]]
        # Hough tends to lock onto the inner ring of 3D pieces: keep a sane radius.
        try: g = Grid(corners, float(np.clip(r / ((sx + sy) / 2), .38, .47)), monitor)
        except ValueError: continue
        # Lattice must lie inside the screenshot.
        hgt, wid = gray.shape
        if not all(-.3 * sx <= p[0] < wid + .3 * sx and -.3 * sy <= p[1] < hgt + .3 * sy for p in g.corners): continue
        score = cnt + 4 * min(1.0, line_evidence(gray, g) / 12)
        out.append((score, g.shifted(*offset)))
    return out


# --------------------------------------------------------------------------
# Per-frame observation
# --------------------------------------------------------------------------
_yy, _xx = np.mgrid[:P, :P]
_RAD = np.hypot(_xx - P / 2 + .5, _yy - P / 2 + .5)
_ANG = np.arctan2(_yy - P / 2 + .5, _xx - P / 2 + .5)
_COS, _SIN = np.cos(_ANG), np.sin(_ANG)
_BINS = (((_ANG + np.pi) / (2 * np.pi)) * 36).astype(int) % 36


@dataclass
class Observation:
    colors: tuple       # canonical-order (row-major) None / "red" / "black"
    screen: tuple       # screen-order colours (before orientation)
    coverage: np.ndarray
    redness: np.ndarray
    lift: np.ndarray = None

    def oriented(self, red_bottom):
        out = []
        for r in range(10):
            for c in range(9):
                sc, sr = orient(c, r, red_bottom); out.append(self.screen[sr * 9 + sc])
        return tuple(out)


class Observer:
    """Samples the 90 lattice points of one capture rectangle."""

    def __init__(self, grid, rect, red_threshold=None):
        self.grid = grid; self.rect = rect; self.red_threshold = red_threshold
        s = grid.spacing; self.s = s
        pr = grid.radius * P            # piece radius in patch pixels (patch = 1 spacing)
        self.pr = pr
        self.ring = (_RAD > pr * .8) & (_RAD < pr * 1.15)
        self.inner = _RAD < pr * .72
        order = np.argsort(_BINS[self.ring], kind="stable")
        self.ring_order = order; self.ring_starts = np.searchsorted(_BINS[self.ring][order], np.arange(36))
        self.points = [grid.point(c, r) for r in range(10) for c in range(9)]

    def _affine(self, x, y, size, span):
        # src -> dst: patch centre = lattice point, patch width = span source pixels
        k = size / span; x -= self.rect["left"]; y -= self.rect["top"]; c = (size - 1) / 2
        return np.float32([[k, 0, c - k * x], [0, k, c - k * y]])

    def patch(self, image, i, size=P, dy=0.0):
        x, y = self.points[i]
        return cv2.warpAffine(image, self._affine(x, y + dy * self.s, size, self.s), (size, size),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def _features(self, patch):
        g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
        radial = np.abs(gx * _COS + gy * _SIN)[self.ring][self.ring_order]
        mx = np.maximum.reduceat(radial, self.ring_starts)
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[:, :, 0][self.inner], hsv[:, :, 1][self.inner], hsv[:, :, 2][self.inner]
        red = float(np.mean(((hue < 12) | (hue > 160)) & (sat > 90) & (val > 60)))
        return mx, float(g[self.inner].std()), red

    def observe(self, image, red_bottom=True):
        base = [self._features(self.patch(image, i)) for i in range(90)]
        # A selected piece may be drawn lifted upward.
        lifted = [self._features(self.patch(image, i, dy=-LIFT)) for i in range(90)]
        allmx = np.concatenate([f[0] for f in base])
        edge_t = max(30.0, .35 * float(np.percentile(allmx, 96)))
        self.edge_t = edge_t
        feats = []; lift = np.zeros(90, bool)
        for i, (a, b) in enumerate(zip(base, lifted)):
            ca, cb = np.mean(a[0] > edge_t), np.mean(b[0] > edge_t)
            if cb >= .8 and cb > ca + .1: feats.append(b); lift[i] = True
            else: feats.append(a)
        cov = np.array([float(np.mean(f[0] > edge_t)) for f in feats])
        std = np.array([f[1] for f in feats]); red = np.array([f[2] for f in feats])
        strong = std[cov >= .9]
        std_t = max(10.0, .5 * float(np.median(strong))) if len(strong) >= 2 else 14.0
        # A partly hidden rim (overlapping pieces, glow) is fine when the face is clearly a glyph.
        occ = ((cov >= .7) & (std >= std_t)) | ((cov >= .5) & (std >= 1.6 * std_t))
        rt = self.red_threshold
        if rt is None:
            rt = .02
            vals = np.sort(red[occ])
            if len(vals) >= 4:
                gaps = np.diff(vals); k = int(np.argmax(gaps))
                if gaps[k] > .03 and vals[k + 1] > .03: rt = (vals[k] + vals[k + 1]) / 2
        screen = tuple(None if not o else ("red" if rv > rt else "black") for o, rv in zip(occ, red))
        obs = Observation((), screen, cov, red, lift)
        obs.colors = obs.oriented(red_bottom)
        return obs

    def glyph(self, image, i, lifted=False):
        """HOG glyph vector of the piece at screen index i."""
        ink = self.ink(image, i, lifted)
        return None if ink is None else glyph_vector(ink)

    def ink(self, image, i, lifted=False):
        """Stroke mask of the piece at screen index i, centred on its disk."""
        x0, y0 = self.points[i]
        # Search from both the lattice point and the "selected/lifted" position.
        starts = [(x0, y0 - k * LIFT * self.s) for k in ((1, .5, 0) if lifted else (0, .5, 1))]
        x, y = max((self.center(image, *p, with_score=True) for p in starts), key=lambda t: t[2])[:2]
        p = cv2.warpAffine(image, self._affine(x, y, G, self.s), (G, G), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE)
        return extract_ink(p, rim_radius(p, self.grid.radius * G))

    def center(self, image, x0, y0, with_score=False):
        """Refine a disk centre: concentric rims give the sharpest radial-edge profile."""
        B = 96; span = self.s * 1.3; k = B / span
        patch = cv2.warpAffine(image, self._affine(x0, y0, B, span), (B, B), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)
        g = cv2.GaussianBlur(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32), (3, 3), 0)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
        yy, xx = np.mgrid[:B, :B].astype(np.float32); c = (B - 1) / 2
        lo, hi = .28 * self.s * k, .54 * self.s * k

        def score(dx, dy):
            ux, uy = xx - c - dx, yy - c - dy; d = np.hypot(ux, uy) + 1e-6
            m = (d > lo) & (d < hi)
            radial = np.abs((gx[m] * ux[m] + gy[m] * uy[m]) / d[m])
            prof = np.bincount(d[m].astype(int), radial) / np.maximum(np.bincount(d[m].astype(int)), 1)
            return float(np.sort(prof)[-2:].sum())

        best = (score(0, 0), 0.0, 0.0); step = .04 * self.s * k
        for _ in range(2):
            bx, by = best[1], best[2]
            for dy in (-3, -2, -1, 0, 1, 2, 3):
                for dx in (-3, -2, -1, 0, 1, 2, 3):
                    if dx == dy == 0: continue
                    v = score(bx + dx * step, by + dy * step)
                    if v > best[0]: best = (v, bx + dx * step, by + dy * step)
            step /= 3.5
        if with_score: return x0 + best[1] / k, y0 + best[2] / k, best[0]
        return x0 + best[1] / k, y0 + best[2] / k


def guess_red_bottom(screen):
    reds = [i // 9 for i, c in enumerate(screen) if c == "red"]
    blacks = [i // 9 for i, c in enumerate(screen) if c == "black"]
    if not reds or not blacks: return True
    return bool(np.mean(reds) >= np.mean(blacks))


# --------------------------------------------------------------------------
# Glyphs and piece types
# --------------------------------------------------------------------------
_gy, _gx = np.mgrid[:G, :G]
_GRAD = np.hypot(_gx - G / 2 + .5, _gy - G / 2 + .5)


_GANG = np.arctan2(_gy - G / 2 + .5, _gx - G / 2 + .5)
_GBIN = (((_GANG + np.pi) / (2 * np.pi)) * 36).astype(int) % 36


def rim_radius(patch, guess):
    """Outer edge of the piece disk: strongest circular radial edge."""
    g = cv2.GaussianBlur(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32), (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    radial = np.abs(gx * np.cos(_GANG) + gy * np.sin(_GANG))
    rint = np.round(_GRAD).astype(int)
    prof = np.bincount(rint.ravel(), radial.ravel(), minlength=G) / np.maximum(np.bincount(rint.ravel(), minlength=G), 1)
    lo, hi = int(G * .34), int(G * .52)
    prof = np.convolve(prof, [.25, .5, .25], "same")
    r = lo + int(np.argmax(prof[lo:hi + 1]))
    return float(r) if prof[r] > 1.5 * np.median(prof[lo:hi + 1]) else float(np.clip(guess, G * .36, G * .47))


def extract_glyph(patch, piece_radius):
    ink = extract_ink(patch, piece_radius)
    return None if ink is None else glyph_vector(ink)


def extract_ink(patch, piece_radius):
    """Boolean stroke mask of the glyph inside a centred G x G piece patch."""
    inner = _GRAD < piece_radius * .8
    ink = ink_mask(patch, inner)
    # Remove decorative inner rings: an annulus inked around most of the circle.
    for k in np.arange(.8, .5, -.04):
        band = ink & (_GRAD >= piece_radius * (k - .06)) & (_GRAD < piece_radius * k)
        coverage = len(np.unique(_GBIN[band])) / 36
        if coverage > .6: ink &= _GRAD < piece_radius * (k - .08)
        else: break
    # Drop leftover pieces of a decorative ring: thin arcs concentric with the disk.
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    for j in range(1, n):
        part = lab == j; rad = _GRAD[part]
        if (np.median(rad) > piece_radius * .6 and rad.std() < piece_radius * .05
                and len(np.unique(_GBIN[part])) >= 6):
            ink &= ~part
    return ink if ink.sum() >= 12 else None


def ink_mask(patch, inner):
    """Stroke pixels: colour far from the local piece face (red and black ink).

    The face is estimated with a large median filter, which removes thin
    strokes but follows lighting gradients and wood texture.
    """
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)
    k = max(3, int(patch.shape[0] * .33) | 1)
    face = cv2.medianBlur(lab, k).astype(np.float32)
    lab = lab.astype(np.float32)
    d = lab - face; d[:, :, 0] *= .8
    dist = np.linalg.norm(d, axis=2)
    vals = dist[inner]
    t = _otsu(vals)
    t = 22.0 if t is None else float(np.clip(t, 18, 60))
    ink = inner & (dist > t)
    ink = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return ink > 0


def _otsu(vals):
    v = np.clip(vals, 0, 255).astype(np.uint8)
    if v.size < 20 or v.max() - v.min() < 10: return None
    t, _ = cv2.threshold(v.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(t)


_HOG = cv2.HOGDescriptor((32, 32), (16, 16), (8, 8), (8, 8), 9)
GLYPH_DIM = 324


def glyph_vector(mask):
    """Stroke-direction (HOG) descriptor of a glyph mask, scale-normalised.

    Gradient orientation histograms are far less sensitive to stroke
    thickness and calligraphy style than raw pixel correlation.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) < 12: return None
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    h, w = m.shape; side = max(h, w)
    pad = np.zeros((side + 8, side + 8), np.float32)
    pad[4 + (side - h) // 2:4 + (side - h) // 2 + h, 4 + (side - w) // 2:4 + (side - w) // 2 + w] = m
    v = cv2.resize(pad, (32, 32), interpolation=cv2.INTER_AREA)
    d = _HOG.compute((v * 255).astype(np.uint8)).ravel().astype(np.float32)
    d -= d.mean(); n = float(np.linalg.norm(d))
    return d / n if n > 1e-6 else None


TYPES = "kabnrcp"


SLOTS = ["k", "a", "a", "b", "b", "n", "n", "r", "r", "c", "c", "p", "p", "p", "p", "p"]


def hungarian(cost):
    """Minimum assignment for an n x m matrix, n <= m. Returns column per row."""
    cost = np.asarray(cost, np.float64); n, m = cost.shape
    u = np.zeros(n + 1); v = np.zeros(m + 1); p = np.zeros(m + 1, int); way = np.zeros(m + 1, int)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0; minv = np.full(m + 1, np.inf); used = np.zeros(m + 1, bool)
        while True:
            used[j0] = True; i0 = p[j0]; delta = np.inf; j1 = 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1, j - 1] - u[i0] - v[j]
                    if cur < minv[j]: minv[j] = cur; way[j] = j0
                    if minv[j] < delta: delta = minv[j]; j1 = j
            for j in range(m + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0: break
    result = [-1] * n
    for j in range(1, m + 1):
        if p[j]: result[p[j] - 1] = j - 1
    return result


class Recognizer:
    def __init__(self, skin_path=None):
        data = np.load(ASSETS / "glyphs.npz")
        self.font_vectors = data["vectors"].astype(np.float32); self.font_labels = data["labels"]
        self.skin_path = Path(skin_path) if skin_path else None
        self.learned_vectors = np.zeros((0, GLYPH_DIM), np.float32); self.learned_labels = np.array([], dtype="<U1")
        self.red_threshold = None
        if self.skin_path and self.skin_path.exists():
            try:
                d = np.load(self.skin_path)
                if d["vectors"].shape[1:] == (GLYPH_DIM,):
                    self.learned_vectors = d["vectors"].astype(np.float32); self.learned_labels = d["labels"]
                self.red_threshold = float(d["red_threshold"]) if "red_threshold" in d else None
            except (OSError, ValueError, KeyError):
                pass
        # Built-in skins of popular programs (tools/make_skin.py).
        lib_v, lib_l = [], []
        for path in sorted((ASSETS / "skins").glob("*.npz")) if (ASSETS / "skins").is_dir() else []:
            d = np.load(path)
            if d["vectors"].shape[1:] == (GLYPH_DIM,): lib_v.append(d["vectors"].astype(np.float32)); lib_l.append(d["labels"])
        self.library_vectors = np.concatenate(lib_v) if lib_v else np.zeros((0, GLYPH_DIM), np.float32)
        self.library_labels = np.concatenate(lib_l) if lib_l else np.array([], dtype="<U1")

    @property
    def has_skin(self):
        return len(self.learned_labels) >= 14

    # generic fonts are discounted against templates of a known skin
    W_FONT, W_SKIN = .85, 1.0

    def type_scores(self, ink, side):
        """Per piece type score (higher is better): best of generic-font and known-skin match."""
        vec = None if ink is None else glyph_vector(ink)
        if vec is None: return {t: 0.0 for t in TYPES}
        font = self.font_vectors @ vec
        skins = [(self.learned_vectors @ vec, self.learned_labels) if len(self.learned_labels) else None,
                 (self.library_vectors @ vec, self.library_labels) if len(self.library_labels) else None]
        scores = {}
        for k, t in enumerate(TYPES):
            template = float(font[self.font_labels == t].max()) * self.W_FONT
            for skin in filter(None, skins):
                m = skin[1] == (t.upper() if side == "red" else t)
                if m.any(): template = max(template, float(skin[0][m].max()) * self.W_SKIN)
            scores[t] = template
        return scores

    def learn(self, observer, image, board, red_bottom, observation):
        """Store this skin's glyphs from a position known with certainty."""
        vectors, labels = [], []
        for r in range(10):
            for c in range(9):
                p = board.cells[r][c]
                if not p: continue
                sc, sr = orient(c, r, red_bottom); i = sr * 9 + sc
                v = observer.glyph(image, i, bool(observation.lift[i]))
                if v is not None: vectors.append(v); labels.append(p)
        reds = [observation.redness[i] for i, col in enumerate(observation.screen) if col == "red"]
        blacks = [observation.redness[i] for i, col in enumerate(observation.screen) if col == "black"]
        if reds and blacks and min(reds) > max(blacks): self.red_threshold = (min(reds) + max(blacks)) / 2
        if len(set(labels)) < 14: return False
        self.learned_vectors = np.array(vectors, np.float32); self.learned_labels = np.array(labels)
        if self.skin_path:
            self.skin_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.skin_path.with_name(self.skin_path.stem + ".tmp.npz")
            np.savez_compressed(tmp, vectors=self.learned_vectors.astype(np.float16), labels=self.learned_labels,
                                red_threshold=np.float32(self.red_threshold if self.red_threshold is not None else .02))
            tmp.replace(self.skin_path)
        return True

    # same-skin consistency: identical pieces look alike, so look-alikes vote
    CONSISTENCY, SAME_SKIN_SIM = .6, .5

    def _consistent(self, cells, glyphs, cost, assign, rounds=3):
        vecs = [None if glyphs[i] is None else glyph_vector(glyphs[i]) for _, _, i in cells]
        n = len(cells); sim = np.zeros((n, n))
        for a in range(n):
            for b in range(n):
                if a != b and vecs[a] is not None and vecs[b] is not None: sim[a, b] = float(vecs[a] @ vecs[b])
        for _ in range(rounds):
            bonus = np.zeros_like(cost)
            for a in range(n):
                for t in TYPES:
                    peers = [sim[a, b] for b in range(n) if b != a and SLOTS[assign[b]] == t]
                    if peers and max(peers) > self.SAME_SKIN_SIM:
                        bonus[a, [k for k, s_ in enumerate(SLOTS) if s_ == t]] = self.CONSISTENCY * (max(peers) - self.SAME_SKIN_SIM)
            new = hungarian(cost - bonus)
            if new == assign: break
            assign = new
        return assign

    def recognize(self, observer, image, observation):
        """Full position from one screenshot. Returns (board, red_bottom, score)."""
        screen = observation.screen
        glyphs = {i: observer.ink(image, i, bool(observation.lift[i])) for i, col in enumerate(screen) if col}
        best = None
        for red_bottom in (guess_red_bottom(screen), not guess_red_bottom(screen)):
            board = Board(); total = 0.0
            for side in ("red", "black"):
                cells = []
                for i, col in enumerate(screen):
                    if col != side: continue
                    c, r = orient(i % 9, i // 9, red_bottom); cells.append((c, r, i))
                cells.sort(key=lambda t: -observation.coverage[t[2]]); cells = cells[:16]
                if not cells: continue
                cost = np.zeros((len(cells), len(SLOTS)))
                for a, (c, r, i) in enumerate(cells):
                    sc = self.type_scores(glyphs[i], side)
                    for b, t in enumerate(SLOTS):
                        piece = t.upper() if side == "red" else t
                        cost[a, b] = -sc[t] if placement_ok(piece, c, r) else 50.0
                        if t == "k": cost[a, b] -= 5.0     # every side has exactly one king
                        if HOME.cells[r][c] == piece: cost[a, b] -= .04   # many pieces never leave home
                assign = hungarian(cost)
                assign = self._consistent(cells, glyphs, cost, assign)
                for a, (c, r, i) in enumerate(cells):
                    t = SLOTS[assign[a]]; board.cells[r][c] = t.upper() if side == "red" else t
                    total -= cost[a, assign[a]]
            total -= 20 * len(board.validate())
            if best is None or total > best[2]: best = (board, red_bottom, total)
        return best
