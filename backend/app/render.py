"""成片导出：把选中的镜头按顺序标准化 → 拼接 → 抽封面。"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from . import ffmpeg, store
from .config import settings

DATA = Path(settings.paths["data"])
RENDERS = DATA / "renders"


class RenderRunner:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

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

    async def _loop(self) -> None:
        while True:
            rid = await self.queue.get()
            try:
                await self._run_one(rid)
            except asyncio.CancelledError:
                raise
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
        cursor = 0.0

        for idx, shot in enumerate(ordered, start=1):
            src = self._video_path_for_shot(shot["id"])
            assert src is not None
            edit = edits.get(shot["id"]) or {}
            dst = work / f"clip_{idx:03d}.mp4"
            store.update_render(
                render_id,
                message=f"{idx-1}/{total} 段处理：{shot['title'] or shot['id']}",
                progress=0.05 + 0.55 * (idx - 1) / total,
            )
            await ffmpeg.process_clip(
                src, dst, width, height, fps,
                in_point=float(edit.get("in_point") or 0),
                out_point=float(edit["out_point"]) if edit.get("out_point") else None,
                volume_db=float(edit.get("volume_db") or 0),
                muted=bool(edit.get("muted")),
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
                        await ffmpeg.mix_voice(dst, candidate, voiced)
                        dst = voiced
            voice_segments.append((voice_path, dur))

            text = str(edit.get("subtitle") or "").strip() or (shot.get("title") or "")
            timeline.append({
                "shot_id": shot["id"], "title": shot.get("title") or "",
                "start": cursor, "end": cursor + dur, "duration": dur, "subtitle": text,
            })
            cursor += dur
            clips.append(dst)

        store.update_render(render_id, message="拼接中", progress=0.62)
        joined = work / "joined.mp4"
        if trans_kind in {"fade", "dissolve"}:
            store.update_render(render_id, message=f"拼接中（{trans_kind} {trans_dur}s）", progress=0.66)
            await ffmpeg.concat_with_transition(clips, joined, work, trans_kind, trans_dur)
        else:
            await ffmpeg.concat_clips(clips, joined, work)
        current = joined

        voice_full: Path | None = None
        if any(path for path, _ in voice_segments):
            voice_full = work / "narration.m4a"
            try:
                await ffmpeg.build_narration_track(voice_segments, voice_full)
            except Exception:
                voice_full = None

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

        srt_path = work / "subtitles.srt"
        if timeline:
            ffmpeg.write_srt(timeline, srt_path)

        if (not preview) and sub_opt.get("enabled", True) and caps.get("subtitles") and srt_path.exists():
            store.update_render(render_id, message="烧录字幕", progress=0.8)
            subbed = work / "subbed.mp4"
            style = sub_opt.get("style") or {}
            await ffmpeg.burn_subtitles(
                current, srt_path, subbed,
                font=str(style.get("font") or ""),
                size=int(style.get("size") or 42),
                color=str(style.get("color") or "#FFFFFF"),
                outline=int(style.get("outline") or 2),
                margin_v=int(style.get("margin_v") or 48),
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

        if current != final:
            current.replace(final)

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


runner = RenderRunner()
