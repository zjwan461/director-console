"""视频取帧工具：优先 ffmpeg，缺失时生成占位图（保证流程不断）。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from . import ffmpeg as ffmpeg_mod


def ffmpeg_available() -> bool:
    return bool(ffmpeg_mod.ffmpeg_path())


def _placeholder(out: Path, label: str) -> None:
    img = Image.new("RGB", (720, 1280), (18, 20, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 680, 1240], outline=(70, 78, 110), width=3)
    draw.multiline_text((80, 560), label, fill=(200, 206, 230), spacing=8)
    img.save(out, "PNG")


def extract_last_frame(video: Path, out: Path) -> tuple[bool, str]:
    """从视频取最后一帧；返回 (是否真实取帧, 说明)。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_mod.ffmpeg_path()
    if ffmpeg:
        cmd = [
            ffmpeg, "-y", "-loglevel", "error",
            "-sseof", "-0.3", "-i", str(video),
            "-frames:v", "1", "-q:v", "2", str(out),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
                return True, "ffmpeg"
        except Exception as exc:
            _placeholder(out, f"取帧失败：{exc}")
            return False, str(exc)
    _placeholder(out, "末帧占位\n\n安装 ffmpeg 后可自动取真实末帧")
    return False, "ffmpeg 未安装"


def copy_as_frame(image: Path, out: Path) -> tuple[bool, str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(image, out)
        return True, "copy"
    except Exception as exc:
        return False, str(exc)
