import sys
from coach.capture import enable_dpi
enable_dpi()
from coach.app import run

if __name__ == "__main__":
    raise SystemExit(run())
