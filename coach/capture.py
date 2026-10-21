import ctypes
import sys
from dataclasses import dataclass
import numpy as np
import mss


def enable_dpi():
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass


def native_monitors():
    from ctypes import wintypes
    if sys.platform != "win32":
        return {}
    class MI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR*32)]
    result = {}
    get_info=ctypes.windll.user32.GetMonitorInfoW
    get_info.argtypes=[wintypes.HANDLE,ctypes.POINTER(MI)]
    get_info.restype=wintypes.BOOL
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def callback(handle, dc, rect, data):
        mi = MI(); mi.cbSize = ctypes.sizeof(mi)
        if not get_info(handle, ctypes.byref(mi)):
            return True
        r = mi.rcMonitor
        result[mi.szDevice] = (r.left,r.top,r.right-r.left,r.bottom-r.top)
        return True
    cb = callback_type(callback)
    ctypes.windll.user32.EnumDisplayMonitors(None,None,cb,0)
    return result


@dataclass
class ScreenMap:
    name: str
    physical: tuple
    logical: tuple

    def to_logical(self, point):
        x,y,w,h = self.physical
        qx,qy,qw,qh = self.logical
        return qx+(point[0]-x)*qw/w, qy+(point[1]-y)*qh/h

    def to_physical(self, point):
        x,y,w,h = self.physical
        qx,qy,qw,qh = self.logical
        return x+(point[0]-qx)*w/qw, y+(point[1]-qy)*h/qh

    def rect(self):
        return dict(zip(("left","top","width","height"), self.physical))


def screen_maps(app):
    native = native_monitors()
    with getattr(mss, "MSS", mss.mss)() as s:
        monitors = s.monitors[1:]
    out = []
    for i, screen in enumerate(app.screens()):
        q = screen.geometry()
        p = native.get(screen.name())
        if p is None:
            candidates=[v for v in native.values() if (v[0],v[1])==(q.x(),q.y()) and abs(v[2]/q.width()-screen.devicePixelRatio())<.02 and abs(v[3]/q.height()-screen.devicePixelRatio())<.02]
            if len(candidates)==1:
                p=candidates[0]
            elif len(monitors)==1 and len(app.screens())==1:
                m=monitors[0]; p=(m["left"],m["top"],m["width"],m["height"])
            else:
                raise RuntimeError("无法可靠对应多显示器物理坐标，请在单显示器模式使用")
        out.append(ScreenMap(screen.name(),p,(q.x(),q.y(),q.width(),q.height())))
    return out


def layout_signature(maps):
    return sorted([[m.name,list(m.physical),list(m.logical)] for m in maps])


def grab(rect):
    with getattr(mss, "MSS", mss.mss)() as s:
        return np.array(s.grab(rect))[:,:,:3].copy()  # BGR


def window_snapshot(point=None, handle=None):
    """Read-only visible window geometry; never touches target process."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.WindowFromPoint.restype = wintypes.HWND
    u.GetAncestor.restype = wintypes.HWND
    u.GetAncestor.argtypes = [wintypes.HWND,wintypes.UINT]
    for name in ("IsWindow","IsWindowVisible","IsIconic"):
        getattr(u,name).argtypes = [wintypes.HWND]
    u.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    if handle is None:
        handle = u.GetAncestor(u.WindowFromPoint(wintypes.POINT(round(point[0]),round(point[1]))),2)
    if not handle or not u.IsWindow(handle) or not u.IsWindowVisible(handle) or u.IsIconic(handle):
        return None
    r=wintypes.RECT()
    if not u.GetWindowRect(handle,ctypes.byref(r)):
        return None
    return (int(handle),(r.left,r.top,r.right,r.bottom))
