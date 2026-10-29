"""任务执行器：上传素材 → 注入参数 → 提交 ComfyUI → 轮询 → 落盘产物。"""
from __future__ import annotations

import asyncio
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

from . import store
from .comfy import ComfyClient, ComfyError, make_client
from .config import settings
from .presets import (adapt_workflow_models, apply_bindings, build_bindings,
                      drop_bindings, get_card, load_workflow, optional_drops,
                      sanitize_load_images)

OUTPUT_KEYS = ("images", "gifs", "videos", "audio", "files", "video")


class JobRunner:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._cancel: set[str] = set()
        self._running: dict[str, str] = {}  # job_id -> comfy prompt_id
        self._blank_cache: dict[str, str] = {}

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

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    async def cancel(self, job_id: str) -> None:
        self._cancel.add(job_id)
        pid = self._running.get(job_id)
        if pid:
            try:
                await make_client().interrupt()
            except Exception:
                pass
        job = store.get_job(job_id)
        if job and job["status"] in {"queued", "uploading", "running"}:
            store.update_job(job_id, status="canceled", message="已取消", finished_at=time.time())

    async def _loop(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self._run_one(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 兜底，避免整个 worker 死掉
                store.update_job(job_id, status="failed", error=str(exc), message="失败", finished_at=time.time())
            finally:
                self.queue.task_done()

    async def _run_one(self, job_id: str) -> None:
        job = store.get_job(job_id)
        if not job or job["status"] == "canceled":
            return
        client = make_client()
        card = get_card(job["preset_id"])
        if not card:
            store.update_job(job_id, status="failed", error=f"能力卡不存在：{job['preset_id']}", finished_at=time.time())
            return

        store.update_job(job_id, status="uploading", message="上传素材", started_at=time.time())
        values: dict[str, Any] = job.get("inputs") or {}

        # 1) 媒体槽位：asset_id -> 本地文件 -> ComfyUI input
        media: dict[str, str] = {}
        for field in card.get("fields", []):
            if field.get("type") not in {"image", "video", "audio"}:
                continue
            key = field.get("key") or ""
            value = values.get(key)
            if not value:
                if field.get("required"):
                    raise ComfyError(f"{field.get('label', key)} 必填")
                placeholder = (card.get("placeholders") or {}).get(field.get("type") or "image")
                if placeholder:
                    name = await self._blank_name(client, field.get("type") or "image", placeholder)
                    if name:
                        media[key] = name
                continue
            asset = store.get_asset(str(value))
            if asset:
                media[key] = await self._upload_path(client, Path(settings.paths["data"]) / asset["path"], asset)
            elif str(value).startswith("comfy:"):
                media[key] = str(value).split(":", 1)[1]
            else:
                raise ComfyError(f"素材不存在：{value}")

        if job_id in self._cancel:
            return

        # 2) 参数注入（模型路径按当前 ComfyUI 实际清单自适应）
        binds = build_bindings(card, values, media)
        workflow = apply_bindings(load_workflow(card["workflow"]), binds)
        # 可选素材槽没传时摘掉对应输入（多图编辑的 image_2 / image_3）
        drops = optional_drops(card, media)
        if drops:
            workflow = drop_bindings(workflow, drops)
        try:
            object_info = await client.object_info()
            workflow, changes = adapt_workflow_models(workflow, object_info)
            image_fallbacks = [v for v in media.values()
                               if isinstance(v, str) and v.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))]
            changes += sanitize_load_images(workflow, object_info, image_fallbacks)
            if changes:
                note = "；".join(f"{c['good']} -> {c['actual']}" for c in changes[:3])
                store.update_job(job_id, message=f"已按本机模型路径调整：{note}")
        except Exception:
            pass

        # 3) 提交
        store.update_job(job_id, status="running", message="已提交，等待出片", progress=0.05)
        prompt_id = await client.submit(workflow)
        self._running[job_id] = prompt_id
        store.update_job(job_id, comfy_prompt_id=prompt_id)

        # 4) 轮询（期间更新“已等待秒数”）
        started = time.time()
        poll = asyncio.create_task(client.wait_history(prompt_id, timeout=float(card.get("timeout", 3600))))
        while not poll.done():
            if job_id in self._cancel:
                poll.cancel()
                return
            await asyncio.sleep(2)
            elapsed = int(time.time() - started)
            store.update_job(job_id, message=f"生成中… {elapsed}s", progress=min(0.9, 0.05 + elapsed / 600))
        entry = await poll

        # 5) 收产物
        store.update_job(job_id, message="下载产物", progress=0.95)
        outputs = await self._collect_outputs(client, job_id, entry)
        store.update_job(
            job_id, status="succeeded", progress=1.0, message="完成",
            outputs=outputs, finished_at=time.time(),
        )
        self._running.pop(job_id, None)

        # 把第一张图回填成镜头封面
        if job.get("shot_id") and outputs:
            first = outputs[0]
            if first.get("kind") == "image":
                store.update_shot(job["shot_id"], cover=first["url"])
            await self._attach_last_frame(job, outputs)

    async def _attach_last_frame(self, job: dict, outputs: list[dict]) -> None:
        """镜头生成成功后，把末帧存成素材，供下一镜当首帧用。"""
        shot_id = job.get("shot_id")
        target = next((o for o in outputs if o.get("kind") in {"video", "image"}), None)
        if not shot_id or not target:
            return
        url = target.get("url", "")
        if url.startswith("/media/outputs/"):
            src = Path(settings.paths["outputs"]) / url.removeprefix("/media/outputs/")
        elif url.startswith("/media/uploads/"):
            src = Path(settings.paths["uploads"]) / url.removeprefix("/media/uploads/")
        else:
            return
        if not src.exists():
            return
        from .frames import copy_as_frame, extract_last_frame

        thumbs = Path(settings.paths["data"]) / "thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)
        out = thumbs / f"{job['id']}_last.png"
        if target["kind"] == "image":
            ok, note = copy_as_frame(src, out)
        else:
            ok, note = extract_last_frame(src, out)
        if not out.exists():
            return
        rel = out.relative_to(Path(settings.paths["data"])).as_posix()
        asset = store.add_asset("image", rel, size=out.stat().st_size, meta={
            "from_job": job["id"], "from_shot": shot_id, "note": note,
        })
        store.update_shot(shot_id, last_frame=asset["id"])

    async def _blank_name(self, client: ComfyClient, ftype: str, filename: str) -> str:
        """空白占位文件按进程缓存，避免每个任务重复上传。"""
        if ftype in self._blank_cache:
            return self._blank_cache[ftype]
        path = Path(settings.paths["content"]) / "blank" / filename
        if not path.exists():
            return ""
        name = await self._upload_path(client, path)
        self._blank_cache[ftype] = name
        return name

    async def _upload_path(self, client: ComfyClient, path: Path, asset: dict | None = None) -> str:
        if not path.exists():
            raise ComfyError(f"文件不存在：{path}")
        data = path.read_bytes()
        result = await client.upload(path.name, data)
        name = result.get("name", path.name)
        if asset is not None:
            store.add_asset(
                asset["kind"], asset["path"], comfy_name=name, size=asset.get("size") or len(data),
                width=asset.get("width") or 0, height=asset.get("height") or 0,
            )
        return name

    async def _collect_outputs(self, client: ComfyClient, job_id: str, entry: dict) -> list[dict]:
        out_dir = Path(settings.paths["outputs"]) / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict] = []
        for node_id, payload in (entry.get("outputs") or {}).items():
            if not isinstance(payload, dict):
                continue
            # 纯文本输出（ShowText / PreviewAny 之类）
            for key in ("text", "string"):
                for item in payload.get(key, []) or []:
                    if isinstance(item, str) and item.strip():
                        results.append({
                            "kind": "text",
                            "name": "提示词",
                            "text": item,
                            "node": node_id,
                            "url": "",
                        })
            for key in OUTPUT_KEYS:
                for item in payload.get(key, []) or []:
                    if not isinstance(item, dict):
                        continue
                    filename = item.get("filename")
                    if not filename:
                        continue
                    try:
                        blob = await client.download(
                            filename, item.get("subfolder", ""), item.get("type", "output")
                        )
                    except Exception as exc:
                        results.append({"kind": "error", "name": filename, "error": str(exc)})
                        continue
                    target = out_dir / os.path.basename(filename)
                    target.write_bytes(blob)
                    kind = _kind_of(filename)
                    rel = target.relative_to(Path(settings.paths["outputs"])).as_posix()
                    item = {
                        "kind": kind,
                        "name": filename,
                        "url": f"/media/outputs/{rel}",
                        "node": node_id,
                        "size": len(blob),
                    }
                    # 图片/视频/音频产物都进素材库，方便资产面板与项目复用
                    if kind in {"image", "video", "audio"}:
                        data_rel = target.relative_to(Path(settings.paths["data"])).as_posix()
                        width, height = _image_size(target) if kind == "image" else (0, 0)
                        asset = store.add_asset(
                            kind, data_rel, size=len(blob), width=width, height=height,
                            meta={"from_job": job_id, "node": node_id},
                        )
                        item["asset_id"] = asset["id"]
                    results.append(item)
        return results


def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:
        return 0, 0


def _kind_of(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        if mime.startswith("image"):
            return "image"
        if mime.startswith("video"):
            return "video"
        if mime.startswith("audio"):
            return "audio"
    return "file"


runner = JobRunner()
