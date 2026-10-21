from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import os
import sys


def application_root():
    # Frozen modules live in _internal; writable data and engine stay by the EXE.
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


ROOT = application_root()
VERSION = 2


@dataclass
class Settings:
    side: str = "red"
    grid: dict | None = None
    engine_path: str = "engine/pikafish.exe"
    movetime_ms: int = 1000
    threads: int = 0            # 0 = half of the logical CPUs (max 8)
    hash_mb: int = 256
    geometry: list = field(default_factory=list)
    rev: int = 2                # bump to migrate changed defaults

    @classmethod
    def load(cls, path=None):
        path = Path(path or ROOT / "data/config.json")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if raw.get("version") != VERSION: return cls()
        obj = cls(**{k: v for k, v in raw.get("settings", {}).items() if k in cls.__dataclass_fields__})
        if obj.side not in ("red", "black"): obj.side = "red"
        if raw.get("settings", {}).get("rev", 1) < 2:   # V0.2 shipped 1500 ms; pondering makes 1000 ms as strong
            if obj.movetime_ms == 1500: obj.movetime_ms = 1000
            obj.rev = 2
        obj.movetime_ms = max(300, min(10000, int(obj.movetime_ms)))
        obj.threads = max(0, min(32, int(obj.threads)))
        obj.hash_mb = max(16, min(2048, int(obj.hash_mb)))
        return obj

    def save(self, path=None):
        path = Path(path or ROOT / "data/config.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": VERSION, "settings": asdict(self)}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def engine(self):
        p = Path(self.engine_path)
        return p if p.is_absolute() else ROOT / p
