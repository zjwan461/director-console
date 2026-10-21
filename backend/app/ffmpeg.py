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


async def _run(cmd: list[str], timeout: float = 1800, cwd: Path | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
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
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
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
) -> None:
    """单镜处理：裁剪 + 画布适配 + 帧率 + 音量。

    fit: letterbox=等比缩放补黑边 / crop=裁切填满 / blur=模糊背景补边
    """
    ff = ffmpeg_path()
    if not ff:
        raise FFmpegMissing("未检测到 ffmpeg")
    with_audio = await has_audio(src)
    fit = fit if fit in {"letterbox", "crop", "blur"} else "letterbox"

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
    if out_point is not None and out_point > in_point:
        cmd += ["-t", f"{out_point - in_point:.3f}"]

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


async def probe_size(path: Path) -> tuple[int, int]:
    """读视频分辨率；ffprobe 不可用时返回 (0, 0)。"""
    probe = ffprobe_path()
    if not probe or not path.exists():
        return 0, 0
    proc = await asyncio.create_subprocess_exec(
        probe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        data = json.loads((out or b"{}").decode("utf-8", "replace"))
        stream = (data.get("streams") or [{}])[0]
        return int(stream.get("width") or 0), int(stream.get("height") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0, 0


def write_srt(timeline: list[dict], path: Path) -> None:
    def fmt(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = []
    for i, item in enumerate(timeline, start=1):
        text = (item.get("subtitle") or "").strip()
        if not text:
            continue
        # 时间轴必须写成 “start --> end” 一行；拆成两行 libass 直接判定文件无效
        blocks.append(f"{i}\n{fmt(item['start'])} --> {fmt(item['end'])}\n{text}\n")
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
    filt = f"subtitles={srt.name}:force_style='{','.join(style)}'"
    cmd = [
        ff, "-y", "-loglevel", "error", "-i", str(video),
        "-vf", filt, "-c:v", "libx264", "-crf", _cfg("crf", "20"), "-preset", "veryfast",
        "-c:a", "copy", "-movflags", "+faststart", str(out),
    ]
    code, err = await _run(cmd, cwd=srt.parent)
    if code != 0:
        raise RuntimeError(f"字幕烧录失败：{_tail(err)}")


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
