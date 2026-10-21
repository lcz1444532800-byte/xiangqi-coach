"""Fetch a pinned official release, verify SHA-256, deploy Windows x64 files."""
from pathlib import Path, PurePosixPath
import urllib.request
import hashlib
import json
import shutil
import sys
import py7zr

ROOT=Path(__file__).resolve().parents[1]
TAG="Pikafish-2026-09-06"
ARCHIVE="Pikafish.2026-09-06.7z"
SHA256="41952bbfe2520faceb5902c69e6ab4845cc999841d2b49a95cc1be7867a25e5b"
URL=f"https://github.com/official-pikafish/Pikafish/releases/download/{TAG}/{ARCHIVE}"


def download(url,path):
    request=urllib.request.Request(url,headers={"User-Agent":"XiangqiCoach/0.1"})
    with urllib.request.urlopen(request,timeout=90) as response, path.open("wb") as out:
        shutil.copyfileobj(response,out)


def install():
    work=ROOT/"work/engine-download"; work.mkdir(parents=True,exist_ok=True)
    archive=work/ARCHIVE
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:
        print("下载官方 Pikafish 发布包…",flush=True); download(URL,archive)
    actual=hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual!=SHA256: raise RuntimeError("官方发布包 SHA-256 不匹配，未部署")
    extracted=work/"extracted"; extracted.mkdir(exist_ok=True)
    with py7zr.SevenZipFile(archive) as z:
        for name in z.getnames():
            p=PurePosixPath(name.replace("\\","/"))
            if p.is_absolute() or ".." in p.parts or ":" in name:
                raise RuntimeError("不安全的压缩包路径")
        z.extractall(extracted)
    binaries=list(extracted.rglob("*.exe"))
    print("可用 Windows 引擎：",[str(p.relative_to(extracted)) for p in binaries],flush=True)
    choices=[p for p in binaries if "x86-64" in str(p).lower() or "x64" in str(p).lower()]
    if not choices:
        choices=[p for p in binaries if "arm" not in str(p).lower()]
    if len(choices)!=1:
        raise RuntimeError(f"无法唯一确定 Windows x64 通用引擎：{choices}")
    engine=ROOT/"engine"; engine.mkdir(exist_ok=True)
    shutil.copy2(choices[0],engine/"pikafish.exe")
    networks=list(extracted.rglob("*.nnue"))
    for net in networks: shutil.copy2(net,engine/net.name)
    # Include exact corresponding source and license for redistribution.
    source_url=f"https://github.com/official-pikafish/Pikafish/archive/refs/tags/{TAG}.zip"
    download(source_url,engine/"Pikafish-source.zip")
    download(f"https://raw.githubusercontent.com/official-pikafish/Pikafish/{TAG}/Copying.txt",engine/"Copying.txt")
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in engine.iterdir() if p.is_file() and p.name!="manifest.json"}
    (engine/"manifest.json").write_text(json.dumps({"tag":TAG,"release_url":URL,"archive_sha256":actual,"source_url":source_url,"files":files},indent=2),encoding="utf-8")
    print("引擎已部署：",engine/"pikafish.exe",flush=True)


if __name__=="__main__":
    try: install()
    except Exception as e:
        print("安装失败：",e,file=sys.stderr); raise SystemExit(1)
