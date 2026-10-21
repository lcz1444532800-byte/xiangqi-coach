"""Synthetic board screenshots in several skins (test-only)."""
from dataclasses import dataclass
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QFont, QRadialGradient, QFontDatabase
from coach.board import Board

CHARS = {"K": "帅", "A": "仕", "B": "相", "N": "马", "R": "车", "C": "炮", "P": "兵",
         "k": "将", "a": "士", "b": "象", "n": "马", "r": "车", "c": "炮", "p": "卒"}
TRAD = {"K": "帥", "A": "仕", "B": "相", "N": "傌", "R": "俥", "C": "炮", "P": "兵",
        "k": "將", "a": "士", "b": "象", "n": "馬", "r": "車", "c": "砲", "p": "卒"}


@dataclass
class Skin:
    font: str = "KaiTi"
    traditional: bool = False
    spacing: int = 60
    radius: float = .44
    board: str = "#e9c98f"
    line: str = "#6b4a22"
    face: str = "#f7e2b5"
    rim: str = "#8a5a2b"
    red: str = "#c41e1e"
    black: str = "#1d1d1d"
    background: str = "#3d5a3d"
    gradient: bool = False
    inner_ring: bool = True


SKINS = [
    Skin(),
    Skin(font="SimHei", spacing=48, radius=.45, board="#d8b878", face="#fff4d6", rim="#5b3a12", gradient=True, inner_ring=False),
    Skin(font="STXingkai", traditional=True, spacing=72, radius=.42, board="#9fb3a0", line="#556b55", face="#f0c27a",
         rim="#6e4a1e", background="#26331f", gradient=True),
    Skin(font="LiSu", spacing=54, radius=.46, board="#f2e6c8", line="#333", face="#fbfbf3", rim="#444", red="#d0103a",
         black="#123a2a", background="#555"),
]

_fonts_loaded = False


def load_fonts():
    global _fonts_loaded
    if _fonts_loaded: return
    for f in ("simkai.ttf", "simhei.ttf", "STXINGKA.TTF", "SIMLI.TTF", "msyh.ttc"):
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + f)
    _fonts_loaded = True


def render(board, skin, red_bottom=True, size=(900, 900), origin=(120, 80), last_move=None, lifted=None,
           moving=None, noise=0, seed=0):
    """BGR numpy screenshot. moving=(piece, (x,y) screen-lattice float pos) draws a piece mid-animation."""
    load_fonts()
    w, h = size; s = skin.spacing; ox, oy = origin
    img = QImage(w, h, QImage.Format.Format_RGB888); img.fill(QColor(skin.background))
    p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pt = lambda c, r: QPointF(ox + c * s, oy + r * s)
    p.fillRect(QRectF(ox - s * .8, oy - s * .8, 8 * s + 1.6 * s, 9 * s + 1.6 * s), QColor(skin.board))
    p.setPen(QPen(QColor(skin.line), max(1, s // 30)))
    for r in range(10): p.drawLine(pt(0, r), pt(8, r))
    for c in range(9):
        if c in (0, 8): p.drawLine(pt(c, 0), pt(c, 9))
        else: p.drawLine(pt(c, 0), pt(c, 4)); p.drawLine(pt(c, 5), pt(c, 9))
    for r0 in (0, 7):
        p.drawLine(pt(3, r0), pt(5, r0 + 2)); p.drawLine(pt(5, r0), pt(3, r0 + 2))
    f = QFont(skin.font); f.setPixelSize(int(s * .45)); p.setFont(f)
    p.drawText(QRectF(ox, oy + 4 * s, 8 * s, s), Qt.AlignmentFlag.AlignCenter, "楚 河          汉 界")
    names = TRAD if skin.traditional else CHARS

    def piece(center, label):
        rad = s * skin.radius
        if skin.gradient:
            g = QRadialGradient(center + QPointF(-rad * .3, -rad * .3), rad * 1.3)
            g.setColorAt(0, QColor(skin.face).lighter(115)); g.setColorAt(1, QColor(skin.face).darker(125)); p.setBrush(g)
        else:
            p.setBrush(QColor(skin.face))
        p.setPen(QPen(QColor(skin.rim), max(2, s * .05))); p.drawEllipse(center, rad, rad)
        ink = QColor(skin.red if label.isupper() else skin.black)
        if skin.inner_ring:
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(ink, max(1, s * .025))); p.drawEllipse(center, rad * .82, rad * .82)
        f = QFont(skin.font); f.setPixelSize(int(rad * 1.25)); f.setBold(True); p.setFont(f); p.setPen(ink)
        p.drawText(QRectF(center.x() - rad, center.y() - rad, 2 * rad, 2 * rad), Qt.AlignmentFlag.AlignCenter, names[label])

    def screen(c, r):
        return (c, r) if red_bottom else (8 - c, 9 - r)

    if last_move:
        for c, r in last_move:
            sc, sr = screen(c, r); p.setPen(QPen(QColor("#ffffff"), 2)); p.setBrush(QColor(255, 255, 255, 160))
            p.drawEllipse(pt(sc, sr), s * .08, s * .08)
    for c, r, label in board.pieces():
        sc, sr = screen(c, r); center = pt(sc, sr)
        if lifted == (c, r): center = center + QPointF(0, -s * .25)
        piece(center, label)
        if last_move and (c, r) == last_move[-1]:
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor(80, 255, 120, 200), max(3, s * .07)))
            p.drawEllipse(center, s * skin.radius * 1.12, s * skin.radius * 1.12)
    if moving:
        label, (x, y) = moving
        piece(QPointF(ox + x * s, oy + y * s), label)
    p.end()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
    out = a[:, :, ::-1].copy()
    if noise:
        rng = np.random.default_rng(seed)
        out = np.clip(out.astype(np.int16) + rng.integers(-noise, noise + 1, out.shape), 0, 255).astype(np.uint8)
    return out
