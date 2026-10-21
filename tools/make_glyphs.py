"""Render generic piece glyph templates from Windows Chinese fonts.

Output: coach/assets/glyphs.npz (normalised 32x32 glyph vectors + piece types).
Only needed when changing the font list; the result ships with the program.
"""
import os
import sys
from pathlib import Path
import numpy as np
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QFont, QFontDatabase, QColor
from PySide6.QtCore import Qt, QRect
from coach.vision import glyph_vector, GLYPH_CHARS

FONTS = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "simkai.ttf", "simfang.ttf", "STKAITI.TTF",
         "STXINGKA.TTF", "STLITI.TTF", "SIMLI.TTF", "FZSTK.TTF", "FZYTK.TTF", "STZHONGS.TTF", "STSONG.TTF",
         "msjh.ttc", "Deng.ttf", "Dengb.ttf", "STHUPO.TTF", "STXINWEI.TTF", "STFANGSO.TTF"]


def main():
    app = QGuiApplication([])
    vectors, labels = [], []
    for name in FONTS:
        path = Path("C:/Windows/Fonts") / name
        if not path.exists(): continue
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid < 0: continue
        family = QFontDatabase.applicationFontFamilies(fid)[0]
        for bold in (False, True):
            for t, chars in GLYPH_CHARS.items():
                for ch in chars:
                    img = QImage(128, 128, QImage.Format.Format_Grayscale8); img.fill(0)
                    p = QPainter(img); font = QFont(family); font.setPixelSize(92); font.setBold(bold)
                    p.setFont(font); p.setPen(QColor(255, 255, 255))
                    p.drawText(QRect(0, 0, 128, 128), Qt.AlignmentFlag.AlignCenter, ch); p.end()
                    mask = np.frombuffer(img.constBits(), np.uint8).reshape(128, img.bytesPerLine())[:, :128]
                    v = glyph_vector(mask > 100)
                    if v is not None: vectors.append(v); labels.append(t)
    out = Path(__file__).resolve().parents[1] / "coach/assets/glyphs.npz"
    out.parent.mkdir(exist_ok=True)
    np.savez_compressed(out, vectors=np.array(vectors, np.float16), labels=np.array(labels))
    print(out, len(vectors))
    del app


if __name__ == "__main__":
    main()
