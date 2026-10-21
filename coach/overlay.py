import ctypes
import math
import sys
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_from_capture(widget):
    """Hide a window from screenshots (Windows 10 2004+). Returns success."""
    if sys.platform != "win32": return False
    from ctypes import wintypes
    fn = ctypes.windll.user32.SetWindowDisplayAffinity
    fn.argtypes = [wintypes.HWND, wintypes.DWORD]; fn.restype = wintypes.BOOL
    return bool(fn(wintypes.HWND(int(widget.winId())), WDA_EXCLUDEFROMCAPTURE))


class ArrowOverlay(QWidget):
    """Transparent, click-through, always-on-top arrow over the real board."""

    def __init__(self):
        super().__init__(); self.points = None; self.size = 40.0; self.capture_excluded = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def show_arrow(self, mapping, points, spacing):
        """points: physical screen pixels (from, to); spacing in physical pixels."""
        self.setGeometry(*mapping.logical)
        x, y, w, _ = mapping.logical
        scale = w / mapping.physical[2]
        self.points = [QPointF(px - x, py - y) for px, py in (mapping.to_logical(p) for p in points)]
        self.size = spacing * scale
        self.show(); self.raise_()
        if sys.platform == "win32":
            from ctypes import wintypes
            u = ctypes.windll.user32; hwnd = wintypes.HWND(int(self.winId()))
            get = u.GetWindowLongW; get.argtypes = [wintypes.HWND, ctypes.c_int]; get.restype = ctypes.c_long
            put = u.SetWindowLongW; put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            put(hwnd, -20, get(hwnd, -20) | 0x20 | 0x80000 | 0x08000000)   # transparent, layered, no-activate
            self.capture_excluded = exclude_from_capture(self)
        self.update()

    def clear(self):
        self.hide(); self.points = None

    def paintEvent(self, event):
        if not self.points: return
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a, b = self.points; dx, dy = b.x() - a.x(), b.y() - a.y(); n = math.hypot(dx, dy)
        if n < 1: return
        s = self.size; ux, uy = dx / n, dy / n
        width = max(6.0, s * .14); head = max(18.0, s * .42)
        start = QPointF(a.x() + ux * s * .2, a.y() + uy * s * .2)
        tip = QPointF(b.x() - ux * s * .05, b.y() - uy * s * .05)
        neck = QPointF(tip.x() - ux * head * .8, tip.y() - uy * head * .8)
        poly = QPolygonF([tip, QPointF(tip.x() - ux * head - uy * head * .55, tip.y() - uy * head + ux * head * .55),
                          QPointF(tip.x() - ux * head + uy * head * .55, tip.y() - uy * head - ux * head * .55)])
        green = QColor(0, 200, 90, 235); dark = QColor(0, 60, 30, 200)
        # origin ring and target ring
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(dark, width * .9)); p.drawEllipse(a, s * .46, s * .46)
        p.setPen(QPen(green, width * .55)); p.drawEllipse(a, s * .46, s * .46)
        p.setPen(QPen(QColor(255, 210, 0, 220), width * .55, Qt.PenStyle.DashLine)); p.drawEllipse(b, s * .46, s * .46)
        p.setPen(QPen(dark, width + 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)); p.drawLine(start, neck)
        p.setPen(QPen(green, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)); p.drawLine(start, neck)
        p.setPen(QPen(dark, 3)); p.setBrush(green); p.drawPolygon(poly)
