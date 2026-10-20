"""ffmpeg 封装：探测、逐段标准化、拼接、抽封面。

设计要点：
- 每一段先标准化成同样的编码参数（分辨率/帧率/采样率），再用 concat demuxer 无损拼接；
  避免直接 concat 不同参数视频导致的音画不同步。
- 没有音轨的片段自动补一段等长静音，保证 concat 时每个输入都有音频。
- ffmpeg 不在 PATH 时，可用 config.yaml 的 ffmpeg.path 指定绝对路径。
"""
from __future__ import annotations

import asyncio
import json
import re
import os
import shutil
from pathlib import Path
from typing import Iterable

from .config import settings


class FFmpegMissing(RuntimeError):
    pass


def _cfg(key: str, default: str) -> str:
    return str(settings.get(f"ffmpeg.{key}", default) or default)


def _imageio_ffmpeg() -> str | None:
    """imageio-ffmpeg 自带的静态二进制（install.py 的兜底来源）。"""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if Path(exe).exists() else None
    except Exception:
        return None


def ffmpeg_path() -> str | None:
    configured = _cfg("path", "")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    tools = Path(settings.paths["root"]) / "tools"
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for candidate in (tools / exe, tools / "ffmpeg" / exe):
        if candidate.exists():
            return str(candidate)
    return _imageio_ffmpeg()


def ffprobe_path() -> str | None:
    ff = ffmpeg_path()
    if ff:
        candidate = Path(ff).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if candidate.exists():
            return str(candidate)
        candidate = Path(ff).with_name("ffprobe")
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffprobe")


def status() -> dict:
    ff = ffmpeg_path()
    probe = ffprobe_path()
    return {
        "available": bool(ff),
        "ffmpeg": ff or "",
        "ffprobe": probe or "",
        "configured_path": _cfg("path", ""),
        "hint": "" if ff else "未找到 ffmpeg：请安装后加入 PATH，或在 config.yaml 设置 ffmpeg.path",
    }


async def _run(cmd: list[str], timeout: float = 1800) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("ffmpeg 执行超时")
    text = (stderr or b"").decode("utf-8", "replace")
    return proc.returncode or 0, text


async def _probe_json(path: Path, args: list[str]) -> dict:
    probe = ffprobe_path()
    if not probe:
        return {}
    code, out = await _run([probe, "-v", "error", "-print_format", "json", *args, str(path)], timeout=60)
    if code != 0:
        return {}
    try:
        return json.loads(out or "{}")
    except json.JSONDecodeError:
        # stderr 里混了日志时，截取第一个 { 到最后一个 }
        start, end = out.find("{"), out.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(out[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


async def _ffmpeg_stderr(path: Path) -> str:
    """没有 ffprobe 时的兜底：用 ffmpeg -i 的 stderr 解析媒体信息。"""
    ff = ffmpeg_path()
    if not ff:
        return ""
    _, text = await _run([ff, "-hide_banner", "-i", str(path)], timeout=60)
    return text


async def has_audio(path: Path) -> bool:
    if ffprobe_path():
        data = await _probe_json(path, ["-select_streams", "a", "-show_entries", "stream=index"])
        return bool(data.get("streams"))
    return "Audio:" in await _ffmpeg_stderr(path)


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


async def duration_of(path: Path) -> float:
    if ffprobe_path():
        data = await _probe_json(path, ["-show_entries", "format=duration"])
        try:
            return float(data["format"]["duration"])
        except (KeyError, TypeError, ValueError):
            pass
    match = _DURATION_RE.search(await _ffmpeg_stderr(path))
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return 0.0


async def normalize_clip(
    src: Path,
    dst: Path,
    width: int,
    height: int,
    fps: int,
    with_audio: bool | None = None,
) -> None:
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    if with_audio is None:
        with_audio = await has_audio(src)

    crf = _cfg("crf", "20")
    preset = _cfg("preset", "medium")
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    )

    cmd = [ff, "-y", "-loglevel", "error", "-i", str(src)]
    if not with_audio:
        dur = max(await duration_of(src), 1.0)
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        audio_map = "1:a:0"
    else:
        audio_map = "0:a:0"

    cmd += [
        "-map", "0:v:0", "-map", audio_map,
        "-vf", vf,
        "-c:v", "libx264", "-crf", crf, "-preset", preset, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]
    code, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"标准化失败：{_tail(err)}")


async def concat_clips(clips: Iterable[Path], out: Path, workdir: Path) -> None:
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    clips = list(clips)
    if not clips:
        raise RuntimeError("没有可拼接的片段")
    list_file = workdir / "concat.txt"
    # concat demuxer 的路径要转义单引号
    lines = ["file '" + str(p).replace("'", "'\\''") + "'" for p in clips]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    code, err = await _run([
        ff, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", "-movflags", "+faststart", str(out),
    ])
    if code != 0:
        raise RuntimeError(f"拼接失败：{_tail(err)}")


async def extract_cover(video: Path, out: Path, at: float = 1.0) -> None:
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    code, err = await _run([
        ff, "-y", "-loglevel", "error",
        "-ss", f"{max(at, 0):.2f}", "-i", str(video),
        "-frames:v", "1", "-q:v", "2", str(out),
    ], timeout=120)
    if code != 0:
        raise RuntimeError(f"抽封面失败：{_tail(err)}")


def _tail(text: str, lines: int = 6) -> str:
    rows = [r for r in (text or "").strip().splitlines() if r.strip()]
    return "\n".join(rows[-lines:]) or "未知错误"
