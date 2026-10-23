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
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".install-state.json"
LOG_PATH = ROOT / "logs" / "install.log"

HOST = sys.platform.startswith("win")
VENV_PY = Path("Scripts/python.exe") if HOST else Path("bin/python")

# 节点依赖不再手写清单：每个包自己带 requirements*.txt / pyproject.toml，按清单装。
# 下面几组是「装了会出事 / 太大 / 要编译」的例外，按名字拦。

# 必须和 cv2 一起统一安装的构建（见 _unify_opencv）
OPENCV_PIN = "opencv-contrib-python-headless>=4.12,<5"

# 基座包：节点依赖不许改它们的版本，否则 ComfyUI / torch 就坏了
PROTECTED_PACKAGES = {
    "torch", "torchvision", "torchaudio", "numpy", "scipy",
    "transformers", "tokenizers", "huggingface-hub", "safetensors", "pillow",
    "aiohttp", "yarl", "pydantic", "pydantic-settings", "alembic", "sqlalchemy",
    "comfyui-frontend-package", "comfyui-workflow-templates",
    "comfyui-embedded-docs", "comfy-kitchen", "comfy-aimdo", "blake3", "simpleeval",
}

# 要编译 / 平台没有轮子 / 纯可选加速：默认跳过，--with-build 才装
SKIP_UNLESS_BUILD = {
    "llama-cpp-python", "xformers", "bitsandbytes",
    "flash-attn", "flash-attn-2", "sageattention", "sageattn3", "fp4attn-cuda",
    "nvvfx", "pynvvideocodec", "triton", "insightface", "mediapipe",
}

# 体积大 / 带模型 / 容易拖崩环境：默认跳过，--with-heavy 才装
HEAVY_PACKAGES = {
    "demucs", "openai-whisper", "voxcpm", "clip-interrogator",
    "stable-ts", "modelscope", "torchcodec",
}

# cv2 由 _unify_opencv 统一装一个构建；节点清单里的 opencv* 全部忽略（混装必崩）
OPENCV_PACKAGES = {
    "opencv-python", "opencv-python-headless",
    "opencv-contrib-python", "opencv-contrib-python-headless",
}

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
        explicit = getattr(args, "venv_dir", None)
        self.venv_is_explicit = bool(explicit)
        self.panel_venv: Path = Path(explicit) if explicit else ROOT / ".venv"
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
            # pip 和 curl 都认这两组；PIP_PROXY 让 pip 明确走代理（少一条警告）
            full_env.update({
                "HTTP_PROXY": self.args.proxy, "HTTPS_PROXY": self.args.proxy,
                "http_proxy": self.args.proxy, "https_proxy": self.args.proxy,
                "PIP_PROXY": self.args.proxy,
            })
        mirror = getattr(self.args, "pip_mirror", "") or ""
        if mirror:
            # 国内源：所有 pip 子进程都走这个索引（命令行显式 --index-url 的步骤不受影响）
            full_env["PIP_INDEX_URL"] = mirror
            if mirror.startswith("http://"):
                full_env["PIP_TRUSTED_HOST"] = mirror.split("//", 1)[1].split("/", 1)[0]
        # 无人值守：不让 pip 弹任何交互（凭据、确认），网络卡住时也早点失败
        full_env.setdefault("PIP_NO_INPUT", "1")
        full_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        full_env.setdefault("PIP_PROGRESS_BAR", "off")
        full_env.setdefault("PIP_TIMEOUT", "30")
        full_env.setdefault("PIP_RETRIES", "2")
        if env:
            full_env.update(env)

        # 边跑边把输出写进日志（以前是跑完才写，pip 一慢就看起来像卡死）
        proc = subprocess.Popen(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            env=full_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        tail: list[str] = []
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            assert proc.stdout is not None
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
                text = line.rstrip()
                if not text:
                    continue
                tail.append(text)
                del tail[:-40]
                if not quiet:
                    print(line, end="", flush=True)
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"命令失败（{code}）：{pretty}\n" + "\n".join(tail[-25:]))

    def python_of(self, venv: Path) -> str:
        return str(venv / VENV_PY)

    # -- 步骤包装 --------------------------------------------------------- #
    COMFY_STEPS = {"comfy_clone", "comfy_venv", "comfy_torch", "comfy_deps",
                   "comfy_nodes", "git_packs", "node_deps", "extra_deps", "models"}

    def step(self, sid: str, title: str, fn, payload=None) -> None:
        if self.args.skip_comfy and sid in self.COMFY_STEPS:
            self.log(f"[skip] {title}")
            return
        if self.args.comfy_only and sid in {"check", "dirs", "panel_venv", "panel_deps", "db", "config", "scripts"}:
            # conmfy-only 仍需要 dirs / config 的一部分，这里只跳过面板专属
            if sid in {"panel_venv", "panel_deps", "db"}:
                self.log(f"[skip] {title}")
                return
        # 环境检查很便宜，而且决定 venv 放哪（低完整性标签），每次都跑
        if sid == "check":
            self.log(f"[..]   {title}")
            fn()
            self.mark(sid)
            self.log(f"[done] {title}")
            return
        # payload 用来记「这次装的是哪份清单」：节点包增删后能自动重跑
        fingerprint = payload() if payload else None
        if self.done(sid):
            # venv 可能被用户手动删掉，但状态文件仍记着“已完成”——必须校验真实存在
            missing_venv = (
                (sid == "panel_venv" and not (self.panel_venv / VENV_PY).exists())
                or (sid == "comfy_venv" and not (self.comfy_venv / VENV_PY).exists())
            )
            if fingerprint and self.state.get(sid, {}).get("fingerprint") != fingerprint:
                self.log(f"[..]   {title}（依赖清单有变化，重跑）")
            elif missing_venv:
                self.log(f"[..]   {title}（虚拟环境已不存在，重新创建）")
            else:
                self.log(f"[ok]   {title}（已完成，跳过）")
                return
        self.log(f"[..]   {title}")
        fn()
        self.mark(sid, {"fingerprint": fingerprint} if fingerprint else None)
        self.log(f"[done] {title}")


# --------------------------------------------------------------------------- #
# 步骤实现
# --------------------------------------------------------------------------- #

def _low_integrity_dir(path: Path) -> bool:
    """Windows：目录是否带 Low Mandatory Level（低完整性进程写不了系统临时目录）。"""
    if not HOST:
        return False
    try:
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                             errors="replace", timeout=20).stdout
    except Exception:
        return False
    return "Low Mandatory Level" in out


def _fallback_venv_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "director-console" / ".venv"
    return ROOT.parent / ".director-venv"


def step_check(inst: Installer) -> None:
    inst.log(f"  python: {sys.version.split()[0]} @ {sys.executable}")

    # DSH/AppLocker 之类会给目录打 Low 标签，venv 里的 python 会继承，
    # 于是 pip 的临时目录退化到项目目录并卡死。这里提前把 venv 挪到项目外。
    if _low_integrity_dir(ROOT):
        inst.log("  [warn] 项目目录带 Low 完整性标签：venv 里的 pip 会卡在临时目录")
        if inst.venv_is_explicit:
            inst.log(f"  沿用 --venv-dir：{inst.panel_venv}")
        else:
            inst.panel_venv = _fallback_venv_dir()
            inst.log(f"  已自动改用项目外的 venv：{inst.panel_venv}")
    if sys.version_info < (3, 10):
        raise RuntimeError("需要 Python >= 3.10")
    if not inst.args.skip_comfy and not shutil.which("git"):
        raise RuntimeError("未找到 git，请先安装（apt-get install git）")

    # 临时目录自检：Windows 上如果项目目录（或里面的 python.exe）被打了「低完整性」标签，
    # 从这里起的 venv 进程就写不了系统临时目录，Python 会退化成拿当前目录当 temp，
    # 于是 pip 把 pip-install-* / tmp* 丢进项目里、并且看起来像卡死。提前查出来。
    try:
        tmpdir = Path(tempfile.gettempdir()).resolve()
    except Exception as exc:
        raise RuntimeError(f"找不到可写的临时目录：{exc}") from exc
    if str(tmpdir).lower() == str(ROOT).lower() or str(tmpdir).lower().startswith(str(ROOT).lower() + os.sep):
        raise RuntimeError(
            f"临时目录被解析成了项目目录（{tmpdir}）。pip 会把临时文件写进项目并卡住。\n"
            "  处理：确认 TEMP/TMP 指向一个可写目录；Windows 上还要确认项目目录没有低完整性标签"
        )
    probe = tmpdir / f".dc-tmp-probe-{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(
            f"临时目录不可写：{tmpdir}（{exc}）。pip 会卡住。\n"
            "  Windows 常见原因：项目目录被打了「低完整性」标签，里面的 python.exe 继承后写不了系统 temp\n"
            "  处理：icacls \"<项目目录>\" /setintegritylevel (OI)(CI)M /T，然后删掉 .venv 重建"
        ) from exc
    inst.log(f"  临时目录: {tmpdir}")
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
        if _low_integrity_dir(inst.panel_venv):
            inst.log("  [warn] 现有 venv 带 Low 标签，pip 会卡住；建议删除后重跑")
        inst.log("  已存在，跳过创建")
        return
    inst.run([sys.executable, "-m", "venv", str(inst.panel_venv)])


def step_panel_deps(inst: Installer) -> None:
    if not (inst.panel_venv / VENV_PY).exists():
        inst.log("  venv 不存在，先创建")
        step_panel_venv(inst)
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
    if not (inst.comfy_venv / VENV_PY).exists():
        inst.log("  ComfyUI venv 不存在，先创建")
        step_comfy_venv(inst)
    py = inst.python_of(inst.comfy_venv)
    req = str(inst.comfy_dir / "requirements.txt")
    # 不钉 numpy<2 / scipy<1.14：
    #  1) Python 3.13 根本没有 numpy<2 的轮子，钉了就装不上；
    #  2) 打崩 cv2 的是「多个 opencv 构建混装」，不是 numpy 版本 —— 那个在 _unify_opencv 里统一。
    try:
        inst.run([py, "-m", "pip", "install", "-r", req])
    except RuntimeError:
        # 国内镜像经常缺 ComfyUI 新发的包（例如 comfyui-workflow-templates-media-assets-*），
        # 缺就用官方源再解析一次
        if not (getattr(inst.args, "pip_mirror", "") or "").strip():
            raise
        inst.log("  [warn] 镜像里缺包，改走官方 PyPI 再试一次")
        inst.run([py, "-m", "pip", "install", "-r", req,
                  "--index-url", "https://pypi.org/simple"])


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_pack(inst: Installer, urls: list[str], sha: str) -> Path:
    dst = ROOT / "logs" / "director-node-pack.zip"
    dst.parent.mkdir(parents=True, exist_ok=True)
    for url in urls:
        inst.log(f"  下载节点包：{url}")
        try:
            _download(url, dst, inst.args.proxy)
        except Exception as exc:
            inst.log(f"  [warn] 失败：{exc}")
            continue
        actual = _sha256(dst)
        if sha and actual != sha:
            inst.log(f"  [warn] sha256 不匹配（{actual[:12]} != {sha[:12]}），换下一个地址")
            dst.unlink(missing_ok=True)
            continue
        inst.log(f"  校验通过（{dst.stat().st_size / 1024 / 1024:.0f} MB）")
        return dst
    raise RuntimeError("节点包下载失败：请检查 content/node-pack.json 的 urls")


def _copy_from_comfy(inst: Installer, source: Path, pack_names: list[str]) -> int:
    src_dir = source / "custom_nodes"
    if not src_dir.exists():
        raise RuntimeError(f"{src_dir} 不存在")
    target = inst.comfy_dir / "custom_nodes"
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in pack_names:
        src = src_dir / name
        if src.is_dir():
            shutil.copytree(src, target / name, dirs_exist_ok=True)
            copied += 1
        else:
            inst.log(f"  [warn] 缺少 {name}")
    return copied


def _manifest() -> dict:
    path = ROOT / "content" / "node-pack.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def step_comfy_nodes(inst: Installer) -> None:
    manifest_path = ROOT / "content" / "node-pack.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    target = inst.comfy_dir / "custom_nodes"
    target.mkdir(parents=True, exist_ok=True)

    # 1) 直接从已有 ComfyUI 复制（内网/离线最省事）
    if inst.args.from_comfy:
        names = list((manifest.get("packs") or {}).keys())
        if not names:
            raise RuntimeError("content/node-pack.json 里没有 packs 列表")
        copied = _copy_from_comfy(inst, inst.args.from_comfy, names)
        inst.log(f"  从 {inst.args.from_comfy} 复制了 {copied} 个节点包")
        return

    # 2) 本地 zip 优先
    pack = inst.args.node_pack
    if inst.args.node_source in ("auto", "local") and pack.exists():
        inst.log(f"  使用本地节点包：{pack}")
    elif inst.args.node_source == "local":
        raise RuntimeError(f"--nodes local 但找不到 {pack}")
    else:
        urls = [u for u in (manifest.get("urls") or []) if u]
        if not urls:
            raise RuntimeError(
                "没有可用的节点包地址：请把 zip 传到 GitHub Release，"
                "并把下载地址填进 content/node-pack.json 的 urls"
            )
        pack = _download_pack(inst, urls, manifest.get("sha256", ""))
        inst.args.node_pack = pack

    if inst.args.dry_run:
        inst.log(f"  将解压 {pack} -> {target}")
        return

    tmp = ROOT / "logs" / "_nodepack"
    if tmp.exists():
        shutil.rmtree(tmp)
    with zipfile.ZipFile(pack) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/").lstrip("/")
            if name.endswith("/") or not name or name.startswith("__MACOSX/"):
                continue
            if name.startswith("../") or "/../" in name:
                raise RuntimeError(f"节点包里有越界路径：{info.filename}")
            dest = tmp / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fh, dest.open("wb") as out:
                shutil.copyfileobj(fh, out)

    src = tmp / "custom_nodes"
    if not src.is_dir():
        raise RuntimeError(f"节点包结构不对：{pack} 里没有 custom_nodes/ 目录")
    skip = {"ComfyUI-FeiHou-Toolbox"}
    count = 0
    for item in sorted(src.iterdir()):
        if item.is_dir() and item.name not in skip:
            shutil.copytree(item, target / item.name, dirs_exist_ok=True)
            count += 1
    shutil.rmtree(tmp, ignore_errors=True)
    inst.log(f"  复制 {count} 个节点包")


def step_git_packs(inst: Installer) -> None:
    """清单里点名的 git 节点包（如 RES4LYF）直接 clone 进 custom_nodes。

    zip 里没有这些包：它们只通过「注册枚举值」生效（采样器等），
    节点类扫描找不到，塞进 zip 也容易被漏掉。
    """
    if getattr(inst.args, "skip_git_packs", False):
        inst.log("  --skip-git-packs，跳过 git 节点包")
        return
    manifest = _manifest()
    packs = manifest.get("git_packs") or []
    if not packs:
        inst.log("  清单里没有 git_packs，跳过")
        return
    target = inst.comfy_dir / "custom_nodes"
    target.mkdir(parents=True, exist_ok=True)
    py = inst.python_of(inst.comfy_venv)

    for spec in packs:
        name = str(spec.get("dir") or spec.get("name") or "").strip()
        repo = str(spec.get("repo") or "").strip()
        if not name or not repo:
            continue
        dest = target / name
        if dest.exists() and any(dest.iterdir()):
            inst.log(f"  {name} 已存在，跳过 clone")
        elif inst.args.dry_run:
            inst.log(f"  将 clone {repo} -> {dest}")
            continue
        else:
            ref = str(spec.get("ref") or "main")
            inst.log(f"  clone {name}（{ref}）")
            try:
                inst.run(["git", "clone", "--depth", "1", "--branch", ref, repo, str(dest)])
            except RuntimeError as exc:
                inst.log(f"  [warn] {name} clone 失败：{exc}；工作流用到它的节点时会降级")
                continue
        for pkg in spec.get("pip") or []:
            if inst.args.dry_run:
                inst.log(f"  将安装依赖 {pkg}")
                continue
            try:
                inst.run([py, "-m", "pip", "install", pkg])
            except RuntimeError as exc:
                inst.log(f"  [warn] {name} 依赖 {pkg} 安装失败：{exc}")


def _nvcc_version() -> tuple[int, int]:
    try:
        out = subprocess.run(["nvcc", "--version"], capture_output=True, text=True, timeout=20).stdout
        match = re.search(r"release (\d+)\.(\d+)", out)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception:
        pass
    return 0, 0


def _safe_cuda_arch(arch: str) -> tuple[str, str]:
    """按本机 nvcc 版本裁剪架构列表，返回 (架构, 说明)。

    sm_120（5090）需要 CUDA >= 12.8 的 nvcc，旧版会直接报
    `nvcc fatal: Unsupported gpu architecture 'compute_120'`；
    只编 89 时带 PTX，50 系卡运行时会 JIT，能跑但不是原生。
    """
    major, minor = _nvcc_version()
    parts = [x.strip() for x in str(arch or "").split(";") if x.strip()]
    dropped = []
    if (major, minor) < (12, 8):
        kept = []
        for item in parts:
            if item == "120":
                dropped.append(item)
                continue
            kept.append(item)
        parts = kept
    result = ";".join(parts) or "89"
    note = ""
    if dropped:
        note = f"（nvcc {major}.{minor} 不支持 sm_120，已去掉，运行时靠 PTX JIT）"
    return result, note


def step_extra_deps(inst: Installer) -> None:
    """清单里的 pip 扩展（默认不装，要显式开 --with-llm 之类）。

    目前只有 llama-cpp-python：本地 GGUF 文本模型用。
    默认装 PyPI 轮子（CPU，几秒完成）；加 --llama-cuda 才源码编译 CUDA 版（10 分钟起）。
    """
    manifest = _manifest()
    extras = manifest.get("pip_extras") or []
    if not extras:
        return
    py = inst.python_of(inst.comfy_venv)
    for spec in extras:
        name = str(spec.get("name") or "").strip()
        flag = str(spec.get("flag") or "").strip()
        if flag and not getattr(inst.args, flag, False):
            inst.log(f"  {name} 未启用（加 --{flag.replace('_', '-')} 才装）：{spec.get('note', '')}")
            continue
        spec_str = str(spec.get("spec") or name)
        if inst.args.dry_run:
            inst.log(f"  将安装 {spec_str}")
            continue
        if name == "llama-cpp-python" and getattr(inst.args, "llama_cuda", False):
            arch, note = _safe_cuda_arch(getattr(inst.args, "llama_cuda_arch", "89"))
            inst.log(f"  {name}：CUDA 源码编译（arch={arch}）{note}，预计 8~25 分钟")
            try:
                inst.run(
                    [py, "-m", "pip", "install", "--no-cache-dir", "--no-build-isolation", spec_str],
                    env={"CMAKE_ARGS": (f"-DGGML_CUDA=on -DGGML_NATIVE=OFF "
                                        f"-DCMAKE_CUDA_ARCHITECTURES={arch}"),
                         "FORCE_CMAKE": "1"},
                )
            except Exception:
                inst.log(f"  [warn] {name} CUDA 编译失败，改回 CPU 轮子")
                inst.run([py, "-m", "pip", "install", spec_str])
        else:
            inst.run([py, "-m", "pip", "install", spec_str])


# --------------------------------------------------------------------------- #
# 节点依赖：按每个包自己的清单装，且不许动基座
# --------------------------------------------------------------------------- #
def _norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", (name or "").strip().lower())


def _req_name(line: str) -> str:
    """从 requirement 行里取出包名；git+/URL/参数行返回空串。"""
    text = (line or "").strip()
    if not text or text.startswith(("#", "-")):
        return ""
    if "://" in text or text.startswith("git+"):
        return ""
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._\-]*", text)
    return match.group(0) if match else ""


def _read_requirements(path: Path, seen: set[Path] | None = None) -> list[str]:
    """读 requirements.txt，展开 -r 引用，丢掉索引类参数。"""
    seen = seen if seen is not None else set()
    if path in seen or not path.exists():
        return []
    seen.add(path)
    out: list[str] = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement")):
            parts = line.split(None, 1)
            if len(parts) == 2:
                out += _read_requirements(path.parent / parts[1].strip(), seen)
            continue
        if line.startswith(("-i ", "--index-url", "--extra-index-url", "-f ", "--find-links",
                            "--trusted-host", "--no-binary", "--only-binary", "--no-deps",
                            "--pre", "--upgrade")):
            continue
        out.append(line)
    return out


def _pyproject_dependencies(path: Path) -> list[str]:
    """pyproject 的 [project].dependencies；Python 3.10 没 tomllib 时用正则兜底。"""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        import tomllib

        data = tomllib.loads(text)
        deps = (data.get("project") or {}).get("dependencies") or []
        return [str(item) for item in deps]
    except Exception:
        pass
    match = re.search(r"^\s*dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    if not match:
        return []
    pairs = re.findall(r"'([^']+)'|\"([^\"]+)\"", match.group(1))
    return [a or b for a, b in pairs]


def collect_pack_requirements(comfy_dir: Path) -> dict[str, list[str]]:
    """每个 custom_node 包声明的依赖：requirements*.txt（跳过 dev）+ pyproject。"""
    packs: dict[str, list[str]] = {}
    root = comfy_dir / "custom_nodes"
    if not root.is_dir():
        return packs
    for node in sorted(root.iterdir()):
        if not node.is_dir() or node.name.startswith((".", "__")):
            continue
        lines: list[str] = []
        for req in sorted(node.glob("requirements*.txt")):
            if "dev" in req.name.lower():
                continue
            lines += _read_requirements(req)
        pyproject = node / "pyproject.toml"
        if pyproject.exists():
            lines += _pyproject_dependencies(pyproject)
        unique: list[str] = []
        seen: set[str] = set()
        for line in lines:
            key = _norm_name(_req_name(line)) or line
            if key in seen:
                continue
            seen.add(key)
            unique.append(line)
        if unique:
            packs[node.name] = unique
    return packs


def _deps_fingerprint(packs: dict[str, list[str]]) -> str:
    import hashlib

    raw = json.dumps({k: v for k, v in sorted(packs.items())}, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _freeze_versions(py: str) -> dict[str, str]:
    proc = subprocess.run([py, "-m", "pip", "freeze", "--all"],
                          capture_output=True, text=True, errors="replace")
    versions: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if "==" not in line or line.startswith(("#", "-")):
            continue
        name, version = line.split("==", 1)
        versions[_norm_name(name)] = version.strip()
    return versions


def _write_constraints(py: str) -> Path | None:
    """把基座包的当前版本钉成约束，节点依赖只能迁就它。"""
    versions = _freeze_versions(py)
    lines = [f"{name}=={versions[name]}" for name in sorted(versions) if name in PROTECTED_PACKAGES]
    if not lines:
        return None
    path = ROOT / "logs" / "node-deps-constraints.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _pip(inst: Installer, py: str, *args) -> tuple[bool, str]:
    try:
        inst.run([py, "-m", "pip", *args])
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)


def _error_line(err: str) -> str:
    """从 pip 的整段输出里挑一行真正的原因（冲突对、ERROR、最后一行）。"""
    lines = [ln.strip() for ln in str(err or "").splitlines() if ln.strip()]
    for index, line in enumerate(lines):
        if line.startswith("The conflict is caused by"):
            for candidate in lines[index + 1:index + 4]:
                if "constraint" in candidate.lower() or "user requested" in candidate.lower():
                    return candidate[:200]
            if index + 1 < len(lines):
                return lines[index + 1][:200]
    for line in reversed(lines):
        low = line.lower()
        if line.startswith(("ERROR", "error:")) or "conflict" in low or "no matching distribution" in low:
            return line[:200]
    return lines[-1][:200] if lines else "未知错误"


def _install_requirements(inst: Installer, py: str, reqs: list[str],
                          constraints: Path | None, label: str) -> tuple[list[str], list[str]]:
    """先整包装一遍；失败再逐个装，返回（装失败的, 因基座冲突跳过的）。"""
    failed: list[str] = []
    skipped: list[str] = []
    if not reqs:
        return failed, skipped

    tmp = ROOT / "logs" / "_node_reqs.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(reqs) + "\n", encoding="utf-8")
    common = ["install", "-r", str(tmp), "--upgrade-strategy", "only-if-needed"]
    if constraints:
        common += ["-c", str(constraints)]
    ok, err = _pip(inst, py, *common)
    tmp.unlink(missing_ok=True)
    if ok:
        return failed, skipped

    inst.log(f"  [warn] {label} 整包安装失败，改成逐个装：{_error_line(err)}")
    mirror = (getattr(inst.args, "pip_mirror", "") or "").strip()
    for req in reqs:
        args = ["install", req, "--upgrade-strategy", "only-if-needed"]
        if constraints:
            args += ["-c", str(constraints)]
        ok, err = _pip(inst, py, *args)
        if not ok and mirror:
            # 镜像缺这个包（国内源同步滞后很常见）：换官方源再试一次
            retry = ["install", req, "--upgrade-strategy", "only-if-needed",
                     "--index-url", "https://pypi.org/simple"]
            if constraints:
                retry += ["-c", str(constraints)]
            ok2, err2 = _pip(inst, py, *retry)
            if ok2:
                inst.log(f"  [info] {req}：镜像里没有，已从官方 PyPI 装上")
                continue
            err = err2
        if ok:
            continue
        reason = _error_line(err)
        if _norm_name(_req_name(req)) in PROTECTED_PACKAGES:
            skipped.append(req)
            inst.log(f"  [skip] {req}：要改基座版本，跳过（{reason}）")
        else:
            failed.append(req)
            inst.log(f"  [warn] {req} 装不上：{reason}")
    return failed, skipped


def _unify_opencv(inst: Installer, py: str) -> None:
    """只留一个 cv2：混装会让 cv2.dnn 丢符号（DictValue / dnn_superres）。"""
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
              "'| dnn.DictValue', hasattr(cv2.dnn, 'DictValue')); "
              "assert hasattr(cv2.dnn, 'DictValue'), 'cv2 与 numpy 不匹配：换个 opencv 版本再试'"])


def _write_node_deps_report(inst: Installer, packs: dict[str, list[str]],
                            failed: dict[str, list[str]], heavy: dict[str, list[str]],
                            build: dict[str, list[str]]) -> None:
    path = ROOT / "logs" / "node-deps-report.txt"
    lines = [f"节点依赖报告 @ {time.strftime('%Y-%m-%d %H:%M:%S')}", f"ComfyUI: {inst.comfy_dir}", ""]
    lines.append(f"有依赖清单的节点包：{len(packs)}")
    for name, reqs in packs.items():
        lines.append(f"  {name}: {len(reqs)} 项")
    lines.append("")
    for title, table in (("装失败", failed),
                         ("默认跳过（--with-heavy 才装）", heavy),
                         ("默认跳过（--with-build 才装）", build)):
        lines.append(f"== {title} ==")
        if not table:
            lines.append("  （无）")
        for name, items in table.items():
            lines.append(f"  {name}: {', '.join(items)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")

    if failed:
        inst.log(f"  [warn] {sum(len(v) for v in failed.values())} 个依赖没装上，见 {path}")
    if heavy or build:
        inst.log("  这些默认没装（用到再说）："
                 + ", ".join(sorted({i for v in list(heavy.values()) + list(build.values()) for i in v})))
    inst.log(f"  报告：{path}")


def step_node_deps(inst: Installer) -> None:
    py = inst.python_of(inst.comfy_venv)
    packs = collect_pack_requirements(inst.comfy_dir)
    if not packs:
        inst.log("  custom_nodes 里没有依赖清单，跳过")
        return

    constraints = None
    if not inst.args.dry_run:
        constraints = _write_constraints(py)
        if constraints:
            inst.log(f"  基座约束：{constraints.name}（节点依赖不许改 torch/numpy/transformers 等版本）")
        if "torch" not in _freeze_versions(py):
            # 节点清单里只要出现 torch，pip 会从 PyPI 拉一个 CPU 版，把 CUDA 版顶掉
            inst.log("  [warn] 这个 venv 还没有 torch，节点依赖可能会装成 CPU 版；"
                     "先跑「PyTorch」那一步再装节点依赖")

    failed: dict[str, list[str]] = {}
    heavy: dict[str, list[str]] = {}
    build: dict[str, list[str]] = {}

    for name, reqs in packs.items():
        keep: list[str] = []
        for req in reqs:
            key = _norm_name(_req_name(req))
            if key in OPENCV_PACKAGES:
                continue  # cv2 最后统一装一个构建，见 _unify_opencv
            if key in SKIP_UNLESS_BUILD and not inst.args.with_build:
                build.setdefault(name, []).append(req)
                continue
            if key in HEAVY_PACKAGES and not inst.args.with_heavy:
                heavy.setdefault(name, []).append(req)
                continue
            keep.append(req)
        if not keep:
            continue
        inst.log(f"  {name}（{len(keep)} 项）")
        bad, skipped = _install_requirements(inst, py, keep, constraints, name)
        if bad or skipped:
            failed[name] = bad + skipped

    _unify_opencv(inst, py)
    _write_node_deps_report(inst, packs, failed, heavy, build)


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


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        import tarfile

        with tarfile.open(archive) as tf:
            tf.extractall(dest)


def _verify_ffmpeg(binary: Path) -> tuple[bool, str]:
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
            ok, note = _verify_ffmpeg(Path(found))
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


def _check_node_imports(inst: Installer) -> None:
    """跑 ComfyUI 自己的导入自检：哪些 custom_nodes 起不来，一眼看到。"""
    main_py = inst.comfy_dir / "main.py"
    cpy = inst.python_of(inst.comfy_venv)
    if not main_py.exists() or not Path(cpy).exists():
        return
    inst.log("  custom_nodes 导入自检（几十秒，不加载模型）…")
    out = ""
    for extra in (["--quick-test-for-ci", "--cpu"], ["--quick-test-for-ci"], []):
        try:
            proc = subprocess.run([cpy, "main.py", *extra], cwd=str(inst.comfy_dir),
                                  capture_output=True, text=True, errors="replace", timeout=900)
        except subprocess.TimeoutExpired:
            inst.log("  [warn] 导入自检超时，跳过")
            return
        out = (proc.stdout or "") + (proc.stderr or "")
        if "unrecognized arguments" in out and extra:
            continue
        break

    log_file = ROOT / "logs" / "comfy-import-check.log"
    log_file.write_text(out, encoding="utf-8")
    failed = [line.strip() for line in out.splitlines() if "IMPORT FAILED" in line]
    if not failed:
        inst.log("  全部 custom_nodes 导入正常")
    else:
        inst.log(f"  [warn] {len(failed)} 个节点包导入失败（缺依赖，先看 logs/node-deps-report.txt）：")
        for line in failed:
            inst.log("    " + line.replace(str(inst.comfy_dir), ".").replace("\\", "/"))
    inst.log(f"  完整输出：{log_file}")


def step_selfcheck(inst: Installer) -> None:
    if inst.args.dry_run:
        inst.log("  dry-run，跳过自检")
        return
    py = inst.python_of(inst.panel_venv)
    inst.log("  venv 临时目录：")
    inst.run([py, "-c", "import tempfile;print('  ', tempfile.gettempdir())"])
    inst.log("  面板依赖：")
    inst.run([py, "-c", "import fastapi, uvicorn, sqlalchemy, alembic, httpx, yaml; print('  ok')"])

    if not inst.args.skip_comfy:
        cpy = inst.python_of(inst.comfy_venv)
        inst.log("  ComfyUI 依赖：")
        inst.run([cpy, "-c",
                  "import torch, numpy, cv2; print('  torch', torch.__version__, "
                  "'| cuda', torch.cuda.is_available(), '| numpy', numpy.__version__, "
                  "'| cv2', cv2.__version__); "
                  "assert hasattr(cv2.dnn, 'DictValue'), 'cv2 混装/ABI 不匹配'"])
        if not inst.args.skip_node_check:
            _check_node_imports(inst)

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
    p.add_argument("--venv-dir", type=Path, default=None,
                   help="面板 venv 位置（默认项目内 .venv；目录带 Low 标签时会自动挪到项目外）")
    p.add_argument("--comfy-dir", type=Path, default=Path("/root/ComfyUI") if not HOST else Path("D:/ComfyUI"))
    p.add_argument("--comfy-ref", default="v0.39.0")
    p.add_argument("--comfy-port", type=int, default=8188)
    p.add_argument("--port", type=int, default=6006, help="面板端口（AutoDL 用 6006）")
    p.add_argument("--torch", default="cu130",
                   help="torch 的 CUDA 通道：cu130（默认，支持 50 系）/ cu128 / cpu")
    p.add_argument("--torch-version", default="2.11.0", help="留空则装该通道最新版")
    p.add_argument("--torchvision-version", default="0.26.0", help="留空则装该通道最新版")
    p.add_argument("--models-dir", default="", help="模型目录（建议 /root/autodl-tmp/models）")
    p.add_argument("--node-pack", type=Path, default=None, help="本地 zip 路径")
    p.add_argument("--node-source", "--nodes", dest="node_source", default="auto",
                   choices=["auto", "local", "download"],
                   help="auto=本地优先，没有就按清单下载；local=只用本地；download=强制下载")
    p.add_argument("--from-comfy", type=Path, default=None,
                   help="从已有 ComfyUI 目录复制节点包（内网/离线推荐）")
    p.add_argument("--proxy", default="", help="安装期代理，如 http://127.0.0.1:1081（pip 和下载都会走）")
    p.add_argument("--pip-mirror", default="",
                   help="pip 索引（国内加速），如 https://pypi.tuna.tsinghua.edu.cn/simple；"
                        "留空用官方源")
    p.add_argument("--skip-comfy", action="store_true")
    p.add_argument("--comfy-only", action="store_true")
    p.add_argument("--skip-ffmpeg", action="store_true", help="不安装 ffmpeg")
    p.add_argument("--ffmpeg-source", default="auto", choices=["auto", "full", "system", "imageio"],
                   help="auto=系统优先→下载 full→imageio 兜底")
    p.add_argument("--ffmpeg-url", default="", help="自定义 full 版下载地址（zip/tar.xz）")
    p.add_argument("--with-heavy", action="store_true",
                   help="额外安装 demucs / whisper / voxcpm / clip-interrogator / modelscope 等重依赖")
    p.add_argument("--with-llm", action="store_true",
                   help="额外安装 llama-cpp-python（本地 GGUF 文本模型，图片对口型等卡需要）")
    p.add_argument("--llama-cuda", action="store_true",
                   help="配合 --with-llm：源码编译 CUDA 版（10~25 分钟，CPU 版几秒）")
    p.add_argument("--llama-cuda-arch", default="89",
                   help="CUDA 架构，89=4090 / 120=5090 / 86=3090")
    p.add_argument("--skip-git-packs", action="store_true",
                   help="不 clone 清单里的 git 节点包（如 RES4LYF）")
    p.add_argument("--with-build", action="store_true",
                   help="额外安装需要编译的（llama-cpp-python / xformers / bitsandbytes / insightface 等）")
    p.add_argument("--skip-node-check", action="store_true",
                   help="跳过自定义节点导入自检（默认会在装完后跑一次）")
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
        ROOT / "logs" / "director-node-pack.zip",   # 上次下载留下的，直接复用
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
        ("git_packs", "git 节点包", step_git_packs),
        ("node_deps", "节点依赖", step_node_deps),
        ("extra_deps", "扩展依赖", step_extra_deps),
        ("ffmpeg", "FFmpeg", step_ffmpeg),
        ("config", "写配置", step_config),
        ("models", "模型目录", step_models),
        ("scripts", "启动脚本", step_scripts),
        ("selfcheck", "自检", step_selfcheck),
    ]

    # 节点依赖用「当前 custom_nodes 的清单指纹」判断要不要重跑：
    # 新增/删掉节点包后，即使状态文件里记过 node_deps，也会自动重装。
    deps_payload = None
    if not args.skip_comfy:
        deps_payload = lambda: _deps_fingerprint(collect_pack_requirements(args.comfy_dir))

    for sid, title, fn in steps:
        try:
            inst.step(sid, title, lambda f=fn: f(inst), deps_payload if sid == "node_deps" else None)
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
