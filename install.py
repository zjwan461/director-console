#!/usr/bin/env python3
"""导演台安装器：把一台裸机变成「面板 + ComfyUI」可用环境。

用法示例：
    python install.py                      # 全量安装（面板 + ComfyUI）
    python install.py --skip-comfy         # 只装面板
    python install.py --comfy-only         # 只装 ComfyUI
    python install.py --dry-run            # 只打印将执行的命令
    python install.py --models-dir /root/autodl-tmp/models
    python install.py --proxy http://127.0.0.1:1081 --torch cu130

设计要点：
- 只用标准库，Windows / Linux 都能跑；
- 每一步有 id，成功后写进 .install-state.json，可重复执行（幂等）；
- --force 忽略状态全部重跑；
- 所有命令输出落到 logs/install.log，失败时回显最后一段；
- ComfyUI 用独立 venv，面板 venv 不装 torch。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".install-state.json"
LOG_PATH = ROOT / "logs" / "install.log"

HOST = sys.platform.startswith("win")
VENV_PY = Path("Scripts/python.exe") if HOST else Path("bin/python")

COMFY_LIGHT_DEPS = [
    "psutil", "color-matcher", "mss",
    "imageio", "imageio-ffmpeg", "diffusers", "accelerate", "sentencepiece",
    "spandrel", "matplotlib", "peft", "lark", "kornia", "av", "transformers",
    "huggingface_hub", "safetensors", "einops", "omegaconf", "gguf",
    "onnxruntime", "Cython", "librosa", "google-generativeai",
    "rotary_embedding_torch",
]

COMFY_HEAVY_DEPS = ["demucs", "openai-whisper", "voxcpm", "clip_interrogator", "mtcnn-runtime"]

KEY_NODES = [
    "CR Text", "CR Prompt Text", "INTConstant", "VHS_VideoCombine",
    "VHS_LoadAudioUpload", "VRAMCleanup", "RAMCleanup", "H3SigmaRefiner",
    "ModelPreviewOverrideKJ", "ImageResizeKJ2", "ZealmanH3ModelLoader",
    "SeedVR2VideoUpscaler", "PT_H3ConcatAVLatent",
]


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #
class Installer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.state: dict = self._load_state()
        self.comfy_dir: Path = args.comfy_dir
        self.panel_venv: Path = ROOT / ".venv"
        self.comfy_venv: Path = self.comfy_dir / ".venv"
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # -- 日志 / 状态 ------------------------------------------------------- #
    def log(self, msg: str = "") -> None:
        print(msg, flush=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")

    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_state(self) -> None:
        STATE_PATH.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")

    def done(self, step: str) -> bool:
        return bool(self.state.get(step)) and not self.args.force

    def mark(self, step: str, payload: dict | None = None) -> None:
        if self.args.dry_run:
            return
        self.state[step] = {"at": int(time.time()), **(payload or {})}
        self._save_state()

    # -- 命令执行 --------------------------------------------------------- #
    def run(self, cmd: list[str], cwd: Path | None = None, env: dict | None = None,
            quiet: bool = False) -> None:
        pretty = " ".join(str(c) for c in cmd)
        self.log(f"  $ {pretty}")
        if self.args.dry_run:
            return
        full_env = os.environ.copy()
        if self.args.proxy:
            full_env.update({"HTTP_PROXY": self.args.proxy, "HTTPS_PROXY": self.args.proxy})
        if env:
            full_env.update(env)
        proc = subprocess.run(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(proc.stdout or "")
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout or "").splitlines()[-25:])
            raise RuntimeError(f"命令失败（{proc.returncode}）：{pretty}\n{tail}")
        if not quiet and proc.stdout.strip():
            tail = "\n".join(proc.stdout.splitlines()[-6:])
            self.log(tail)

    def python_of(self, venv: Path) -> str:
        return str(venv / VENV_PY)

    # -- 步骤包装 --------------------------------------------------------- #
    COMFY_STEPS = {"comfy_clone", "comfy_venv", "comfy_torch", "comfy_deps",
                   "comfy_nodes", "node_deps", "models"}

    def step(self, sid: str, title: str, fn) -> None:
        if self.args.skip_comfy and sid in self.COMFY_STEPS:
            self.log(f"[skip] {title}")
            return
        if self.args.comfy_only and sid in {"check", "dirs", "panel_venv", "panel_deps", "db", "config", "scripts"}:
            # conmfy-only 仍需要 dirs / config 的一部分，这里只跳过面板专属
            if sid in {"panel_venv", "panel_deps", "db"}:
                self.log(f"[skip] {title}")
                return
        if self.done(sid):
            self.log(f"[ok]   {title}（已完成，跳过）")
            return
        self.log(f"[..]   {title}")
        fn()
        self.mark(sid)
        self.log(f"[done] {title}")


# --------------------------------------------------------------------------- #
# 步骤实现
# --------------------------------------------------------------------------- #
def step_check(inst: Installer) -> None:
    inst.log(f"  python: {sys.version.split()[0]} @ {sys.executable}")
    if sys.version_info < (3, 10):
        raise RuntimeError("需要 Python >= 3.10")
    if not inst.args.skip_comfy and not shutil.which("git"):
        raise RuntimeError("未找到 git，请先安装（apt-get install git）")
    free = shutil.disk_usage(ROOT).free / 1024**3
    inst.log(f"  磁盘可用: {free:.1f} GB")
    if free < 15 and not inst.args.skip_comfy:
        inst.log("  [warn] 磁盘不足 15GB，ComfyUI + torch 可能装不下")


def step_dirs(inst: Installer) -> None:
    for path in (ROOT / "data", ROOT / "logs", inst.args.comfy_dir):
        if not path.exists():
            inst.log(f"  创建 {path}")
            if not inst.args.dry_run:
                path.mkdir(parents=True, exist_ok=True)


def step_panel_venv(inst: Installer) -> None:
    if inst.panel_venv.exists() and (inst.panel_venv / VENV_PY).exists():
        inst.log("  已存在，跳过创建")
        return
    inst.run([sys.executable, "-m", "venv", str(inst.panel_venv)])


def step_panel_deps(inst: Installer) -> None:
    py = inst.python_of(inst.panel_venv)
    inst.run([py, "-m", "pip", "install", "-U", "pip", "-q"])
    inst.run([py, "-m", "pip", "install", "-r", str(ROOT / "backend" / "requirements.txt")])


def step_db(inst: Installer) -> None:
    py = inst.python_of(inst.panel_venv)
    inst.run([py, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend")


def step_comfy_clone(inst: Installer) -> None:
    main_py = inst.comfy_dir / "main.py"
    if main_py.exists():
        inst.log("  ComfyUI 已存在，跳过 clone")
        return
    if inst.comfy_dir.exists() and any(inst.comfy_dir.iterdir()):
        raise RuntimeError(f"{inst.comfy_dir} 非空且没有 main.py，请先清空或换 --comfy-dir")
    inst.run([
        "git", "clone", "--depth", "1", "--branch", inst.args.comfy_ref,
        "https://github.com/comfyanonymous/ComfyUI.git", str(inst.comfy_dir),
    ])


def step_comfy_venv(inst: Installer) -> None:
    if (inst.comfy_venv / VENV_PY).exists():
        inst.log("  已存在，跳过创建")
        return
    inst.run([sys.executable, "-m", "venv", str(inst.comfy_venv)])


def step_comfy_torch(inst: Installer) -> None:
    py = inst.python_of(inst.comfy_venv)
    channel = inst.args.torch
    index = f"https://download.pytorch.org/whl/{channel}"
    inst.run([py, "-m", "pip", "install", "-U", "pip", "-q"])

    if channel in {"cu118", "cu121", "cu124", "cu126"}:
        inst.log("  [warn] 该通道不支持 RTX 50 系（sm_120），新卡请用 cu128/cu130")

    pinned = []
    if inst.args.torch_version:
        pinned.append(f"torch=={inst.args.torch_version}")
    else:
        pinned.append("torch")
    if inst.args.torchvision_version:
        pinned.append(f"torchvision=={inst.args.torchvision_version}")
    else:
        pinned.append("torchvision")
    pinned.append(f"torchaudio=={inst.args.torch_version}" if inst.args.torch_version else "torchaudio")

    try:
        inst.run([py, "-m", "pip", "install", *pinned, "--index-url", index])
    except RuntimeError as exc:
        if not (inst.args.torch_version or inst.args.torchvision_version):
            raise
        inst.log(f"  [warn] 钉版本安装失败，回退到该通道最新版：{exc}")
        inst.run([py, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", index])


def step_comfy_deps(inst: Installer) -> None:
    py = inst.python_of(inst.comfy_venv)
    inst.run([py, "-m", "pip", "install", "-r", str(inst.comfy_dir / "requirements.txt"),
              "numpy<2", "scipy<1.14"])


def step_comfy_nodes(inst: Installer) -> None:
    pack = inst.args.node_pack
    if not pack.exists():
        raise RuntimeError(f"找不到节点包 {pack}（用 --node-pack 指定）")
    target = inst.comfy_dir / "custom_nodes"
    target.mkdir(parents=True, exist_ok=True)
    if inst.args.dry_run:
        inst.log(f"  将解压 {pack} -> {target}")
        return
    tmp = ROOT / "logs" / "_nodepack"
    if tmp.exists():
        shutil.rmtree(tmp)
    with zipfile.ZipFile(pack) as zf:
        for info in zf.infolist():
            # Windows 的 Compress-Archive 会用反斜杠做分隔符，解压前统一成 /
            name = info.filename.replace("\\", "/").lstrip("/")
            if name.endswith("/") or not name:
                continue
            target = tmp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fh, target.open("wb") as out:
                shutil.copyfileobj(fh, out)
    src = tmp / "custom_nodes"
    count = 0
    skip = {"ComfyUI-FeiHou-Toolbox"}  # 上游 video_combine_v2.py 为 0 字节，导入必失败
    for item in sorted(src.iterdir()):
        if item.is_dir() and item.name not in skip:
            shutil.copytree(item, target / item.name, dirs_exist_ok=True)
            count += 1
    shutil.rmtree(tmp, ignore_errors=True)
    inst.log(f"  复制 {count} 个节点包")


OPENCV_PIN = "opencv-contrib-python-headless==4.10.0.84"


def step_node_deps(inst: Installer) -> None:
    py = inst.python_of(inst.comfy_venv)
    deps = list(COMFY_LIGHT_DEPS)
    if inst.args.with_heavy:
        deps += COMFY_HEAVY_DEPS
    inst.run([py, "-m", "pip", "install", *deps, "numpy<2", "scipy<1.14"])

    # opencv-python / opencv-python-headless 混装会导致
    #   cv2.dnn 没有 DictValue → import cv2 直接崩
    # 统一成只保留一个 contrib-headless（同时带 dnn_superres 等 contrib 模块）
    inst.log("  统一 cv2（卸载混装的 opencv 包并清掉残留目录）")
    inst.run([py, "-m", "pip", "uninstall", "-y",
              "opencv-python", "opencv-python-headless",
              "opencv-contrib-python", "opencv-contrib-python-headless"], quiet=True)
    inst.run([py, "-c",
              "import pathlib,shutil,site;"
              "[shutil.rmtree(p, ignore_errors=True) for base in site.getsitepackages() "
              "for p in pathlib.Path(base).glob('cv2*') if p.exists()]"])
    inst.run([py, "-m", "pip", "install", "--force-reinstall", "--no-deps", OPENCV_PIN])
    inst.run([py, "-c",
              "import cv2; print('  cv2', cv2.__version__, cv2.__file__, "
              "'dnn', hasattr(cv2.dnn, 'DictValue')); assert hasattr(cv2.dnn, 'DictValue')"])


FULL_FFMPEG = {
    "windows": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "linux-x86_64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    "linux-aarch64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
}


def _platform_key() -> str:
    if HOST:
        return "windows"
    machine = platform.machine().lower()
    return "linux-aarch64" if machine in ("aarch64", "arm64") else "linux-x86_64"


def _download(url: str, dst: Path, proxy: str) -> None:
    """优先 urllib；某些公司代理会返回 407，退回 curl。"""
    errors = []
    try:
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(url, timeout=120) as resp, dst.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        if dst.exists() and dst.stat().st_size > 1024:
            return
        errors.append("urllib 下载内容过小")
    except Exception as exc:
        errors.append(f"urllib: {exc}")

    curl = shutil.which("curl")
    if curl:
        cmd = [curl, "-sS", "-L", "--fail", "--retry", "2", "-o", str(dst)]
        if proxy:
            cmd += ["--proxy", proxy]
        cmd.append(url)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 1024:
            return
        errors.append(f"curl: {proc.stderr.strip()[:200]}")
    raise RuntimeError("；".join(errors))


def _extract(archive: pathlib.Path, dest: pathlib.Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        import tarfile

        with tarfile.open(archive) as tf:
            tf.extractall(dest)


def _verify_ffmpeg(binary: pathlib.Path) -> tuple[bool, str]:
    try:
        filters = subprocess.run([str(binary), "-hide_banner", "-filters"],
                                 capture_output=True, text=True, timeout=60).stdout
        encoders = subprocess.run([str(binary), "-hide_banner", "-encoders"],
                                  capture_output=True, text=True, timeout=60).stdout
    except Exception as exc:
        return False, f"无法执行：{exc}"
    need = {"subtitles": " subtitles " in filters, "xfade": " xfade " in filters,
            "libx264": "libx264" in encoders}
    missing = [k for k, ok in need.items() if not ok]
    return (not missing), ("完整" if not missing else f"缺少 {', '.join(missing)}")


def step_ffmpeg(inst: Installer) -> None:
    """优先装 full 版 ffmpeg（libass/xfade/libx264），失败再用 imageio-ffmpeg 兜底。"""
    if inst.args.skip_ffmpeg:
        inst.log("  --skip-ffmpeg，跳过")
        return
    if inst.args.dry_run:
        inst.log("  dry-run：将尝试下载 full 版 ffmpeg，失败回退 imageio-ffmpeg")
        return

    tools = ROOT / "tools" / "ffmpeg"
    ffmpeg_bin = tools / ("ffmpeg.exe" if HOST else "ffmpeg")
    ffprobe_bin = tools / ("ffprobe.exe" if HOST else "ffprobe")

    source = inst.args.ffmpeg_source
    if source in ("auto", "system"):
        found = shutil.which("ffmpeg")
        if found:
            ok, note = _verify_ffmpeg(pathlib.Path(found))
            inst.log(f"  系统 ffmpeg：{found}（{note}）")
            if ok or source == "system":
                inst.state["ffmpeg_path"] = found
                probe = shutil.which("ffprobe")
                inst.state["ffprobe_path"] = probe or ""
                return

    if source in ("auto", "full") and not (ffmpeg_bin.exists() and ffmpeg_bin.stat().st_size > 0):
        url = inst.args.ffmpeg_url or FULL_FFMPEG[_platform_key()]
        archive = ROOT / "logs" / Path(url).name
        inst.log(f"  下载 full 版 ffmpeg：{url}")
        try:
            _download(url, archive, inst.args.proxy)
            inst.log(f"  下载完成 {archive.stat().st_size / 1024 / 1024:.0f} MB，解压中")
            unpack = ROOT / "logs" / "_ffmpeg"
            if unpack.exists():
                shutil.rmtree(unpack)
            _extract(archive, unpack)
            found_ff = next(unpack.rglob("ffmpeg.exe" if HOST else "ffmpeg"), None)
            found_fp = next(unpack.rglob("ffprobe.exe" if HOST else "ffprobe"), None)
            if not found_ff:
                raise RuntimeError("压缩包里没有 ffmpeg")
            tools.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found_ff, ffmpeg_bin)
            if found_fp:
                shutil.copy2(found_fp, ffprobe_bin)
            for b in (ffmpeg_bin, ffprobe_bin):
                if b.exists() and not HOST:
                    b.chmod(0o755)
            ok, note = _verify_ffmpeg(ffmpeg_bin)
            inst.log(f"  full 版自检：{note}")
            if ok:
                inst.state["ffmpeg_path"] = str(ffmpeg_bin)
                inst.state["ffprobe_path"] = str(ffprobe_bin) if ffprobe_bin.exists() else ""
                archive.unlink(missing_ok=True)
                shutil.rmtree(unpack, ignore_errors=True)
                return
            raise RuntimeError(f"full 版缺少能力：{note}")
        except Exception as exc:
            inst.log(f"  [warn] full 版失败，回退 imageio-ffmpeg：{exc}")
            archive.unlink(missing_ok=True)

    # 兜底：imageio-ffmpeg
    py = inst.python_of(inst.panel_venv) if (inst.panel_venv / VENV_PY).exists() else sys.executable
    inst.run([py, "-m", "pip", "install", "imageio-ffmpeg", "-q"])
    code = "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"
    proc = subprocess.run([py, "-c", code], capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        inst.log("  [warn] 没有可用的 ffmpeg，成片导出不可用")
        return
    src = Path(proc.stdout.strip())
    dst = tools.parent / ("ffmpeg.exe" if HOST else "ffmpeg")
    if not inst.args.dry_run:
        shutil.copy2(src, dst)
        dst.chmod(0o755)
    ok, note = _verify_ffmpeg(dst)
    inst.state["ffmpeg_path"] = str(dst)
    inst.state["ffprobe_path"] = ""
    inst.log(f"  使用 imageio-ffmpeg：{dst}（{note}）")


def step_config(inst: Installer) -> None:
    conf = ROOT / "config.local.yaml"
    comfy_py = inst.python_of(inst.comfy_venv)
    lines = ["# 由 install.py 生成：本机部署覆盖项（git 忽略）"]
    if not inst.args.skip_comfy:
        lines += [
            "comfy:",
            "  mode: local",
            f"  base_url: http://127.0.0.1:{inst.args.comfy_port}",
            f"  local_url: http://127.0.0.1:{inst.args.comfy_port}",
            "  local:",
            f"    workdir: {inst.comfy_dir.as_posix()}",
            f"    python: {comfy_py}",
            f'    args: ["main.py", "--listen", "127.0.0.1", "--port", "{inst.args.comfy_port}"]',
        ]
    ff = inst.state.get("ffmpeg_path") or ""
    if ff:
        lines += ["ffmpeg:", f'  path: {ff}']
    lines += ["app:", "  host: 0.0.0.0", f"  port: {inst.args.port}"]
    block = "\n".join(lines) + "\n"

    if conf.exists() and not inst.args.force_config:
        inst.log(f"  {conf.name} 已存在，保留原内容（--force-config 覆盖）")
        return
    if inst.args.dry_run:
        inst.log(block)
        return
    conf.write_text(block, encoding="utf-8")
    inst.log(f"  写入 {conf}")


def step_models(inst: Installer) -> None:
    if not inst.args.models_dir:
        inst.log("  未指定 --models-dir，跳过")
        return
    models = inst.comfy_dir / "models"
    src = Path(inst.args.models_dir)
    if inst.args.dry_run:
        inst.log(f"  将把 {models} 链到 {src}")
        return
    src.mkdir(parents=True, exist_ok=True)
    if models.is_symlink():
        inst.log("  已是软链接，跳过")
        return
    if models.exists() and any(models.iterdir()):
        inst.log(f"  {models} 非空，保留现场；请手动把内容迁到 {src}")
        return
    if models.exists():
        models.rmdir()
    try:
        models.symlink_to(src, target_is_directory=True)
        inst.log(f"  {models} -> {src}")
    except OSError as exc:
        inst.log(f"  建软链接失败（{exc}），请手动处理")


def step_scripts(inst: Installer) -> None:
    panel_py = inst.python_of(inst.panel_venv)
    comfy_py = inst.python_of(inst.comfy_venv)

    if HOST:
        bat = ROOT / ("start-all.bat" if not inst.args.skip_comfy else "start-panel.bat")
        if bat.exists() and not inst.args.force_config:
            inst.log(f"  {bat.name} 已存在，跳过")
            return
        lines = ["@echo off", "chcp 65001 >nul", 'cd /d "%~dp0"']
        if not inst.args.skip_comfy:
            lines += [
                f'start "ComfyUI" /D "{inst.comfy_dir}" "{comfy_py}" main.py --listen 127.0.0.1 --port {inst.args.comfy_port}',
                "timeout /t 5 >nul",
            ]
        lines.append(f'"{panel_py}" -m uvicorn app.main:app --host 0.0.0.0 --port {inst.args.port} --app-dir backend')
        if not inst.args.dry_run:
            bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        inst.log(f"  {bat.name}")
        return

    sh = ROOT / ("start-all.sh" if not inst.args.skip_comfy else "start-panel.sh")
    if sh.exists() and not inst.args.force_config:
        inst.log(f"  {sh.name} 已存在，跳过")
        return
    body = ['#!/usr/bin/env bash', 'set -euo pipefail', 'cd "$(dirname "$0")"', 'mkdir -p logs']
    if not inst.args.skip_comfy:
        body += [
            f'PANEL_PY="{panel_py}"',
            f'COMFY_PY="{comfy_py}"',
            'nohup "$COMFY_PY" main.py --listen 127.0.0.1 --port '
            f'{inst.args.comfy_port} > "{inst.comfy_dir}/comfyui.log" 2>&1 &',
            'echo $! > logs/comfy.pid',
            'sleep 3',
            f'exec "$PANEL_PY" -m uvicorn app.main:app --host 0.0.0.0 --port {inst.args.port} --app-dir backend',
        ]
    else:
        body.append(f'exec "{panel_py}" -m uvicorn app.main:app --host 0.0.0.0 --port {inst.args.port} --app-dir backend')
    if not inst.args.dry_run:
        sh.write_text("\n".join(body) + "\n", encoding="utf-8")
        sh.chmod(0o755)
    inst.log(f"  {sh.name}")


def step_selfcheck(inst: Installer) -> None:
    if inst.args.dry_run:
        inst.log("  dry-run，跳过自检")
        return
    py = inst.python_of(inst.panel_venv)
    inst.log("  面板依赖：")
    inst.run([py, "-c", "import fastapi, uvicorn, sqlalchemy, alembic, httpx, yaml; print('  ok')"])

    if not inst.args.skip_comfy:
        cpy = inst.python_of(inst.comfy_venv)
        inst.log("  ComfyUI 依赖：")
        inst.run([cpy, "-c", "import torch; print('  torch', torch.__version__, 'cuda', torch.cuda.is_available())"])

    inst.log("  ffmpeg：")
    ff = inst.state.get("ffmpeg_path") or shutil.which("ffmpeg")
    if ff:
        try:
            ver = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=10)
            first = (ver.stdout or "").splitlines()[0] if ver.stdout else ff
            inst.log(f"  {first}")
        except Exception:
            inst.log(f"  {ff}")
    else:
        inst.log("  未找到（成片导出不可用）")

    inst.log("  模型清单：")
    manifest = ROOT / "content" / "model-manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        inst.log(f"  {data.get('with_url')}/{data.get('total')} 个依赖有下载地址")

    inst.log("  在线检查（ComfyUI 未启动时跳过）：")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{inst.args.comfy_port}/object_info", timeout=5) as resp:
            mapping = json.loads(resp.read())
        missing = [n for n in KEY_NODES if n not in mapping]
        inst.log(f"  ComfyUI 已在线，节点 {len(mapping)} 个；缺 {missing or '无'}")
    except Exception:
        inst.log("  ComfyUI 未启动，跳过")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="导演台安装器")
    p.add_argument("--comfy-dir", type=Path, default=Path("/root/ComfyUI") if not HOST else Path("D:/ComfyUI"))
    p.add_argument("--comfy-ref", default="v0.39.0")
    p.add_argument("--comfy-port", type=int, default=8188)
    p.add_argument("--port", type=int, default=6006, help="面板端口（AutoDL 用 6006）")
    p.add_argument("--torch", default="cu130",
                   help="torch 的 CUDA 通道：cu130（默认，支持 50 系）/ cu128 / cpu")
    p.add_argument("--torch-version", default="2.11.0", help="留空则装该通道最新版")
    p.add_argument("--torchvision-version", default="0.26.0", help="留空则装该通道最新版")
    p.add_argument("--models-dir", default="", help="模型目录（建议 /root/autodl-tmp/models）")
    p.add_argument("--node-pack", type=Path, default=None)
    p.add_argument("--proxy", default="", help="安装期代理，如 http://127.0.0.1:1081")
    p.add_argument("--skip-comfy", action="store_true")
    p.add_argument("--comfy-only", action="store_true")
    p.add_argument("--skip-ffmpeg", action="store_true", help="不安装 ffmpeg")
    p.add_argument("--ffmpeg-source", default="auto", choices=["auto", "full", "system", "imageio"],
                   help="auto=系统优先→下载 full→imageio 兜底")
    p.add_argument("--ffmpeg-url", default="", help="自定义 full 版下载地址（zip/tar.xz）")
    p.add_argument("--with-heavy", action="store_true", help="额外安装 demucs / whisper / llama 等重依赖")
    p.add_argument("--force", action="store_true", help="忽略状态文件，全部重跑")
    p.add_argument("--force-config", action="store_true", help="覆盖 config.local.yaml / 启动脚本")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def find_pack(explicit: Path | None) -> Path:
    if explicit:
        return explicit
    candidates = [
        ROOT / "director-node-pack.zip",
        ROOT.parent / "director-node-pack.zip",
        ROOT / "tools" / "director-node-pack.zip",
        ROOT / "docs" / "director-node-pack.zip",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def main() -> int:
    args = parse_args()
    args.node_pack = find_pack(args.node_pack)
    inst = Installer(args)
    inst.log("=" * 60)
    inst.log(f"导演台安装器  root={ROOT}")
    inst.log(f"面板端口 {args.port} · ComfyUI {args.comfy_dir} :{args.comfy_port}")
    inst.log("=" * 60)

    steps = [
        ("check", "环境检查", step_check),
        ("dirs", "目录准备", step_dirs),
        ("panel_venv", "面板 venv", step_panel_venv),
        ("panel_deps", "面板依赖", step_panel_deps),
        ("db", "数据库迁移", step_db),
        ("comfy_clone", "ComfyUI 源码", step_comfy_clone),
        ("comfy_venv", "ComfyUI venv", step_comfy_venv),
        ("comfy_torch", "PyTorch", step_comfy_torch),
        ("comfy_deps", "ComfyUI 依赖", step_comfy_deps),
        ("comfy_nodes", "custom_nodes", step_comfy_nodes),
        ("node_deps", "节点依赖", step_node_deps),
        ("ffmpeg", "FFmpeg", step_ffmpeg),
        ("config", "写配置", step_config),
        ("models", "模型目录", step_models),
        ("scripts", "启动脚本", step_scripts),
        ("selfcheck", "自检", step_selfcheck),
    ]

    for sid, title, fn in steps:
        try:
            inst.step(sid, title, lambda f=fn: f(inst))
        except Exception as exc:
            inst.log(f"\n[FAIL] {title}: {exc}")
            inst.log(f"日志：{LOG_PATH}")
            return 1

    inst.log("=" * 60)
    script = ("start-all" if not args.skip_comfy else "start-panel") + (".bat" if HOST else ".sh")
    inst.log("安装完成。启动：")
    inst.log("  " + script)
    inst.log(f"面板：http://127.0.0.1:{args.port}")
    inst.log("AutoDL：控制台点「自定义服务」拿到公网地址（映射的就是 6006）")
    inst.log("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
