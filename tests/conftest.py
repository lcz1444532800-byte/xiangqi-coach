import os
import sys
from pathlib import Path
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).parent))
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    font = Path("C:/Windows/Fonts/msyh.ttc")
    if font.exists(): QFontDatabase.addApplicationFont(str(font))
    return app
