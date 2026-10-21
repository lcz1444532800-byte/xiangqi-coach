"""Build the Windows x64 portable release, verify it from a relocated folder, zip it.

    .venv\\Scripts\\python.exe tools\\build_portable.py

Output: 发布\\象棋AI助手-V0.2-免安装版.zip (needs no Python on the target PC).
"""
from pathlib import Path
import ctypes
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from ctypes import wintypes
import pefile
import psutil

ROOT = Path(__file__).resolve().parents[1]
NAME = "象棋AI助手"
VERSION = "V0.5.1"
DIST = ROOT / "work/portable-dist"
RELEASE = ROOT / "发布"


def build():
    shutil.rmtree(DIST / NAME, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--noupx",
                    "--name", NAME, "--distpath", str(DIST), "--workpath", str(ROOT / "work/pyinstaller-build"),
                    "--specpath", str(ROOT / "work/pyinstaller-spec"),
                    "--add-data", f"{ROOT / 'coach/assets'};coach/assets",
                    "--exclude-module", "pytest", "--exclude-module", "PySide6.QtWebEngineCore",
                    "--exclude-module", "PySide6.QtWebEngineWidgets", "--exclude-module", "PySide6.QtPdf",
                    "--exclude-module", "PySide6.QtQml", "--exclude-module", "py7zr",
                    str(ROOT / "main.py")], cwd=ROOT, check=True)
    bundle = DIST / NAME; internal = bundle / "_internal"
    # Qt uses Windows' unversioned ICU API; a mismatching bundled ICU breaks QtCore.
    icu = internal / "icuuc.dll"
    if icu.exists():
        exports = {e.name for e in pefile.PE(str(icu)).DIRECTORY_ENTRY_EXPORT.symbols}
        core = pefile.PE(str(internal / "PySide6/Qt6Core.dll"))
        need = {i.name for e in core.DIRECTORY_ENTRY_IMPORT if e.dll.lower() == b"icuuc.dll" for i in e.imports if i.name}
        if not need.issubset(exports):
            icu.unlink()
            for extra in internal.glob("icudt*.dll"): extra.unlink()
    shutil.copytree(ROOT / "engine", bundle / "engine", dirs_exist_ok=True)
    (bundle / "data").mkdir(exist_ok=True)
    for name in ("README.md", "LICENSE"): shutil.copy2(ROOT / name, bundle / name)
    licenses = bundle / "licenses"; licenses.mkdir(exist_ok=True)
    py_license = Path(sys.base_prefix) / "LICENSE.txt"
    if py_license.is_file(): shutil.copy2(py_license, licenses / "Python-LICENSE.txt")
    if (ROOT / "third-party-notices").is_dir(): shutil.copytree(ROOT / "third-party-notices", licenses / "Qt", dirs_exist_ok=True)
    for module in ("PySide6_Essentials", "shiboken6", "numpy", "opencv-python", "mss", "pyinstaller"):
        dist = importlib.metadata.distribution(module)
        for entry in dist.files or []:
            if "license" in str(entry).lower() or "copying" in str(entry).lower():
                src = Path(dist.locate_file(entry))
                if src.is_file():
                    folder = licenses / module; folder.mkdir(exist_ok=True)
                    shutil.copy2(src, folder / str(entry).replace("/", "_").replace("\\", "_"))
    (bundle / "先看这里.txt").write_text(
        "象棋AI助手 " + VERSION + "（Windows 10/11 64 位，免安装）\n\n"
        "1. 把整个压缩包解压到桌面等普通文件夹，不要在压缩包里直接运行。\n"
        "2. 双击「象棋AI助手.exe」。\n"
        "3. 打开你的象棋软件，让棋盘完整显示在屏幕上（助手窗口放到旁边）。\n"
        "4. 点「我执红/我执黑」选好自己的一方，再点「开始」。\n"
        "5. 轮到你时，棋盘上会出现绿色箭头，助手窗口显示走法（如 炮二平五）。\n"
        "   也可随时点「提示走法」立即获得当前局面的建议。\n\n"
        "建议在开局时点开始：从开局跟踪最精确，前 8 回合的推荐会有变化。\n"
        "查看胜率等弹窗盖住棋盘时会自动暂停，关闭弹窗后自动继续。\n"
        "请保留 _internal、engine、data 文件夹。详细说明见 README.md。\n", encoding="utf-8-sig")
    return bundle


def find_window(pid_root, title, timeout=25):
    u = ctypes.windll.user32
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: ids = {pid_root.pid} | {c.pid for c in psutil.Process(pid_root.pid).children(recursive=True)}
        except psutil.NoSuchProcess: return None, set()
        found, titles = [], set()

        def cb(hwnd, _):
            pid = wintypes.DWORD(); u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in ids:
                buf = ctypes.create_unicode_buffer(256); u.GetWindowTextW(hwnd, buf, 256)
                if buf.value: titles.add(buf.value)
                if buf.value == title: found.append(int(hwnd))
            return True
        u.EnumWindows(cb_type(cb), 0)
        if found: return found[0], titles
        if pid_root.poll() is not None: return None, titles
        time.sleep(.2)
    return None, titles


def verify(bundle):
    """Copy to a folder with Chinese + spaces, sanitise PATH/Python env, launch, close."""
    target = ROOT / "work/朋友电脑 模拟" / NAME
    shutil.rmtree(target.parent, ignore_errors=True); shutil.copytree(bundle, target)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "QT_", "VIRTUAL_ENV", "CONDA"))}
    env["PATH"] = r"C:\Windows\System32;C:\Windows"
    cwd = ROOT / "work/unrelated-dir"; cwd.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([str(target / (NAME + ".exe"))], cwd=cwd, env=env)
    try:
        hwnd, titles = find_window(proc, NAME)
        if not hwnd: raise RuntimeError(f"主窗口没有出现，看到的窗口：{titles}")
        time.sleep(3)                                   # engine starts in the background
        engine_ok = any(c.name().lower() == "pikafish.exe" for c in psutil.Process(proc.pid).children(recursive=True))
        ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x10, 0, 0)
        code = proc.wait(timeout=15)
        if not engine_ok: raise RuntimeError("便携版没有启动自带的 Pikafish 引擎")
        if code != 0: raise RuntimeError(f"退出码 {code}")
        return {"relocated_to": str(target), "window": True, "engine_started": engine_ok, "exit_code": code}
    finally:
        if proc.poll() is None: proc.kill()


def package(bundle, check):
    RELEASE.mkdir(exist_ok=True)
    (bundle / "build-info.json").write_text(json.dumps({
        "version": VERSION, "python": sys.version, "format": "PyInstaller onedir, Windows x64", "relocation_check": check,
        "exe_sha256": hashlib.sha256((bundle / (NAME + ".exe")).read_bytes()).hexdigest()}, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = RELEASE / f"{NAME}-{VERSION}-免安装版.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(bundle.rglob("*")):
            if p.is_file() and not (p.parent.name == "data" and p.parent.parent == bundle):
                z.write(p, NAME + "/" + p.relative_to(bundle).as_posix())
        z.writestr(NAME + "/data/", "")
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None and f"{NAME}/{NAME}.exe" in z.namelist()
    (RELEASE / "SHA256.txt").write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n", encoding="utf-8")
    return archive


if __name__ == "__main__":
    b = build(); c = verify(b); a = package(b, c)
    print(json.dumps({"archive": str(a), "size_mb": round(a.stat().st_size / 2 ** 20, 1), "check": c}, ensure_ascii=False, indent=2))
