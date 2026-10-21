import cv2
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import QDialog


def pixmap(bgr):
    rgb = cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
    return QPixmap.fromImage(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format.Format_RGB888).copy())


class Selector(QDialog):
    def __init__(self, image, mapping):
        super().__init__()
        self.mapping=mapping; self.image=pixmap(image); self.start=None; self.end=None; self.selected=None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setGeometry(*mapping.logical)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self,event):
        p=QPainter(self); p.drawPixmap(self.rect(),self.image)
        p.fillRect(self.rect(),QColor(0,0,0,55)); p.setPen(QColor("white"))
        p.drawText(20,35,"拖框选择整个棋盘（包含棋子），松开确认；Esc 取消。")
        if self.start and self.end:
            p.setPen(QPen(QColor("#00e6c8"),3)); p.drawRect(QRectF(self.start,self.end).normalized())

    def mousePressEvent(self,event):
        self.start=event.position(); self.end=self.start; self.update()

    def mouseMoveEvent(self,event):
        if self.start:
            self.end=event.position(); self.update()

    def mouseReleaseEvent(self,event):
        self.end=event.position()
        r=QRectF(self.start,self.end).normalized().intersected(QRectF(self.rect()))
        if r.width()<80 or r.height()<90:
            self.start=None; self.update(); return
        gx,gy,_,_=self.mapping.logical
        a=self.mapping.to_physical((gx+r.left(),gy+r.top()))
        b=self.mapping.to_physical((gx+r.right(),gy+r.bottom()))
        self.selected={"left":round(a[0]),"top":round(a[1]),"width":round(b[0]-a[0]),"height":round(b[1]-a[1])}
        self.accept()
