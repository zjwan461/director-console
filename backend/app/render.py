"""成片导出：把选中的镜头按顺序标准化 → 拼接 → 抽封面。"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from . import ffmpeg, store
from .config import settings

DATA = Path(settings.paths["data"])
RENDERS = DATA / "renders"


class RenderCanceled(Exception):
    pass


class RenderRunner:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self.cancelled: set[str] = set()

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    async def enqueue(self, render_id: str) -> None:
        await self.queue.put(render_id)

    def cancel(self, render_id: str) -> None:
        self.cancelled.add(render_id)

    def _check(self, render_id: str) -> None:
        if render_id in self.cancelled:
            raise RenderCanceled()

    async def _loop(self) -> None:
        while True:
            rid = await self.queue.get()
            try:
                if rid in self.cancelled:
                    self.cancelled.discard(rid)
                    store.update_render(rid, status="canceled", message="已取消", finished_at=time.time())
                    continue
                await self._run_one(rid)
            except asyncio.CancelledError:
                raise
            except RenderCanceled:
                self.cancelled.discard(rid)
                store.update_render(rid, status="canceled", message="已取消", finished_at=time.time())
            except Exception as exc:  # 兜底，别让 worker 挂掉
                store.update_render(
                    rid, status="failed", error=str(exc), message="失败",
                    finished_at=time.time(),
                )
            finally:
                self.queue.task_done()

    def _video_path_for_shot(self, shot_id: str) -> Path | None:
        shot = store.get_shot(shot_id) or {}
        active = str(shot.get("active_job") or "")
        jobs = store.list_jobs_by_shot(shot_id, limit=20)
        if active:
            jobs = [j for j in jobs if j.get("id") == active] + [j for j in jobs if j.get("id") != active]
        for job in jobs:
            if job.get("status") != "succeeded":
                continue
            for item in job.get("outputs") or []:
                if isinstance(item, dict) and item.get("kind") == "video" and item.get("url"):
                    url = item["url"]
                    if url.startswith("/media/outputs/"):
                        p = Path(settings.paths["outputs"]) / url.removeprefix("/media/outputs/")
                    elif url.startswith("/media/files/"):
                        p = DATA / url.removeprefix("/media/files/")
                    else:
                        continue
                    if p.exists():
                        return p
        return None

    async def _run_one(self, render_id: str) -> None:
        render = store.get_render(render_id)
        if not render:
            return
        project = store.get_project(render["project_id"])
        if not project:
            raise RuntimeError("项目不存在")

        shot_ids = render.get("shot_ids") or []
        options = render.get("options") or {}
        width = int(options.get("width") or 1280)
        height = int(options.get("height") or 720)
        fps = int(options.get("fps") or 24)
        cover_at = float(options.get("cover_at") or 1.0)
        bgm_opt = options.get("bgm") or {}
        sub_opt = options.get("subtitles") or {}
        loud_opt = options.get("loudness") or {}
        preview = bool(options.get("preview"))
        global_fit = str(options.get("fit") or "letterbox")
        title_opt = options.get("title") or {}
        tail_opt = options.get("tail") or {}
        title_text = str(title_opt.get("text") or "").strip() if title_opt.get("enabled") else ""
        tail_text = str(tail_opt.get("text") or "").strip() if tail_opt.get("enabled") else ""
        title_dur = float(title_opt.get("duration") or 1.5) if title_text else 0.0
        tail_dur = float(tail_opt.get("duration") or 2.0) if tail_text else 0.0
        trans = options.get("transition") or {}
        trans_kind = str(trans.get("type") or "none")
        trans_dur = float(trans.get("duration") or 0.4)
        if preview:
            # 480p 快速草稿
            ratio = (width / height) if height else 16 / 9
            width = 854
            height = max(2, int(round(854 / ratio)) // 2 * 2)

        store.update_render(render_id, status="preparing", message="检查素材", progress=0.02,
                            started_at=time.time())

        shots = {s["id"]: s for s in store.list_shots(project["id"])}
        ordered = [shots[sid] for sid in shot_ids if sid in shots]
        if not ordered:
            raise RuntimeError("没有选中的镜头")

        missing = [f"{s['title'] or '未命名镜头'}（{s['id']}）" for s in ordered
                   if not self._video_path_for_shot(s["id"])]
        if missing:
            raise RuntimeError("这些镜头还没有可用的视频产物：" + "、".join(missing))

        caps = ffmpeg.capabilities()
        if not caps.get("available"):
            raise RuntimeError("未检测到 ffmpeg，无法合成。安装后加入 PATH，或在 config.yaml 设置 ffmpeg.path")

        edits = {row["shot_id"]: row for row in store.list_render_shots(render_id)}
        work = RENDERS / render_id
        work.mkdir(parents=True, exist_ok=True)
        final = work / "final.mp4"
        cover = work / "cover.jpg"

        total = len(ordered)
        clips: list[Path] = []
        voice_segments: list[tuple[Path | None, float]] = []
        timeline: list[dict] = []
        cursor = title_dur

        for idx, shot in enumerate(ordered, start=1):
            self._check(render_id)
            src = self._video_path_for_shot(shot["id"])
            assert src is not None
            edit = edits.get(shot["id"]) or {}
            dst = work / f"clip_{idx:03d}.mp4"
            store.update_render(
                render_id,
                message=f"{idx-1}/{total} 段处理：{shot['title'] or shot['id']}",
                progress=0.05 + 0.55 * (idx - 1) / total,
            )
            shot_fit = str(edit.get("fit") or "") or global_fit
            await ffmpeg.process_clip(
                src, dst, width, height, fps,
                in_point=float(edit.get("in_point") or 0),
                out_point=float(edit["out_point"]) if edit.get("out_point") else None,
                volume_db=float(edit.get("volume_db") or 0),
                muted=bool(edit.get("muted")),
                fit=shot_fit,
            )
            dur = await ffmpeg.duration_of(dst)

            voice_path = None
            voice_id = str(edit.get("voice_asset") or "")
            if voice_id:
                voice_asset = store.get_asset(voice_id)
                if voice_asset:
                    candidate = DATA / voice_asset["path"]
                    if candidate.exists():
                        voice_path = candidate
                        voiced = work / f"clipv_{idx:03d}.mp4"
                        store.update_render(render_id, message=f"{idx}/{total} 混入旁白", progress=0.05 + 0.55 * idx / total)
                        # 旁白比镜头长时，按建议值提速压进镜头（最多 1.3x）
                        try:
                            voice_dur = await ffmpeg.duration_of(candidate)
                        except Exception:
                            voice_dur = 0.0
                        tempo = 1.0
                        if voice_dur and dur > 0.5:
                            tempo = min(max(voice_dur / max(dur - 0.3, 0.5), 1.0), 1.3)
                        if tempo > 1.001:
                            adjusted = work / f"vo_{idx:03d}.wav"
                            await ffmpeg.speed_audio(candidate, adjusted, tempo)
                            voice_path = adjusted
                        await ffmpeg.mix_voice(dst, voice_path, voiced)
                        dst = voiced
            voice_segments.append((voice_path, dur))

            text = str(edit.get("subtitle") or "").strip() or (shot.get("title") or "")
            if edit.get("burned_subtitle"):
                text = ""  # 视频里已经烧好字幕，不再重复烧
            timeline.append({
                "shot_id": shot["id"], "title": shot.get("title") or "",
                "start": cursor, "end": cursor + dur, "duration": dur, "subtitle": text,
            })
            cursor += dur
            clips.append(dst)

        self._check(render_id)
        store.update_render(render_id, message="拼接中", progress=0.62)
        joined = work / "joined.mp4"
        if trans_kind in {"fade", "dissolve"}:
            store.update_render(render_id, message=f"拼接中（{trans_kind} {trans_dur}s）", progress=0.66)
            await ffmpeg.concat_with_transition(clips, joined, work, trans_kind, trans_dur)
        else:
            await ffmpeg.concat_clips(clips, joined, work)
        current = joined

        parts: list[Path] = []
        if title_text:
            store.update_render(render_id, message="生成片头", progress=0.68)
            bg_path = None
            if title_opt.get("bg_asset"):
                bg_asset = store.get_asset(str(title_opt["bg_asset"]))
                if bg_asset:
                    candidate = DATA / bg_asset["path"]
                    bg_path = candidate if candidate.exists() else None
            card = work / "title.mp4"
            await ffmpeg.make_title_card(
                card, title_text, title_dur, width, height, fps,
                bg_color=str(title_opt.get("bg") or "#000000"),
                bg_image=bg_path,
                bg_fit=global_fit,
            )
            parts.append(card)
        parts.append(current)
        if tail_text:
            store.update_render(render_id, message="生成片尾", progress=0.69)
            bg_path = None
            if tail_opt.get("bg_asset"):
                bg_asset = store.get_asset(str(tail_opt["bg_asset"]))
                if bg_asset:
                    candidate = DATA / bg_asset["path"]
                    bg_path = candidate if candidate.exists() else None
            card = work / "tail.mp4"
            await ffmpeg.make_title_card(
                card, tail_text, tail_dur, width, height, fps,
                bg_color=str(tail_opt.get("bg") or "#000000"),
                bg_image=bg_path,
                bg_fit=global_fit,
            )
            parts.append(card)
        if len(parts) > 1:
            with_cards = work / "with_cards.mp4"
            await ffmpeg.concat_clips(parts, with_cards, work)
            current = with_cards

        voice_full: Path | None = None
        if any(path for path, _ in voice_segments):
            voice_full = work / "narration.m4a"
            try:
                await ffmpeg.build_narration_track(voice_segments, voice_full)
            except Exception:
                voice_full = None

        self._check(render_id)
        if bgm_opt.get("asset_id"):
            bgm_asset = store.get_asset(str(bgm_opt["asset_id"]))
            bgm_path = DATA / bgm_asset["path"] if bgm_asset else None
            if bgm_path and bgm_path.exists():
                store.update_render(render_id, message="混入 BGM", progress=0.7)
                mixed = work / "mixed.mp4"
                await ffmpeg.mix_bgm(
                    current, bgm_path, mixed,
                    volume_db=float(bgm_opt.get("volume_db") or -12),
                    fade_in=float(bgm_opt.get("fade_in") or 0),
                    fade_out=float(bgm_opt.get("fade_out") or 0),
                    loop=bool(bgm_opt.get("loop", True)),
                    duck_track=voice_full if bgm_opt.get("duck", True) else None,
                    duck_db=float(bgm_opt.get("duck_db") or -14),
                )
                current = mixed

        self._check(render_id)
        srt_path = work / "subtitles.srt"
        sub_style = (sub_opt.get("style") or {})
        sub_size = int(sub_style.get("size") or 42)
        # 单行最多多少字：留 10% 边距，按字号估算
        max_chars = max(8, int(width * 0.88 / max(sub_size, 1)))
        if timeline:
            ffmpeg.write_srt(timeline, srt_path, max_chars=max_chars)

        if (sub_opt.get("enabled", True) and caps.get("subtitles")
                and srt_path.exists() and srt_path.stat().st_size > 20):
            store.update_render(render_id, message="烧录字幕", progress=0.8)
            subbed = work / "subbed.mp4"
            style = sub_opt.get("style") or {}
            await ffmpeg.burn_subtitles(
                current, srt_path, subbed,
                font=str(style.get("font") or ""),
                size=sub_size,
                color=str(style.get("color") or "#FFFFFF"),
                outline=int(style.get("outline") or 2),
                margin_v=int(style.get("margin_v") or 48),
                width=width,
                height=height,
            )
            current = subbed

        if (not preview) and loud_opt.get("enabled", True):
            store.update_render(render_id, message="响度标准化", progress=0.9)
            normalized = work / "normalized.mp4"
            try:
                await ffmpeg.loudnorm(current, normalized, float(loud_opt.get("target_lufs") or -16))
                current = normalized
            except Exception:
                pass  # 响度失败不阻断导出

        self._check(render_id)
        if current != final:
            current.replace(final)

        # 某些滤镜会输出 yuv444p，Windows 播放器不支持，兜底转回 420p
        try:
            fmt = await ffmpeg.pixel_format(final)
            if fmt and fmt != "yuv420p":
                fixed = work / "final_compat.mp4"
                await ffmpeg.transcode_compat(final, fixed)
                fixed.replace(final)
        except Exception:
            pass

        try:
            await ffmpeg.extract_cover(final, cover, cover_at)
        except Exception:
            cover = None  # 封面失败不影响成片

        out_rel = final.relative_to(DATA).as_posix()
        cover_rel = cover.relative_to(DATA).as_posix() if cover else ""
        store.update_render(
            render_id, status="succeeded", progress=1.0, message="完成",
            output_path=out_rel, cover_path=cover_rel, finished_at=time.time(),
        )
        cache_key = str(options.get("cache_key") or "")
        if preview and cache_key:
            store.set_setting("preview_cache." + cache_key, render_id)


runner = RenderRunner()
