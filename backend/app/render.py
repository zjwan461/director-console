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
        for job in store.list_jobs_by_shot(shot_id, limit=20):
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

        if not ffmpeg.status()["available"]:
            raise RuntimeError(
                "未检测到 ffmpeg，无法合成。安装后加入 PATH，或在 config.yaml 设置 ffmpeg.path"
            )

        work = RENDERS / render_id
        work.mkdir(parents=True, exist_ok=True)
        final = work / "final.mp4"
        cover = work / "cover.jpg"

        clips: list[Path] = []
        total = len(ordered)
        store.update_render(render_id, status="rendering", message=f"0/{total} 段标准化", progress=0.05)

        for idx, shot in enumerate(ordered, start=1):
            src = self._video_path_for_shot(shot["id"])
            assert src is not None
            dst = work / f"clip_{idx:03d}.mp4"
            store.update_render(
                render_id,
                message=f"{idx-1}/{total} 段标准化：{shot['title'] or shot['id']}",
                progress=0.05 + 0.85 * (idx - 1) / total,
            )
            await ffmpeg.normalize_clip(src, dst, width, height, fps)
            clips.append(dst)

        store.update_render(render_id, message="拼接中", progress=0.92)
        await ffmpeg.concat_clips(clips, final, work)

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
