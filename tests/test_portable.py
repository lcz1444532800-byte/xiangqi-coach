from pathlib import Path
import sys
from coach.config import application_root


def test_frozen_root_tracks_executable(monkeypatch,tmp_path):
    executable=tmp_path/"朋友 解压目录"/"象棋AI教练.exe"
    monkeypatch.setattr(sys,"frozen",True,raising=False)
    monkeypatch.setattr(sys,"executable",str(executable))
    assert application_root()==executable.parent.resolve()


def test_source_root_unchanged(monkeypatch):
    monkeypatch.delattr(sys,"frozen",raising=False)
    assert application_root()==Path(__file__).resolve().parents[1]
