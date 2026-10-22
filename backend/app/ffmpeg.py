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
import subprocess
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


def _run_sync(cmd: list[str], timeout: float, cwd: Path | None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg 执行超时") from exc
    return proc.returncode or 0, (proc.stderr or b"").decode("utf-8", "replace")


async def _run(cmd: list[str], timeout: float = 1800, cwd: Path | None = None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except NotImplementedError:
        # Windows 上 uvicorn --reload 用 SelectorEventLoop，它不支持子进程；
        # 不兜底的话合成完音频、算时长的这一步会抛一个没有信息的 NotImplementedError
        return await asyncio.to_thread(_run_sync, cmd, timeout, cwd)
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("ffmpeg 执行超时")
    text = (stderr or b"").decode("utf-8", "replace")
    return proc.returncode or 0, text


def _capture_sync(cmd: list[str]) -> bytes:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return proc.stdout or b""


async def _capture(cmd: list[str]) -> bytes:
    """拿子进程 stdout；事件循环不支持子进程时退回线程。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        return out or b""
    except NotImplementedError:
        return await asyncio.to_thread(_capture_sync, cmd)


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

def capabilities() -> dict:
    """探测 ffmpeg 是否支持字幕烧录 / 转场 / x264。"""
    import subprocess as sp

    ff = ffmpeg_path()
    if not ff:
        return {"available": False}
    try:
        filters = sp.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30).stdout
        encoders = sp.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return {"available": True, "subtitles": False, "xfade": False, "libx264": False}
    return {
        "available": True,
        "subtitles": " subtitles " in filters,
        "xfade": " xfade " in filters,
        "libx264": "libx264" in encoders,
        "ffprobe": bool(ffprobe_path()),
    }


async def concat_with_transition(
    clips: list[Path],
    out: Path,
    workdir: Path,
    kind: str = "fade",
    duration: float = 0.4,
) -> None:
    """带转场的拼接：xfade（画面）+ acrossfade（声音）。"""
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    if len(clips) < 2 or kind not in {"fade", "dissolve"} or duration <= 0:
        await concat_clips(clips, out, workdir)
        return

    durations = [await duration_of(p) for p in clips]
    d = min(duration, min(durations) / 2)
    if d <= 0:
        await concat_clips(clips, out, workdir)
        return

    args: list[str] = [ff, "-y", "-loglevel", "error"]
    for clip in clips:
        args += ["-i", str(clip)]

    filters: list[str] = []
    v_prev = "0:v"
    a_prev = "0:a"
    offset = durations[0] - d
    for i in range(1, len(clips)):
        v_out = f"v{i}"
        a_out = f"a{i}"
        filters.append(
            f"[{v_prev}][{i}:v]xfade=transition={kind}:duration={d:.3f}:offset={offset:.3f}[{v_out}]"
        )
        filters.append(f"[{a_prev}][{i}:a]acrossfade=d={d:.3f}[{a_out}]")
        v_prev, a_prev = v_out, a_out
        if i < len(clips) - 1:
            offset += durations[i] - d

    args += [
        "-filter_complex", ";".join(filters),
        "-map", f"[{v_prev}]", "-map", f"[{a_prev}]",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out),
    ]
    code, err = await _run(args)
    if code != 0:
        raise RuntimeError("转场拼接失败：" + err[-800:])


async def process_clip(
    src: Path,
    dst: Path,
    width: int,
    height: int,
    fps: int,
    in_point: float = 0.0,
    out_point: float | None = None,
    volume_db: float = 0.0,
    muted: bool = False,
    fit: str = "letterbox",
    speed: float = 1.0,
) -> None:
    """单镜处理：裁剪 + 画布适配 + 帧率 + 音量 + 变速。

    fit: letterbox=等比缩放补黑边 / crop=裁切填满 / blur=模糊背景补边
    speed: 1.0 表示原速；仅对画面做 setpts + 音频 atempo（0.5~2.0）
    """
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    with_audio = await has_audio(src)
    fit = fit if fit in {"letterbox", "crop", "blur"} else "letterbox"
    speed = min(max(float(speed or 1.0), 0.5), 2.0)
    trimming = abs(speed - 1.0) > 0.005
    length = (out_point - in_point) if (out_point is not None and out_point > in_point) else None

    if fit == "crop":
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps}"
        )
        graph = None
    elif fit == "blur":
        graph = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma=28[bg2];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps}[v]"
        )
        vf = None
    else:
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
        )
        graph = None

    cmd = [ff, "-y", "-loglevel", "error", "-ss", f"{max(in_point, 0):.3f}", "-i", str(src)]

    if not trimming:
        # 原速：沿用 -t 输出时长（最省事，不需要 trim 滤镜）
        if length is not None:
            cmd += ["-t", f"{length:.3f}"]
        if with_audio and not muted:
            af = f"volume={volume_db}dB,aresample=48000"
            if graph:
                cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "0:a:0", "-af", af]
            else:
                cmd += ["-map", "0:v:0", "-map", "0:a:0", "-vf", vf, "-af", af]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            if graph:
                cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "1:a:0", "-shortest"]
            else:
                cmd += ["-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-shortest"]
    else:
        # 变速：-t 是输出侧限制，会把慢放截断；改用 trim + setpts 在滤镜里裁
        trim = f"trim=duration={length:.3f}," if length is not None else ""
        pts = f"setpts=(PTS-STARTPTS)/{speed:.4f},"
        if graph:
            graph = graph.replace("[0:v]", f"[0:v]{trim}{pts}", 1)
        else:
            vf = trim + pts + vf

        audio_chain = (
            (f"atrim=duration={length:.3f}," if length is not None else "")
            + f"asetpts=PTS-STARTPTS,atempo={speed:.4f},"
            + f"volume={volume_db}dB,aresample=48000"
        )
        if with_audio and not muted:
            if graph:
                graph = graph.replace("[v]", "[vout]") + f";[0:a]{audio_chain}[a]"
                cmd += ["-filter_complex", graph, "-map", "[vout]", "-map", "[a]"]
            else:
                cmd += ["-map", "0:v:0", "-map", "0:a:0", "-vf", vf, "-af", audio_chain]
        else:
            cmd += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000"]
            if graph:
                cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "1:a:0", "-shortest"]
            else:
                cmd += ["-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-shortest"]

    cmd += [
        "-c:v", "libx264", "-crf", _cfg("crf", "20"), "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(dst),
    ]
    code, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"单镜处理失败：{_tail(err)}")


def _cjk_font(size: int):
    from PIL import ImageFont

    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for item in candidates:
        if Path(item).exists():
            try:
                return ImageFont.truetype(item, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(text: str, draw, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            probe = current + char
            if draw.textlength(probe, font=font) <= max_width or not current:
                current = probe
            else:
                lines.append(current)
                current = char
        lines.append(current)
    return lines[:4]


async def make_title_card(
    out: Path,
    text: str,
    duration: float,
    width: int,
    height: int,
    fps: int = 24,
    bg_color: str = "#000000",
    bg_image: Path | None = None,
    fade: float = 0.3,
    bg_fit: str = "crop",
) -> None:
    """生成片头/片尾卡：纯色或图片背景 + 居中文字，带淡入淡出。"""
    from PIL import Image, ImageDraw

    frame = Image.new("RGB", (width, height), bg_color)
    if bg_image and bg_image.exists():
        try:
            src = Image.open(bg_image).convert("RGB")
            if bg_fit == "letterbox":
                factor = min(width / src.width, height / src.height)
                resized = src.resize((max(1, int(src.width * factor)), max(1, int(src.height * factor))))
                frame = Image.new("RGB", (width, height), bg_color)
                frame.paste(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
            else:
                scale = max(width / src.width, height / src.height)
                resized = src.resize((int(src.width * scale) + 1, int(src.height * scale) + 1))
                left = (resized.width - width) // 2
                top = (resized.height - height) // 2
                frame = resized.crop((left, top, left + width, top + height))
        except Exception:
            pass

    text = (text or "").strip()
    if text:
        draw = ImageDraw.Draw(frame)
        font = _cjk_font(max(18, height // 12))
        lines = _wrap(text, draw, font, int(width * 0.8))
        line_height = int(font.size * 1.35) if hasattr(font, "size") else int(height * 0.12)
        total = line_height * len(lines)
        y = (height - total) // 2
        for line in lines:
            w = draw.textlength(line, font=font)
            draw.text(((width - w) / 2, y), line, font=font, fill="#FFFFFF")
            y += line_height

    png = out.with_suffix(".png")
    frame.save(png)

    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    dur = max(0.5, duration)
    fade = min(fade, dur / 3)
    vf = f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={dur - fade:.2f}:d={fade:.2f}"
    code, err = await _run([
        ff, "-y", "-loglevel", "error",
        "-loop", "1", "-t", f"{dur:.3f}", "-i", str(png),
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", vf, "-r", str(fps),
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart", str(out),
    ])
    if code != 0:
        raise RuntimeError("生成片头/片尾失败：" + err[-600:])


async def extract_frames(src: Path, out_dir: Path, count: int = 3,
                          prefix: str = "f", width: int = 768) -> list[Path]:
    """按时间均匀抽 count 张 jpg，供多模态模型看画面。"""
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    count = max(1, min(count, 9))
    total = await duration_of(src)
    if total <= 0:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index in range(count):
        at = total * (index + 1) / (count + 1)
        out = out_dir / f"{prefix}_{index + 1}.jpg"
        code, err = await _run([
            ff, "-y", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(src),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out),
        ])
        if code == 0 and out.exists():
            files.append(out)
    return files


async def to_asr_wav(src: Path, out: Path) -> None:
    """抽出音轨并转成 16k 单声道 wav，供语音转写使用。"""
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    code, err = await _run([
        ff, "-y", "-loglevel", "error", "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out),
    ])
    if code != 0:
        raise RuntimeError("提取音轨失败：" + err[-400:])


async def speech_ratio(path: Path, noise_db: int = -35) -> float:
    """估算音频里“有声”的占比（0~1），用来判断镜头里有没有口播/人声。"""
    ff = ffmpeg_path()
    if not ff or not path.exists():
        return 0.0
    total = await duration_of(path)
    if total <= 0:
        return 0.0
    code, err = await _run([
        ff, "-hide_banner", "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d=0.35",
        "-f", "null", "-",
    ], timeout=120)
    silence = 0.0
    for line in err.splitlines():
        if "silence_duration:" in line:
            try:
                silence += float(line.split("silence_duration:")[1].strip().split()[0])
            except (IndexError, ValueError):
                pass
    return max(0.0, min(1.0, 1.0 - silence / total))


async def speed_audio(src: Path, out: Path, tempo: float) -> None:
    """旁白变速（1.0~1.3），用于把配音压进镜头时长。"""
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    tempo = min(max(tempo, 1.0), 1.3)
    code, err = await _run([
        ff, "-y", "-loglevel", "error", "-i", str(src),
        "-filter:a", f"atempo={tempo:.4f}",
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out),
    ])
    if code != 0:
        raise RuntimeError("旁白变速失败：" + err[-400:])


async def mix_voice(clip: Path, voice: Path, out: Path, volume_db: float = 0.0) -> None:
    """把旁白混到单镜音频上；旁白按镜头时长裁断，短了补静音。"""
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    dur = await duration_of(clip)
    filt = (
        f"[1:a]volume={volume_db}dB,atrim=0:{dur:.3f},apad,atrim=0:{dur:.3f}[vo];"
        f"[0:a][vo]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )
    code, err = await _run([
        ff, "-y", "-loglevel", "error", "-i", str(clip), "-i", str(voice),
        "-filter_complex", filt, "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out),
    ])
    if code != 0:
        raise RuntimeError("混入旁白失败：" + err[-600:])


async def build_narration_track(segments: list[tuple[Path | None, float]], out: Path) -> None:
    """按时间轴拼一条纯旁白轨（没旁白的镜头补静音），用于 BGM 闪避。"""
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    args: list[str] = [ff, "-y", "-loglevel", "error"]
    filters: list[str] = []
    labels: list[str] = []
    input_index = 0
    for index, (path, dur) in enumerate(segments):
        if path and path.exists():
            args += ["-i", str(path)]
            filters.append(
                f"[{input_index}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                f"atrim=0:{dur:.3f},apad,atrim=0:{dur:.3f}[v{index}]"
            )
            input_index += 1
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.3f}[v{index}]")
        labels.append(f"[v{index}]")
    filters.append("".join(labels) + f"concat=n={len(segments)}:v=0:a=1[a]")
    args += [
        "-filter_complex", ";".join(filters),
        "-map", "[a]", "-c:a", "aac", "-b:a", "192k", str(out),
    ]
    code, err = await _run(args)
    if code != 0:
        raise RuntimeError("生成旁白轨失败：" + err[-600:])


async def mix_bgm(
    video: Path,
    bgm: Path,
    out: Path,
    volume_db: float = -12,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    loop: bool = True,
    duck_track: Path | None = None,
    duck_db: float = -14,
) -> None:
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    total = max(await duration_of(video), 1.0)
    fade_out = min(fade_out, max(total - fade_in, 0))
    bg_chain = f"volume={volume_db}dB,aresample=48000,atrim=0:{total:.3f}"
    if fade_in > 0:
        bg_chain += f",afade=t=in:st=0:d={fade_in:.3f}"
    if fade_out > 0:
        bg_chain += f",afade=t=out:st={max(total - fade_out, 0):.3f}:d={fade_out:.3f}"
    loop_args = ["-stream_loop", "-1"] if loop else []
    duck = duck_track if (duck_track and duck_track.exists()) else None
    if duck:
        # 旁白出现时把 BGM 压下去（sidechaincompress），旁白结束后恢复
        filters = (
            f"[1:a]{bg_chain}[bg];"
            f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={duck_db}dB[sc];"
            f"[bg][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[bgd];"
            f"[0:a][bgd]amix=inputs=2:duration=first:normalize=0[a]"
        )
        inputs = ["-i", str(video), *loop_args, "-i", str(bgm), "-i", str(duck)]
    else:
        filters = f"[1:a]{bg_chain}[bg];[0:a][bg]amix=inputs=2:duration=first:normalize=0[a]"
        inputs = ["-i", str(video), *loop_args, "-i", str(bgm)]
    cmd = [
        ff, "-y", "-loglevel", "error", *inputs,
        "-filter_complex", filters,
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ]
    code, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"混音失败：{_tail(err)}")


async def mix_bgm_tracks(
    video: Path,
    tracks: list[dict],
    out: Path,
    offset: float = 0.0,
    duck_track: Path | None = None,
    duck_db: float = -14,
    duck: bool = True,
) -> None:
    """多轨 BGM 混音。

    tracks: [{path, volume_db, start, end, fade_in, fade_out, loop}]
      start/end 相对「正片」开头，渲染时统一加 offset（片头时长）
    """
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    total = max(await duration_of(video), 1.0)
    tracks = [t for t in tracks if t.get("path")]
    if not tracks:
        raise RuntimeError("没有可用的 BGM 轨道")

    args: list[str] = [ff, "-y", "-loglevel", "error", "-i", str(video)]
    index = 1
    filters: list[str] = []
    for track in tracks:
        loop = bool(track.get("loop", True))
        if loop:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(track["path"])]

        start = max(float(track.get("start") or 0) + offset, 0.0)
        raw_end = track.get("end")
        end = float(raw_end) + offset if raw_end else total
        end = min(end, total)
        length = max(end - start, 0.2)

        volume = float(track.get("volume_db", -14))
        fade_in = min(max(float(track.get("fade_in") or 0), 0.0), length / 2)
        fade_out = min(max(float(track.get("fade_out") or 0), 0.0), length / 2)

        chain = (
            f"aformat=sample_rates=48000:channel_layouts=stereo,"
            f"atrim=0:{length:.3f},asetpts=PTS-STARTPTS,"
            f"volume={volume}dB"
        )
        if fade_in > 0:
            chain += f",afade=t=in:st=0:d={fade_in:.3f}"
        if fade_out > 0:
            chain += f",afade=t=out:st={max(length - fade_out, 0):.3f}:d={fade_out:.3f}"
        if start > 0:
            chain += f",adelay={int(round(start * 1000))}|{int(round(start * 1000))}"
        chain += ",apad"
        filters.append(f"[{index}:a]{chain}[bg{index}]")
        index += 1

    mix_inputs = "".join(f"[bg{i}]" for i in range(1, index))
    filters.append(
        f"{mix_inputs}amix=inputs={index - 1}:duration=longest:normalize=0,"
        f"atrim=0:{total:.3f}[bgbus]"
    )

    duck_path = duck_track if (duck and duck_track and duck_track.exists()) else None
    if duck_path:
        args += ["-i", str(duck_path)]
        nar_index = index
        filters.append(
            f"[{nar_index}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={duck_db}dB[sc]"
        )
        filters.append(
            "[bgbus][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[bgd]"
        )
        bus = "bgd"
    else:
        bus = "bgbus"

    filters.append(
        f"[0:a][{bus}]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"
    )
    args += [
        "-filter_complex", ";".join(filters),
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ]
    code, err = await _run(args)
    if code != 0:
        raise RuntimeError(f"多轨混音失败：{_tail(err)}")


async def probe_size(path: Path) -> tuple[int, int]:
    """读视频分辨率；ffprobe 不可用时返回 (0, 0)。"""
    probe = ffprobe_path()
    if not probe or not path.exists():
        return 0, 0
    out = await _capture([
        probe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(path),
    ])
    try:
        data = json.loads((out or b"{}").decode("utf-8", "replace"))
        stream = (data.get("streams") or [{}])[0]
        return int(stream.get("width") or 0), int(stream.get("height") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0, 0


def _display_units(text: str) -> float:
    """按「一个汉字宽」为 1 个单位估算显示宽度；英文/数字约 0.55。"""
    total = 0.0
    for ch in text:
        total += 1.0 if ord(ch) > 0x2E7F else 0.55
    return total


def _has_cjk(text: str) -> bool:
    return any(ord(ch) > 0x2E7F for ch in text)


def _wrap_units(text: str, limit: float, max_lines: int = 2) -> list[str]:
    """把一段文字按显示宽度切行：中文在标点处断，英文在空格处断。"""
    if _display_units(text) <= limit:
        return [text]
    lines: list[str] = []
    rest = text
    while _display_units(rest) > limit and len(lines) < max_lines - 1:
        cut = 0
        width = 0.0
        candidates: list[int] = []
        cjk = _has_cjk(rest)
        for index, ch in enumerate(rest):
            width += 1.0 if ord(ch) > 0x2E7F else 0.55
            if width > limit:
                break
            cut = index + 1
            if cjk and ch in "，。、；：！？,.!?;: ":
                candidates.append(cut)
            elif not cjk and ch == " ":
                candidates.append(cut)
        if cut <= 0:
            break
        if candidates:
            cut = candidates[-1]
        lines.append(rest[:cut].strip("，。、；：,.!?;: "))
        rest = rest[cut:].strip("，。、；：,.!?;: ")
    if rest:
        lines.append(_clip_units(rest, limit))
    return [line for line in lines if line]


def _clip_units(text: str, limit: float) -> str:
    """截断到指定宽度，末尾加省略号。"""
    if _display_units(text) <= limit:
        return text
    clipped = ""
    width = 0.0
    for ch in text:
        width += 1.0 if ord(ch) > 0x2E7F else 0.55
        if width > limit - 1:
            break
        clipped += ch
    return clipped.rstrip("，。、；：,.!?;: ") + "…"


def _wrap_subtitle(text: str, max_chars: int, max_lines: int = 2) -> str:
    """长字幕折行。

    - 已含换行（中英双语）时：保持一段一行，超宽各行截断，不再二次折行
    - 单段时：按显示宽度折成最多 max_lines 行
    """
    text = (text or "").strip()
    if not text or max_chars <= 0:
        return text

    segments = [seg.strip() for seg in text.split("\n") if seg.strip()]
    if len(segments) > 1:
        return "\n".join(_clip_units(seg, float(max_chars)) for seg in segments[:max_lines])

    return "\n".join(_wrap_units(segments[0], float(max_chars), max_lines))


def write_srt(timeline: list[dict], path: Path, max_chars: int = 0) -> None:
    def fmt(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = []
    for item in timeline:
        text = (item.get("subtitle") or "").strip()
        if not text:
            continue
        text = _wrap_subtitle(text, max_chars)
        # 时间轴必须写成 “start --> end” 一行；拆成两行 libass 直接判定文件无效
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{fmt(item['start'])} --> {fmt(item['end'])}\n{text}\n"
        )
    # libass 靠 BOM 判断 UTF-8，没有 BOM 的中文字幕会直接“打不开”
    path.write_text("\n".join(blocks), encoding="utf-8-sig")


async def burn_subtitles(
    video: Path,
    srt: Path,
    out: Path,
    font: str = "",
    size: int = 42,
    color: str = "#FFFFFF",
    outline: int = 2,
    margin_v: int = 48,
    width: int = 0,
    height: int = 0,
) -> None:
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    style = [f"FontSize={int(size)}", f"Outline={int(outline)}", f"MarginV={int(margin_v)}"]
    if font:
        style.insert(0, f"FontName={font}")
    if color.startswith("#") and len(color) == 7:
        b, g, r = color[1:3], color[3:5], color[5:7]
        style.append(f"PrimaryColour=&H00{b}{g}{r}")
    # 相对路径 + cwd 最稳：Windows 上 libass 打开带盘符的绝对路径会失败
    # SRT 没有 PlayRes，libass 默认按 288 行高换算，720p 下字号会被放大 2.5 倍。
    # 显式给 PlayResX/PlayResY 才能让 FontSize 等于真实像素。
    if width and height:
        style.append(f"PlayResX={int(width)}")
        style.append(f"PlayResY={int(height)}")
    filt = f"subtitles={srt.name}:force_style='{','.join(style)}'"
    cmd = [
        ff, "-y", "-loglevel", "error", "-i", str(video),
        "-vf", filt, "-c:v", "libx264", "-crf", _cfg("crf", "20"), "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(out),
    ]
    code, err = await _run(cmd, cwd=srt.parent)
    if code != 0:
        raise RuntimeError(f"字幕烧录失败：{_tail(err)}")


async def pixel_format(path: Path) -> str:
    probe = ffprobe_path()
    if not probe or not path.exists():
        return ""
    out = await _capture([
        probe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=pix_fmt", "-of", "json", str(path),
    ])
    try:
        data = json.loads((out or b"{}").decode("utf-8", "replace"))
        return str((data.get("streams") or [{}])[0].get("pix_fmt") or "")
    except (json.JSONDecodeError, TypeError, ValueError):
        return ""


async def transcode_compat(src: Path, dst: Path) -> None:
    """把非 yuv420p 的成片转成通用 H.264 420p，保证 Windows/手机能播。"""
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    code, err = await _run([
        ff, "-y", "-loglevel", "error", "-i", str(src),
        "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(dst),
    ])
    if code != 0:
        raise RuntimeError("兼容性转码失败：" + err[-400:])


async def loudnorm(video: Path, out: Path, target: float = -16.0) -> None:
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    cmd = [
        ff, "-y", "-loglevel", "error", "-i", str(video),
        "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(out),
    ]
    code, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"响度标准化失败：{_tail(err)}")


async def waveform(path: Path, buckets: int = 160) -> list[float]:
    """把音轨压成 buckets 个 0~1 的峰值，用于时间轴上的波形条。"""
    ff = ffmpeg_path()
    if not ff or not path.exists():
        return []
    buckets = max(16, min(int(buckets), 600))
    raw = await _capture([
        ff, "-v", "error", "-i", str(path),
        "-ac", "1", "-ar", "4000", "-f", "s16le", "-",
    ])
    if not raw:
        return []
    import array

    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
    if not samples:
        return []
    step = max(1, len(samples) // buckets)
    peaks: list[float] = []
    for index in range(buckets):
        chunk = samples[index * step:(index + 1) * step]
        if not chunk:
            peaks.append(0.0)
            continue
        peak = max(abs(min(chunk)), abs(max(chunk))) / 32768.0
        peaks.append(round(min(peak, 1.0), 3))
    return peaks
