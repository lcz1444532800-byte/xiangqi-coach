@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating a Python environment...
    py -3.11 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo Please install 64-bit Python 3.11 first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import PySide6,mss,cv2,numpy,py7zr" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installing dependencies failed, see the messages above.
        pause
        exit /b 1
    )
)
if not exist "engine\pikafish.exe" (
    ".venv\Scripts\python.exe" tools\install_engine.py
    if errorlevel 1 (
        echo Downloading Pikafish failed.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
endlocal
