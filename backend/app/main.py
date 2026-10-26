"""导演台后端入口：FastAPI + 静态前端 + ComfyUI 代理/调度。"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from . import runtime
from . import ai_script, asr, ffmpeg, tts as tts_module
from .render import runner as render_runner
from .comfy import ComfyError, make_client, probe
from .config import settings
from .netutil import proxy_for, proxy_note
from .jobs import runner
from .launcher import LaunchError, get_launcher
from .presets import default_values, get_card, is_video_card, load_cards, public_card, validate
from .prompt_stream import router as prompt_stream_router
from .agent.api import router as agent_router
from .ai_edit_api import router as ai_edit_router
from .task_center import router as tasks_router
from .model_check import check_models
from .model_inventory import fetch_inventory, load_snapshot, save_snapshot
from .model_sources import load_sources, merge_sources, upsert_source

ROOT = Path(settings.paths["root"])
DATA = Path(settings.paths["data"])
UPLOADS = Path(settings.paths["uploads"])
OUTPUTS = Path(settings.paths["outputs"])
CONTENT = Path(settings.paths["content"])
WEB_DIST = Path(settings.paths["web_dist"])

app = FastAPI(title="ComfyUI 导演台", version="0.1.0")
app.include_router(prompt_stream_router)
app.include_router(agent_router)
app.include_router(ai_edit_router)
app.include_router(tasks_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _refresh_settings(request, call_next):
    """config.yaml 改动（比如填了 ai.api_key）无需重启即可生效。"""
    if settings.refresh_if_changed():
        runtime.apply_runtime_settings()
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


store.init_db()
runtime.apply_runtime_settings()
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)
app.mount("/media/outputs", StaticFiles(directory=str(OUTPUTS)), name="outputs")
app.mount("/media/uploads", StaticFiles(directory=str(UPLOADS)), name="uploads")
app.mount("/media/files", StaticFiles(directory=str(DATA)), name="files")


@app.on_event("startup")
async def _startup() -> None:
    store.recover_jobs()
    store.recover_renders()
    try:
        from .agent.checkpoint import ensure_graph
        from .agent.runtime import mark_stale_runs

        await mark_stale_runs()
        await ensure_graph()
    except Exception:
        pass
    runner.start()
    render_runner.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await runner.stop()
    await render_runner.stop()


# ---------------------------------------------------------------- 基础
_ERROR_LOG = DATA / "panel-error.log"


@app.middleware("http")
async def _log_unhandled(request, call_next):
    """把未捕获异常写进 data/panel-error.log，方便定位 500。"""
    try:
        return await call_next(request)
    except Exception:
        import traceback

        try:
            with _ERROR_LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {request.method} {request.url.path}\n")
                fh.write(traceback.format_exc())
        except Exception:
            pass
        raise


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "version": app.version, "time": time.time()}


# ---------------------------------------------------------------- 服务管家
class ServiceAction(BaseModel):
    free_vram: bool = False


@app.get("/api/service/status")
async def service_status() -> dict:
    launcher = get_launcher()
    status = await launcher.status()
    status["config_mode"] = settings.comfy_mode
    status["advanced_panel"] = settings.get("ui.advanced_panel", "")
    status["comfy_web"] = (
        settings.base_url if settings.comfy_mode in {"external", "mock"}
        else settings.get("ui.comfy_web", "")
    )
    status["settings"] = runtime.public_comfy_settings()

    # 本地 ComfyUI 单独探活：与"当前对话走云端"是两件事
    local_url = str(settings.get("comfy.local_url", "http://127.0.0.1:8188")).rstrip("/")
    local_health = await probe(local_url, "", timeout=2.5)
    status["local"] = {
        "url": local_url,
        "running": bool(local_health.get("ok")),
        "health": local_health,
    }
    return status


# ---------------------------------------------------------------- 连接设置
class ComfySettings(BaseModel):
    mode: str = "external"
    base_url: str = ""
    token: str | None = None


class ComfyProbe(BaseModel):
    base_url: str = ""
    token: str | None = None


@app.get("/api/settings/comfy")
async def get_comfy_settings() -> dict:
    return runtime.public_comfy_settings()


@app.put("/api/settings/comfy")
async def put_comfy_settings(body: ComfySettings) -> dict:
    try:
        return runtime.save_comfy_settings(body.mode, body.base_url, body.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/settings/comfy")
async def delete_comfy_settings() -> dict:
    return runtime.reset_comfy_settings()


@app.post("/api/settings/comfy/test")
async def test_comfy_settings(body: ComfyProbe) -> dict:
    url = runtime.normalize_url(body.base_url)
    if not url:
        raise HTTPException(status_code=400, detail="请填写 ComfyUI 地址")
    token = body.token if body.token is not None else str(settings.get("comfy.token", "") or "")
    result = await probe(url, token)
    result["base_url"] = url
    return result


@app.post("/api/service/start")
async def service_start() -> dict:
    try:
        return await get_launcher().start()
    except LaunchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/service/stop")
async def service_stop(body: ServiceAction | None = None) -> dict:
    try:
        return await get_launcher().stop()
    except LaunchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/service/restart")
async def service_restart() -> dict:
    launcher = get_launcher()
    try:
        await launcher.stop()
    except LaunchError:
        pass
    await asyncio.sleep(1)
    try:
        return await launcher.start()
    except LaunchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/service/free")
async def service_free() -> dict:
    client = make_client()
    try:
        await client.free()
        return {"ok": True, "message": "已请求 ComfyUI 释放显存"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/service/logs")
async def service_logs(lines: int = Query(200, ge=10, le=2000)) -> dict:
    text = await get_launcher().logs(lines)
    return {"lines": lines, "text": text}


@app.get("/api/service/comfy")
async def service_comfy() -> dict:
    return await make_client().health()


# ---------------------------------------------------------------- 能力卡
@app.get("/api/presets")
async def presets() -> dict:
    cards = [public_card(c) for c in load_cards()]
    return {"items": cards, "count": len(cards)}


@app.get("/api/models/inventory")
async def models_inventory() -> dict:
    try:
        return await fetch_inventory()
    except ComfyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/models/inventory/snapshot")
async def models_inventory_snapshot() -> dict:
    try:
        inventory = await fetch_inventory()
    except ComfyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    save_snapshot(inventory)
    return {"ok": True, "inventory": inventory}


@app.get("/api/models/inventory/snapshot")
async def models_inventory_snapshot_get() -> dict:
    snapshot = load_snapshot()
    if not snapshot:
        raise HTTPException(status_code=404, detail="还没有保存过模型清单快照")
    return snapshot


@app.get("/api/models/sources")
async def models_sources() -> dict:
    sources = load_sources()
    items = list(sources.values())
    return {"count": len(items), "items": items[:20]}


class SourceEdit(BaseModel):
    name: str
    url: str = ""
    directory: str = ""


@app.put("/api/models/sources")
async def models_sources_put(body: SourceEdit) -> dict:
    if body.url and not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="链接需要以 http:// 或 https:// 开头")
    stats = upsert_source(body.name.strip(), body.url.strip(), body.directory)
    return {"ok": True, **stats}


@app.post("/api/models/sources/import")
async def models_sources_import(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON") from exc
    if isinstance(data, list):
        workflows = data
    elif isinstance(data, dict) and isinstance(data.get("workflows"), list):
        workflows = data["workflows"]
    elif isinstance(data, dict) and "nodes" in data:
        workflows = [data]
    else:
        raise HTTPException(status_code=400, detail="请传 UI workflow JSON、数组或 {workflows:[...]}")
    stats = merge_sources([w for w in workflows if isinstance(w, dict)])
    return {"ok": True, **stats}


@app.post("/api/models/sources/sync")
async def models_sources_sync() -> dict:
    client = make_client()
    try:
        entries = await client.userdata_list("workflows")
    except ComfyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    names = []
    for entry in entries:
        name = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(name, str) and name.lower().endswith(".json"):
            names.append(name)

    sem = asyncio.Semaphore(8)

    async def fetch(name: str):
        async with sem:
            try:
                return json.loads(await client.userdata_get(name))
            except Exception:
                return None

    workflows = [w for w in await asyncio.gather(*[fetch(n) for n in names]) if isinstance(w, dict)]
    used = len(workflows)
    stats = merge_sources(workflows)
    return {"ok": True, "files": used, **stats}


@app.get("/api/models/check")
async def models_check(card_id: str | None = None, source: str = "live") -> dict:
    try:
        return await check_models(card_id, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ComfyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/presets/{card_id}")
async def preset_detail(card_id: str) -> dict:
    card = get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="能力卡不存在")
    return {"card": public_card(card), "defaults": default_values(card)}


# ---------------------------------------------------------------- 素材
def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image  # 可选依赖
        with Image.open(path) as im:
            return im.size
    except Exception:
        return 0, 0


@app.post("/api/assets/upload")
async def upload_asset(file: UploadFile = File(...), kind: str = Form("image"),
                       purpose: str = Form("")) -> dict:
    suffix = Path(file.filename or "upload").suffix.lower() or ".bin"
    name = f"{uuid.uuid4().hex}{suffix}"
    target = UPLOADS / name
    size = 0
    with target.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            fh.write(chunk)
    width, height = _image_size(target) if kind == "image" else (0, 0)
    rel = target.relative_to(DATA).as_posix()
    meta: dict = {"origin_name": file.filename}
    if purpose:
        meta["purpose"] = purpose
    asset = store.add_asset(kind, rel, size=size, width=width, height=height, meta=meta)
    asset["url"] = f"/media/files/{rel}"
    return asset


@app.post("/api/assets/cleanup-duplicates")
async def cleanup_duplicate_assets() -> dict:
    """同一文件被登记成多条 asset 时，保留最早一条。"""
    mapping: dict[str, str] = {}
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT id, path, created_at FROM assets ORDER BY path, created_at, id"
        ).fetchall()
        keep_by_path: dict[str, str] = {}
        for asset_id, path, _ in rows:
            if path in keep_by_path:
                mapping[asset_id] = keep_by_path[path]
            else:
                keep_by_path[path] = asset_id
        for old_id, new_id in mapping.items():
            conn.execute("UPDATE shots SET last_frame=? WHERE last_frame=?", (new_id, old_id))
            conn.execute("UPDATE shots SET active_job=active_job WHERE 1=0")
            conn.execute("UPDATE render_shots SET voice_asset=? WHERE voice_asset=?", (new_id, old_id))
            conn.execute("DELETE FROM assets WHERE id=?", (old_id,))
    # edit_state 里存的是 JSON 字符串，直接做 id 文本替换
    if mapping:
        with store.connect() as conn:
            for row in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'edit_state.%'").fetchall():
                key, value = row[0], row[1]
                changed = value
                for old_id, new_id in mapping.items():
                    changed = changed.replace(old_id, new_id)
                if changed != value:
                    conn.execute("UPDATE settings SET value=? WHERE key=?", (changed, key))
    return {"ok": True, "removed": len(mapping), "repointed": len(mapping)}


def _asset_purpose(asset: dict) -> str:
    """素材用途：narration=旁白配音，music=背景音乐，空=未分类。

    老数据没有 purpose 字段，按路径推断：tts/ → 配音，music/ → 音乐。
    """
    meta = asset.get("meta") or {}
    purpose = str(meta.get("purpose") or "").strip()
    if purpose:
        return purpose
    path = str(asset.get("path") or "")
    if "/tts/" in path or meta.get("origin") == "tts":
        return "narration"
    if "/music/" in path or meta.get("license"):
        return "music"
    return ""


@app.get("/api/assets/{asset_id}")
async def asset_detail(asset_id: str) -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    asset["url"] = f"/media/files/{asset['path']}"
    return asset


@app.get("/api/assets/{asset_id}/duration")
async def asset_duration(asset_id: str) -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    target = DATA / asset["path"]
    if not target.exists():
        return {"duration": 0.0}
    cached = (asset.get("meta") or {}).get("duration")
    if cached:
        return {"duration": float(cached)}
    try:
        return {"duration": round(await ffmpeg.duration_of(target), 2)}
    except Exception:
        return {"duration": 0.0}


class AssetMetaPatch(BaseModel):
    mood: str | None = None
    tags: list[str] | None = None


@app.patch("/api/assets/{asset_id}/meta")
async def patch_asset_meta(asset_id: str, body: AssetMetaPatch) -> dict:
    """给素材补标签（音乐情绪等）。"""
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    meta = dict(asset.get("meta") or {})
    if body.mood is not None:
        meta["mood"] = body.mood.strip()
    if body.tags is not None:
        meta["tags"] = [str(t).strip() for t in body.tags if str(t).strip()][:8]
    store.update_asset_meta(asset_id, meta)
    asset = store.get_asset(asset_id) or asset
    asset["url"] = f"/media/files/{asset['path']}"
    asset["purpose"] = _asset_purpose(asset)
    return asset


@app.get("/api/assets/{asset_id}/waveform")
async def asset_waveform(asset_id: str, buckets: int = Query(160, ge=16, le=600)) -> dict:
    """音频波形峰值，供时间轴画波形条。结果按文件大小+修改时间缓存。"""
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    target = DATA / asset["path"]
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    stat = target.stat()
    key = f"waveform.{asset_id}.{buckets}"
    cached = store.get_setting(key) or ""
    if cached:
        try:
            payload = json.loads(cached)
            if payload.get("size") == stat.st_size and payload.get("mtime") == int(stat.st_mtime):
                return {"peaks": payload["peaks"], "cached": True}
        except Exception:
            pass
    peaks = await ffmpeg.waveform(target, buckets)
    store.set_setting(key, json.dumps({
        "size": stat.st_size, "mtime": int(stat.st_mtime), "peaks": peaks,
    }))
    return {"peaks": peaks, "cached": False}


@app.get("/api/assets")
async def assets(
    kind: str | None = None,
    q: str = "",
    purpose: str | None = None,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    items, total = store.search_assets(kind, q, limit, offset, purpose)
    for item in items:
        item["url"] = f"/media/files/{item['path']}"
        item["purpose"] = _asset_purpose(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.post("/api/assets/repair-paths")
async def repair_asset_paths() -> dict:
    """把历史遗留的绝对/错误素材路径修回相对路径，修不了就删记录。"""
    fixed, removed = 0, 0
    for asset in store.list_assets(None, 5000):
        path = str(asset.get("path") or "")
        if not path.startswith(("/", "\\")):
            continue
        rel = ""
        for prefix, root in (("/media/files/", ""), ("/media/outputs/", "outputs/"),
                             ("/media/uploads/", "uploads/")):
            if path.startswith(prefix):
                rel = root + path[len(prefix):]
                break
        if rel and (DATA / rel).exists():
            with store.connect() as conn:
                conn.execute("UPDATE assets SET path=? WHERE id=?", (rel, asset["id"]))
            fixed += 1
        else:
            with store.connect() as conn:
                conn.execute("DELETE FROM assets WHERE id=?", (asset["id"],))
            removed += 1
    return {"ok": True, "fixed": fixed, "removed": removed}


@app.get("/api/assets/{asset_id}/poster")
async def asset_poster(asset_id: str):
    """视频首帧封面：首次访问时用 ffmpeg 抽帧并缓存。"""
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset["kind"] != "video":
        raise HTTPException(status_code=404, detail="只有视频有封面")

    cached = DATA / "thumbs" / f"poster_{asset_id}.jpg"
    if not cached.exists():
        src = DATA / asset["path"]
        if not src.exists():
            raise HTTPException(status_code=404, detail="源文件不存在")
        cached.parent.mkdir(parents=True, exist_ok=True)
        try:
            from .ffmpeg import extract_cover

            await extract_cover(src, cached, at=0.3)
        except Exception:
            if not cached.exists():
                raise HTTPException(status_code=404, detail="封面生成失败")
    if not cached.exists():
        raise HTTPException(status_code=404, detail="封面生成失败")
    return FileResponse(
        cached,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/assets/{asset_id}/usage")
async def asset_usage(asset_id: str) -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    shots = []
    for project in store.list_projects():
        for shot in store.list_shots(project["id"]):
            values = shot.get("values") or {}
            fields = [k for k, v in values.items() if v == asset_id]
            if fields:
                shots.append({
                    "project_id": project["id"],
                    "project_name": project["name"],
                    "shot_id": shot["id"],
                    "shot_title": shot.get("title") or f"镜头 {shot.get('idx', 0) + 1}",
                    "fields": fields,
                })
    jobs = []
    recent_jobs, _, _ = store.list_jobs(200)
    asset_path = asset.get("path") or ""
    for job in recent_jobs:
        hit = False
        for o in job.get("outputs") or []:
            if not isinstance(o, dict):
                continue
            if o.get("asset_id") == asset_id:
                hit = True
                break
            url = o.get("url") or ""
            if url.startswith("/media/outputs/") and "outputs/" + url.removeprefix("/media/outputs/") == asset_path:
                hit = True
                break
        if hit:
            jobs.append({
                "id": job["id"],
                "preset_id": job["preset_id"],
                "status": job["status"],
                "created_at": job["created_at"],
            })
    asset["url"] = f"/media/files/{asset['path']}"
    return {"asset": asset, "shots": shots, "jobs": jobs}


class AssetShotCreate(BaseModel):
    project_id: str
    title: str = ""
    mode: str = "restore"          # restore | first_frame | audio
    preset_id: str = ""


def _source_job_for_asset(asset: dict) -> dict | None:
    jobs, _, _ = store.list_jobs(500)
    target = asset.get("path") or ""
    for job in jobs:
        if job.get("status") != "succeeded":
            continue
        for out in job.get("outputs") or []:
            if not isinstance(out, dict):
                continue
            if out.get("asset_id") == asset["id"]:
                return job
            url = out.get("url") or ""
            if url.startswith("/media/outputs/") and "outputs/" + url.removeprefix("/media/outputs/") == target:
                return job
    return None


@app.post("/api/assets/{asset_id}/create-shot")
async def asset_create_shot(asset_id: str, body: AssetShotCreate) -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    project = store.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    preset_id = ""
    values: dict[str, Any] = {}
    title = body.title.strip()

    if body.mode == "restore":
        job = _source_job_for_asset(asset)
        if not job:
            raise HTTPException(status_code=400, detail="这个素材没有可追溯的生成任务，请改用「用作首帧/参考」")
        restore_card = get_card(job.get("preset_id") or "")
        if restore_card and not is_video_card(restore_card):
            raise HTTPException(status_code=400,
                                detail="这张图是图片卡生成的，不能还原成镜头；请用「用作首帧」配视频卡")
        preset_id = job["preset_id"]
        values = dict(job.get("inputs") or {})
        title = title or f"还原 · {asset['path'].rsplit('/', 1)[-1]}"
    elif body.mode == "first_frame":
        preset_id = body.preset_id or "h3.i2v"
        card = get_card(preset_id)
        if not card:
            raise HTTPException(status_code=400, detail="能力卡不存在")
        values = default_values(card)
        values["first_frame"] = asset["id"]
        title = title or "图片首帧镜头"
    elif body.mode == "audio":
        preset_id = body.preset_id or "h3.r2v9"
        card = get_card(preset_id)
        if not card:
            raise HTTPException(status_code=400, detail="能力卡不存在")
        values = default_values(card)
        values["audio_1"] = asset["id"]
        title = title or "音频参考镜头"
    else:
        raise HTTPException(status_code=400, detail="未知模式")

    shot = store.create_shot(project["id"], title, preset_id)
    store.update_shot(shot["id"], values=values)

    # 还原为镜头时补一条「已成功」的任务记录，把源资产挂上去：
    # 这样「本镜历史」「成片导出」都能找到这条视频，而不是空镜头
    if body.mode == "restore":
        placeholder = store.create_job(preset_id, values, project_id=project["id"], shot_id=shot["id"])
        store.update_job(
            placeholder["id"],
            status="succeeded",
            progress=1.0,
            message="来自资产",
            outputs=[{
                "kind": asset["kind"],
                "name": asset["path"].rsplit("/", 1)[-1],
                "url": f"/media/files/{asset['path']}",
                "asset_id": asset["id"],
                "size": asset.get("size", 0),
            }],
            started_at=time.time(),
            finished_at=time.time(),
        )

    # 图片直接当末帧；视频抽一帧当末帧，方便下一镜接首帧
    if asset["kind"] == "image":
        store.update_shot(shot["id"], last_frame=asset["id"], cover=f"/media/files/{asset['path']}")
    elif asset["kind"] == "video":
        src = DATA / asset["path"]
        if src.exists():
            from .frames import extract_last_frame

            thumbs = DATA / "thumbs"
            thumbs.mkdir(parents=True, exist_ok=True)
            out = thumbs / f"asset_{asset['id']}_last.png"
            ok, note = extract_last_frame(src, out)
            if out.exists():
                rel = out.relative_to(DATA).as_posix()
                frame = store.add_asset("image", rel, size=out.stat().st_size,
                                        meta={"from_asset": asset["id"], "note": note})
                store.update_shot(shot["id"], last_frame=frame["id"])
        store.update_shot(shot["id"], cover=f"/media/files/{asset['path']}")

    return _enrich_shot(store.get_shot(shot["id"]) or shot)


@app.post("/api/assets/cleanup-test")
async def assets_cleanup_test() -> dict:
    """清理早期 mock/stub 测试产物（极小文件）。"""
    assets = store.list_assets(None, 2000)
    removed = 0
    for asset in assets:
        name = asset["path"].rsplit("/", 1)[-1].lower()
        if not (name.startswith(("mock_output", "stub_output", "stub_image")) or asset.get("size", 0) <= 64):
            continue
        try:
            (DATA / asset["path"]).unlink(missing_ok=True)
        except Exception:
            pass
        with store.connect() as conn:
            conn.execute("DELETE FROM assets WHERE id=?", (asset["id"],))
        removed += 1
    return {"ok": True, "removed": removed}


@app.post("/api/assets/backfill")
async def assets_backfill() -> dict:
    """把历史任务产物补登记为素材（旧版本只登记图片）。"""
    created = 0
    recent_jobs, _, _ = store.list_jobs(500)
    for job in recent_jobs:
        for out in job.get("outputs") or []:
            if not isinstance(out, dict):
                continue
            url = out.get("url") or ""
            kind = out.get("kind")
            if kind not in {"image", "video", "audio"} or not url.startswith("/media/outputs/"):
                continue
            rel = "outputs/" + url.removeprefix("/media/outputs/")
            if store.find_asset_by_path(rel):
                continue
            path = DATA / rel
            size = out.get("size") or (path.stat().st_size if path.exists() else 0)
            width, height = _image_size(path) if kind == "image" else (0, 0)
            store.add_asset(kind, rel, size=size, width=width, height=height,
                            meta={"from_job": job["id"], "node": out.get("node")})
            created += 1
    return {"ok": True, "created": created}


@app.delete("/api/assets/{asset_id}")
async def delete_asset(asset_id: str) -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        (DATA / asset["path"]).unlink(missing_ok=True)
    except Exception:
        pass
    with store.connect() as conn:
        conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    return {"ok": True}


# ---------------------------------------------------------------- 任务
class JobCreate(BaseModel):
    preset_id: str
    inputs: dict[str, Any] = {}
    project_id: str = ""
    shot_id: str = ""


@app.post("/api/jobs")
async def create_job(body: JobCreate) -> dict:
    card = get_card(body.preset_id)
    if not card:
        raise HTTPException(status_code=404, detail="能力卡不存在")
    if card.get("error"):
        raise HTTPException(status_code=400, detail=card["error"])
    errors = validate(card, body.inputs)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))
    job = store.create_job(body.preset_id, body.inputs, body.project_id, body.shot_id)
    await runner.enqueue(job["id"])
    return job


@app.get("/api/jobs")
async def jobs(
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
    cursor: str | None = None,
) -> dict:
    items, has_more, next_cursor = store.list_jobs(limit, status, cursor)
    return {"items": items, "has_more": has_more, "next_cursor": next_cursor}


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    await runner.cancel(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    new = store.create_job(job["preset_id"], job.get("inputs") or {}, job.get("project_id") or "", job.get("shot_id") or "")
    await runner.enqueue(new["id"])
    return new


class JobSaveAsShot(BaseModel):
    project_id: str
    title: str = ""


@app.post("/api/jobs/{job_id}/save-as-shot")
async def save_job_as_shot(job_id: str, body: JobSaveAsShot) -> dict:
    """把创作台的一次生成结果落成镜头，并把任务归属回填。"""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("shot_id"):
        raise HTTPException(status_code=400, detail="这个任务已经属于某个镜头")
    project = store.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    job_card = get_card(job.get("preset_id") or "")
    if job_card and not is_video_card(job_card):
        raise HTTPException(status_code=400,
                            detail="这是图片卡生成的结果，不能直接存成镜头；"
                                   "可以在视频卡里把它当首帧")

    shot = store.create_shot(
        project["id"],
        body.title or f"镜头 {len(store.list_shots(project['id'])) + 1}",
        job.get("preset_id") or "",
    )
    store.update_shot(shot["id"], values=job.get("inputs") or {})
    store.update_job(job_id, project_id=project["id"], shot_id=shot["id"])

    updated = store.get_job(job_id)
    if updated and updated.get("status") == "succeeded" and updated.get("outputs"):
        await runner._attach_last_frame(updated, updated["outputs"])

    return _enrich_shot(store.get_shot(shot["id"]) or shot)


# ---------------------------------------------------------------- 项目 / 镜头
class ProjectCreate(BaseModel):
    name: str
    style: str = ""
    notes: str = ""


class ShotCreate(BaseModel):
    project_id: str
    title: str = ""
    preset_id: str = ""
    prompt: str = ""
    values: dict[str, Any] = {}


def _enrich_shot(shot: dict) -> dict:
    """补上末帧预览地址，前端不用再查一次。"""
    frame_id = shot.get("last_frame")
    if frame_id:
        asset = store.get_asset(frame_id)
        if asset:
            shot["last_frame_url"] = f"/media/files/{asset['path']}"
            shot["last_frame_ambiguous"] = (asset.get("meta") or {}).get("note") != "ffmpeg"
    return shot


@app.get("/api/projects")
async def projects() -> dict:
    items = store.list_projects()
    for p in items:
        p["shots"] = len(store.list_shots(p["id"]))
    return {"items": items}


@app.post("/api/projects")
async def create_project(body: ProjectCreate) -> dict:
    return store.create_project(body.name, body.style, body.notes)


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict:
    store.delete_project(project_id)
    return {"ok": True}


@app.get("/api/projects/{project_id}/shots")
async def shots(project_id: str) -> dict:
    return {"items": [_enrich_shot(s) for s in store.list_shots(project_id)]}


class ShotReorder(BaseModel):
    shot_ids: list[str] = []


@app.post("/api/projects/{project_id}/shots/reorder")
async def reorder_shots(project_id: str, body: ShotReorder) -> dict:
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    items = store.reorder_shots(project_id, body.shot_ids)
    return {"items": [_enrich_shot(s) for s in items]}


@app.post("/api/shots")
async def create_shot(body: ShotCreate) -> dict:
    if not store.get_project(body.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    card = get_card(body.preset_id) if body.preset_id else None
    if card and not is_video_card(card):
        raise HTTPException(status_code=400,
                            detail="图片能力卡不能单独作为镜头；请用视频卡，或在视频卡里把它当首帧")
    shot = store.create_shot(body.project_id, body.title, body.preset_id, body.prompt)
    if body.values:
        store.update_shot(shot["id"], values=body.values)
    return _enrich_shot(store.get_shot(shot["id"]) or shot)


@app.get("/api/shots/{shot_id}")
async def shot_detail(shot_id: str) -> dict:
    shot = store.get_shot(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    return _enrich_shot(shot)


class ShotPatch(BaseModel):
    title: str | None = None
    preset_id: str | None = None
    prompt: str | None = None
    cover: str | None = None
    idx: int | None = None
    values: dict[str, Any] | None = None


@app.patch("/api/shots/{shot_id}")
async def patch_shot(shot_id: str, body: ShotPatch) -> dict:
    store.update_shot(shot_id, **body.model_dump(exclude_none=True))
    shot = store.get_shot(shot_id) or {}
    return _enrich_shot(shot)


@app.delete("/api/shots/{shot_id}")
async def delete_shot(shot_id: str) -> dict:
    store.delete_shot(shot_id)
    return {"ok": True}


class ShotGenerate(BaseModel):
    preset_id: str | None = None
    values: dict[str, Any] | None = None


@app.post("/api/shots/{shot_id}/generate")
async def generate_shot(shot_id: str, body: ShotGenerate | None = None) -> dict:
    shot = store.get_shot(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    preset_id = (body.preset_id if body and body.preset_id else shot.get("preset_id")) or ""
    values = (body.values if body and body.values is not None else shot.get("values")) or {}
    card = get_card(preset_id)
    if not card:
        raise HTTPException(status_code=400, detail="镜头还没有选择能力卡")
    if card.get("error"):
        raise HTTPException(status_code=400, detail=card["error"])
    errors = validate(card, values)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))
    store.update_shot(shot_id, preset_id=preset_id, values=values)
    job = store.create_job(preset_id, values, shot.get("project_id") or "", shot_id)
    await runner.enqueue(job["id"])
    return job


class ActivateTake(BaseModel):
    job_id: str


@app.post("/api/shots/{shot_id}/activate-take")
async def activate_take(shot_id: str, body: ActivateTake) -> dict:
    shot = store.get_shot(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    job = store.get_job(body.job_id)
    if not job or job.get("shot_id") != shot_id:
        raise HTTPException(status_code=400, detail="这个任务不属于该镜头")
    if job.get("status") != "succeeded":
        raise HTTPException(status_code=400, detail="只能选用已完成的任务")
    store.update_shot(shot_id, active_job=body.job_id)
    for item in job.get("outputs") or []:
        if isinstance(item, dict) and item.get("kind") == "image" and item.get("asset_id"):
            store.update_shot(shot_id, last_frame=item["asset_id"])
            break
    return _enrich_shot(store.get_shot(shot_id) or shot)


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="任务还在进行，请先取消")
    keep = str((store.get_shot(job.get("shot_id") or "") or {}).get("active_job") or "")
    store.delete_job(job_id)
    if keep == job_id and job.get("shot_id"):
        store.update_shot(job["shot_id"], active_job="")
    return {"ok": True}


def _shot_video(shot: dict) -> tuple[str, Path] | None:
    jobs = store.list_jobs_by_shot(shot["id"], limit=20)
    active = str(shot.get("active_job") or "")
    if active:
        jobs = [j for j in jobs if j["id"] == active] + [j for j in jobs if j["id"] != active]
    for job in jobs:
        if job.get("status") != "succeeded":
            continue
        for item in job.get("outputs") or []:
            if isinstance(item, dict) and item.get("kind") == "video" and item.get("url"):
                url = item["url"]
                if url.startswith("/media/outputs/"):
                    return url, DATA / "outputs" / url.removeprefix("/media/outputs/")
                if url.startswith("/media/files/"):
                    return url, DATA / url.removeprefix("/media/files/")
    return None


@app.get("/api/shots/{shot_id}/frames")
async def shot_frames(shot_id: str, count: int = 3) -> dict:
    shot = store.get_shot(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    found = _shot_video(shot)
    if not found or not found[1].exists():
        return {"items": []}
    frame_dir = DATA / "thumbs" / "frames"
    try:
        files = await ffmpeg.extract_frames(found[1], frame_dir, count, prefix=f"shot_{shot_id}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"截帧失败：{exc}")
    items = []
    for path in files:
        rel = path.relative_to(DATA).as_posix()
        items.append({"url": f"/media/files/{rel}"})
    return {"items": items}


class TitleRequest(BaseModel):
    project_id: str
    kind: str = "title"
    system_prompt: str | None = None
    user_prompt: str | None = None


MOOD_CYCLE = {
    "开场": ["轻快", "治愈", "搞笑"],
    "发展": ["电子", "轻快", "燃"],
    "转折": ["燃", "悬念", "史诗"],
    "收尾": ["治愈", "史诗", "悬念"],
}


@app.post("/api/ai/bgm-plan")
async def ai_bgm_plan(body: TitleRequest) -> dict:
    """按段落自动配乐：把正片分成最多 3 段，每段挑一首情绪合适的音乐。"""
    project = store.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    raw_state = store.get_setting(_edit_state_key(body.project_id), "")
    try:
        state = json.loads(raw_state) if raw_state else {}
    except Exception:
        state = {}
    options = state.get("options") or {}
    all_shots = store.list_shots(body.project_id)
    shots = {s["id"]: s for s in all_shots}
    order = {s["id"]: i for i, s in enumerate(all_shots)}
    edits = {str(e.get("shot_id")): e for e in (state.get("shot_edits") or []) if e.get("shot_id")}
    selected = sorted([sid for sid in edits if sid in shots], key=lambda sid: order.get(sid, 0))
    if not selected:
        raise HTTPException(status_code=400, detail="还没有勾选镜头")

    timeline = await build_timeline(shots, selected, edits, options)
    items = timeline["items"]
    if not items:
        raise HTTPException(status_code=400, detail="时间轴为空")

    # 段落划分：优先用大纲里的分镜定位，没有就按镜数三等分
    outline = str(store.get_setting(f"outline.{body.project_id}", "") or "")
    roles: list[str] = []
    for index in range(1, len(items) + 1):
        role = ai_script.outline_role(outline, index)
        bucket = "发展"
        for key in ("开场", "转折", "收尾"):
            if key in role:
                bucket = key
                break
        roles.append(bucket)
    if not any("开场" in r for r in roles):
        third = max(1, len(items) // 3)
        for i in range(len(items)):
            roles[i] = "开场" if i < third else ("收尾" if i >= len(items) - third else "发展")

    # 合并成最多 3 段
    segments: list[dict] = []
    for item, role in zip(items, roles):
        bucket = role
        if segments and segments[-1]["role"] == bucket:
            segments[-1]["end"] = item["end"]
            continue
        if len(segments) >= 3:
            segments[-1]["end"] = item["end"]
            continue
        segments.append({"role": bucket, "start": item["start"], "end": item["end"]})

    # 选曲
    music = [a for a in store.list_assets("audio", 200) if _asset_purpose(a) == "music"]
    if not music:
        raise HTTPException(status_code=400, detail="素材库里还没有背景音乐（先在资产页上传或跑 fetch_music.py）")

    used: set[str] = set()
    tracks: list[dict] = []
    notes: list[str] = []
    for index, segment in enumerate(segments, start=1):
        moods = MOOD_CYCLE.get(segment["role"], [])
        pick = None
        for mood in moods:
            pick = next((a for a in music
                         if str((a.get("meta") or {}).get("mood") or "") == mood and a["id"] not in used), None)
            if pick:
                break
        if not pick:
            pick = next((a for a in music if a["id"] not in used), music[0])
        used.add(pick["id"])
        name = pick["path"].rsplit("/", 1)[-1]
        mood = str((pick.get("meta") or {}).get("mood") or "")
        notes.append(f"第{index}段（{segment['role']}）→ {name}{f'（{mood}）' if mood else ''}")
        tracks.append({
            "id": f"auto{index}",
            "asset_id": pick["id"],
            "volume_db": -16 if segment["role"] != "转折" else -13,
            "start": round(segment["start"], 2),
            "end": round(segment["end"], 2),
            "fade_in": 0.8,
            "fade_out": 1.2,
            "loop": True,
        })

    return {"tracks": tracks, "segments": segments, "notes": notes,
            "total": timeline["total"]}


@app.post("/api/ai/outline")
async def ai_outline(body: TitleRequest) -> dict:
    """生成/刷新全片大纲，并缓存到 settings，供后续每个镜头复用。"""
    project = store.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    shots = store.list_shots(body.project_id)
    if not shots:
        raise HTTPException(status_code=400, detail="项目还没有镜头")
    try:
        text = await ai_script.build_outline(project, shots)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.set_setting(f"outline.{body.project_id}", text)
    return {"outline": text}


@app.post("/api/ai/title/preview")
async def ai_title_preview(body: TitleRequest) -> dict:
    project = store.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    shots = store.list_shots(body.project_id)
    kind = "tail" if body.kind == "tail" else "title"
    try:
        system, user = ai_script.build_title_prompt(project, shots, kind)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"kind": kind, "system": system, "user": user}


@app.post("/api/ai/title")
async def ai_title(body: TitleRequest) -> dict:
    project = store.get_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    shots = store.list_shots(body.project_id)
    kind = "tail" if body.kind == "tail" else "title"
    try:
        text = await ai_script.title_for(project, shots, kind,
                                         system_override=body.system_prompt,
                                         user_override=body.user_prompt)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"text": text, "kind": kind}


@app.get("/api/projects/{project_id}/rhythm")
async def project_rhythm(project_id: str) -> dict:
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    raw = store.get_setting("edit_state." + project_id, "")
    edits: dict[str, dict] = {}
    if raw:
        try:
            for item in json.loads(raw).get("shot_edits", []):
                edits[item.get("shot_id")] = item
        except Exception:
            pass
    items: list[dict] = []
    total = 0.0
    for shot in store.list_shots(project_id):
        found = _shot_video(shot)
        duration = 0.0
        if found and found[1].exists():
            try:
                duration = await ffmpeg.duration_of(found[1])
            except Exception:
                duration = 0.0
        edit = edits.get(shot["id"], {})
        start = float(edit.get("in_point") or 0)
        end = float(edit["out_point"]) if edit.get("out_point") else duration
        dur = max(0.0, min(end, duration) - start)
        total += dur
        level = "ok"
        advice = ""
        if not duration:
            level = "warn"
            advice = "还没有可用的视频产物"
        elif dur < 1.5:
            level = "warn"
            advice = f"只有 {dur:.1f}s，容易一闪而过，建议至少 2s"
        elif dur > 6:
            level = "warn"
            advice = f"{dur:.1f}s 偏长，叙事镜头建议裁到 4~5s"
        items.append({"shot_id": shot["id"], "title": shot.get("title") or "",
                      "duration": round(dur, 2), "level": level, "advice": advice})
    if items and all(i["level"] == "ok" for i in items):
        summary = f"共 {len(items)} 镜、{total:.1f}s，节奏没有明显问题"
    else:
        bad = sum(1 for i in items if i["level"] != "ok")
        summary = f"共 {len(items)} 镜、{total:.1f}s，其中 {bad} 镜建议调整"

    # BGM 建议（规则版）
    options = {}
    if raw:
        try:
            options = json.loads(raw).get("options") or {}
        except Exception:
            options = {}
    bgm = options.get("bgm") or {}
    has_voice = any((edits.get(i["shot_id"], {}) or {}).get("voice_asset") for i in items)
    audio_count = len(store.list_assets(kind="audio", limit=1))
    bgm_tips: list[dict] = []
    if not bgm.get("asset_id"):
        if has_voice:
            bgm_tips.append({"level": "warn", "text": "有旁白但还没配 BGM，建议加一条铺底音乐"})
        elif audio_count == 0:
            bgm_tips.append({"level": "info", "text": "素材库里还没有音频，先在资产页上传 BGM"})
        else:
            bgm_tips.append({"level": "info", "text": "当前没有 BGM，纯原声也可以"})
    else:
        if not bgm.get("duck", True):
            bgm_tips.append({"level": "warn", "text": "BGM 未开启自动闪避，旁白可能被音乐盖住"})
        if not bgm.get("loop", True) and total > 60:
            bgm_tips.append({"level": "warn", "text": "成片超过 1 分钟但 BGM 不循环，可能中途没声"})
        volume = float(bgm.get("volume_db") or -14)
        if volume > -6:
            bgm_tips.append({"level": "warn", "text": f"BGM 音量 {volume:.0f}dB 偏大，建议 -14 ~ -10dB"})
    return {"items": items, "total": round(total, 2), "summary": summary, "bgm_tips": bgm_tips}


@app.get("/api/shots/{shot_id}/preview")
async def shot_preview(shot_id: str) -> dict:
    shot = store.get_shot(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    found = _shot_video(shot)
    if not found:
        return {"url": "", "duration": 0, "source": ""}
    url, path = found
    duration = 0.0
    width = height = 0
    if path.exists():
        try:
            duration = await ffmpeg.duration_of(path)
        except Exception:
            duration = 0.0
        try:
            width, height = await ffmpeg.probe_size(path)
        except Exception:
            width = height = 0
    return {"url": url, "duration": round(duration, 3), "source": path.name,
            "width": width, "height": height}


async def build_timeline(
    shots: dict[str, dict],
    shot_ids: list[str],
    edits: dict[str, dict],
    options: dict,
) -> dict:
    """权威时间轴：正片各镜的真实起止 + 片头/片尾时长。

    转场重叠、变速、片头偏移都在这里算一次，前端只负责渲染。
    """
    trans = options.get("transition") or {}
    overlap = float(trans.get("duration") or 0) \
        if str(trans.get("type") or "none") in {"fade", "dissolve"} else 0.0

    title_opt = options.get("title") or {}
    tail_opt = options.get("tail") or {}
    title_text = str(title_opt.get("text") or "").strip() if title_opt.get("enabled") else ""
    tail_text = str(tail_opt.get("text") or "").strip() if tail_opt.get("enabled") else ""
    title_dur = float(title_opt.get("duration") or 1.5) if title_text else 0.0
    tail_dur = float(tail_opt.get("duration") or 2.0) if tail_text else 0.0

    items: list[dict] = []
    cursor = 0.0
    for index, sid in enumerate(shot_ids):
        shot = shots.get(sid)
        if not shot:
            continue
        found = _shot_video(shot)
        source = 0.0
        if found and found[1].exists():
            try:
                source = await ffmpeg.duration_of(found[1])
            except Exception:
                source = 0.0
        edit = edits.get(sid) or {}
        start_at = float(edit.get("in_point") or 0)
        end_at = float(edit["out_point"]) if edit.get("out_point") else source
        if source:
            end_at = min(end_at, source)
        speed = min(max(float(edit.get("speed") or 1.0), 0.5), 2.0)
        dur = max(0.0, end_at - start_at) / speed
        if index and overlap:
            cursor = max(0.0, cursor - overlap)
        items.append({
            "shot_id": sid,
            "title": shot.get("title") or "",
            "duration": round(dur, 3),
            "source_duration": round(source, 3),
            "in_point": round(start_at, 3),
            "out_point": round(end_at, 3) if source else None,
            "speed": speed,
            "start": round(cursor, 3),
            "end": round(cursor + dur, 3),
        })
        cursor += dur

    return {
        "items": items,
        "total": round(cursor, 3),
        "title_duration": round(title_dur, 3),
        "tail_duration": round(tail_dur, 3),
        "overlap": round(overlap, 3),
        "full_total": round(title_dur + cursor + tail_dur, 3),
    }


@app.get("/api/projects/{project_id}/timeline")
async def project_timeline(project_id: str) -> dict:
    """项目当前编辑状态下的时间轴（只计算，不改数据）。"""
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    raw = store.get_setting(_edit_state_key(project_id), "")
    try:
        state = json.loads(raw) if raw else {}
    except Exception:
        state = {}
    options = state.get("options") or {}
    all_shots = store.list_shots(project_id)
    shots = {s["id"]: s for s in all_shots}
    order = {s["id"]: index for index, s in enumerate(all_shots)}
    edits = {str(e.get("shot_id")): e for e in (state.get("shot_edits") or []) if e.get("shot_id")}
    # 前端只把「勾选参与导出」的镜头写进 shot_edits，按项目里的顺序排
    selected = [sid for sid in edits if sid in shots]
    ordered = sorted(selected or list(shots), key=lambda sid: order.get(sid, 0))
    return await build_timeline(shots, ordered, edits, options)


@app.get("/api/renders/{render_id}/timeline")
async def render_timeline(render_id: str) -> dict:
    render = store.get_render(render_id)
    if not render:
        raise HTTPException(status_code=404, detail="成片不存在")
    shots = {s["id"]: s for s in store.list_shots(render["project_id"])}
    edits = {row["shot_id"]: row for row in store.list_render_shots(render_id)}
    return await build_timeline(shots, render.get("shot_ids") or [], edits,
                                render.get("options") or {})


@app.get("/api/shots/{shot_id}/takes")
async def shot_takes(shot_id: str, limit: int = 12) -> dict:
    return {"items": store.list_jobs_by_shot(shot_id, limit)}


# ---------------------------------------------------------------- 成片导出
def _enrich_render(render: dict) -> dict:
    if render.get("output_path"):
        render["output_url"] = f"/media/files/{render['output_path']}"
        render["download_name"] = Path(render["output_path"]).name
        target = DATA / render["output_path"]
        if target.exists():
            render["size_bytes"] = target.stat().st_size
    if render.get("cover_path"):
        render["cover_url"] = f"/media/files/{render['cover_path']}"

    options = render.get("options") or {}
    trans = options.get("transition") or {}
    render["is_preview"] = bool(options.get("preview"))
    render["summary"] = {
        "preview": bool(options.get("preview")),
        "width": int(options.get("width") or 0),
        "height": int(options.get("height") or 0),
        "fps": int(options.get("fps") or 0),
        "transition": str(trans.get("type") or "none"),
        "bgm": bool((options.get("bgm") or {}).get("asset_id")),
        "subtitles": bool((options.get("subtitles") or {}).get("enabled", True)),
        "loudness": bool((options.get("loudness") or {}).get("enabled", True)),
        "title": str((options.get("title") or {}).get("text") or ""),
        "tail": str((options.get("tail") or {}).get("text") or ""),
    }
    return render


class RenderCreate(BaseModel):
    shot_ids: list[str] = []
    options: dict[str, Any] = {}
    shot_edits: list[dict[str, Any]] = []


class AISettings(BaseModel):
    base_url: str
    api_key: str | None = None
    model: str = ""
    proxy: str = ""
    vision_model: str = ""


@app.get("/api/settings/ai")
async def get_ai_settings() -> dict:
    return runtime.public_ai_settings()


@app.put("/api/settings/ai")
async def put_ai_settings(body: AISettings) -> dict:
    try:
        return runtime.save_ai_settings(body.base_url, body.api_key, body.model, body.proxy, body.vision_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/settings/ai/reset")
async def reset_ai_settings() -> dict:
    return runtime.reset_ai_settings()


@app.post("/api/settings/ai/test")
async def test_ai_settings(body: AISettings) -> dict:
    """用当前（或传入）配置请求 /models，验证 key 与地址。"""
    base = runtime.normalize_url(body.base_url or str(settings.get("ai.base_url", "")))
    key = (body.api_key or str(settings.get("ai.api_key", ""))).strip()
    proxy = (body.proxy or str(settings.get("ai.proxy", ""))).strip()
    if not base:
        raise HTTPException(status_code=400, detail="请先填写 Base URL")
    if not key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")
    import time

    started = time.time()
    # 内网地址（192.168 / 10. / 172.16-31 / localhost）不能走代理，否则代理会返回 504
    use_proxy = proxy_for(base, proxy)
    note = proxy_note(base, proxy)
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False, proxy=use_proxy) as client:
            resp = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        latency = int((time.time() - started) * 1000)
        if resp.status_code >= 400:
            text = resp.text[:200].replace("\n", " ")
            return {"ok": False, "latency_ms": latency, "proxy_used": bool(use_proxy),
                    "error": f"HTTP {resp.status_code}{note}: {text}"}
        return {"ok": True, "latency_ms": latency, "proxy_used": bool(use_proxy),
                "model_count": len((resp.json() or {}).get("data") or [])}
    except Exception as exc:
        return {"ok": False, "proxy_used": bool(use_proxy),
                "error": f"{type(exc).__name__}{note}: {exc}"}


@app.get("/api/ffmpeg/status")
async def ffmpeg_status() -> dict:
    return {**ffmpeg.status(), "capabilities": ffmpeg.capabilities()}


@app.post("/api/projects/{project_id}/renders")
async def create_render(project_id: str, body: RenderCreate) -> dict:
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    shots = store.list_shots(project_id)
    valid = {s["id"] for s in shots}
    shot_ids = [sid for sid in body.shot_ids if sid in valid]
    if not shot_ids:
        raise HTTPException(status_code=400, detail="至少要选一个镜头")
    options = {
        "width": int(body.options.get("width") or 1280),
        "height": int(body.options.get("height") or 720),
        "fps": int(body.options.get("fps") or 24),
        "cover_at": float(body.options.get("cover_at") or 1.0),
        "bgm": body.options.get("bgm") or {},
        "subtitles": body.options.get("subtitles") or {},
        "loudness": body.options.get("loudness") or {},
    }
    # 转场 / 预览等可选参数原样带上
    for extra in ("transition", "preview", "title", "tail", "fit", "bgm_tracks"):
        if extra in body.options:
            options[extra] = body.options[extra]
    if options["width"] < 64 or options["height"] < 64:
        raise HTTPException(status_code=400, detail="分辨率太小")
    if not ffmpeg.status()["available"]:
        raise HTTPException(status_code=400, detail=ffmpeg.status()["hint"])
    draft = bool(body.options.get("draft"))
    cache_key = ""
    if options.get("preview"):
        import hashlib

        signature = {
            "options": options,
            "shot_ids": shot_ids,
            "shot_edits": body.shot_edits,
        }
        for sid in shot_ids:
            shot = store.get_shot(sid) or {}
            found = _shot_video(shot)
            if found and found[1].exists():
                st = found[1].stat()
                signature.setdefault("sources", {})[sid] = [found[1].name, int(st.st_size), int(st.st_mtime)]
        cache_key = hashlib.sha1(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        options["cache_key"] = cache_key
        cached_id = store.get_setting("preview_cache." + cache_key, "")
        if cached_id:
            cached = store.get_render(cached_id)
            if cached and cached["status"] == "succeeded":
                out = DATA / "renders" / cached_id / "final.mp4"
                if out.exists():
                    return _enrich_render(cached)

    render = store.create_render(project_id, shot_ids, options)
    if draft:
        store.update_render(render["id"], status="draft", message="草稿")
    if body.shot_edits:
        allowed = set(shot_ids)
        store.save_render_shots(render["id"], [e for e in body.shot_edits if e.get("shot_id") in allowed])
    if not draft:
        await render_runner.enqueue(render["id"])
    return _enrich_render(render)


class EditState(BaseModel):
    options: dict[str, Any] = {}
    shot_edits: list[dict[str, Any]] = []


def _edit_state_key(project_id: str) -> str:
    return f"edit_state.{project_id}"


@app.get("/api/projects/{project_id}/edit-state")
async def get_edit_state(project_id: str) -> dict:
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    raw = store.get_setting(_edit_state_key(project_id), "")
    if not raw:
        return {"options": {}, "shot_edits": []}
    try:
        data = json.loads(raw)
        return {"options": data.get("options") or {}, "shot_edits": data.get("shot_edits") or []}
    except Exception:
        return {"options": {}, "shot_edits": []}


@app.put("/api/projects/{project_id}/edit-state")
async def put_edit_state(project_id: str, body: EditState) -> dict:
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    store.set_setting(
        _edit_state_key(project_id),
        json.dumps({"options": body.options, "shot_edits": body.shot_edits}, ensure_ascii=False),
    )
    return {"ok": True, "saved_at": int(time.time())}


class TTSSettings(BaseModel):
    base_url: str
    api_key: str | None = None
    model: str = "qwen-audio-3.0-tts-plus"
    voice: str = "longanlufeng"
    format: str = "wav"
    sample_rate: int = 24000
    proxy: str = ""


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None
    shot_id: str | None = None


class ScriptRequest(BaseModel):
    shot_id: str
    kind: str = "subtitle"
    mode: str = "fill"
    narration: str = ""
    frames: int = 0
    style: dict[str, Any] = {}
    system_prompt: str | None = None
    user_prompt: str | None = None
    frame_picks: list[int] | None = None
    outline: str | None = None


@app.get("/api/settings/tts")
async def get_tts_settings() -> dict:
    data = tts_module.config()
    data["overridden"] = bool(store.list_settings().get("tts.base_url"))
    data["voices"] = tts_module.VOICES.get(data["model"], [])
    return data


@app.put("/api/settings/tts")
async def put_tts_settings(body: TTSSettings) -> dict:
    try:
        tts_module.check_voice(body.model, body.voice)
        data = runtime.save_tts_settings(body.base_url, body.api_key, body.model,
                                         body.voice, body.format, body.sample_rate, body.proxy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    data["voices"] = tts_module.VOICES.get(data["model"], [])
    return data


@app.post("/api/settings/tts/reset")
async def reset_tts() -> dict:
    return runtime.reset_tts_settings()


class ASRSettings(BaseModel):
    base_url: str
    api_key: str | None = None
    model: str = "qwen-audio-3.0-asr-flash"
    proxy: str = ""


@app.get("/api/settings/asr")
async def get_asr_settings() -> dict:
    cfg = asr.config()
    key = str(cfg.pop("api_key", "") or "")
    cfg["key_set"] = bool(key)
    cfg["key_hint"] = (key[:4] + "…" + key[-4:]) if len(key) > 8 else ""
    cfg["available"] = asr.available()
    cfg["overridden"] = bool(store.list_settings().get("asr.base_url"))
    return cfg


@app.put("/api/settings/asr")
async def put_asr_settings(body: ASRSettings) -> dict:
    try:
        runtime.save_asr_settings(body.base_url, body.api_key, body.model, body.proxy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await get_asr_settings()


@app.post("/api/settings/asr/reset")
async def reset_asr() -> dict:
    runtime.reset_asr_settings()
    return await get_asr_settings()


@app.post("/api/settings/asr/test")
async def test_asr() -> dict:
    """用 TTS 合成一句测试语音，再交给 ASR 转写，验证配置是否可用。"""
    sample = "这是语音转写测试。"
    try:
        audio = await tts_module.synthesize(sample)
    except Exception as exc:
        return {"ok": False, "stage": "tts", "error": f"先生成测试语音失败：{exc}"}
    try:
        text = await asr.transcribe(Path(audio["path"]))
    except Exception as exc:
        return {"ok": False, "stage": "asr", "error": str(exc)}
    return {"ok": True, "expect": sample, "text": text,
            "duration": audio.get("duration", 0),
            "match": sample.strip("。") in text.replace(" ", "")}


@app.get("/api/tts/voices")
async def tts_voices(model: str | None = None) -> dict:
    name = model or tts_module.config()["model"]
    return {"model": name, "items": tts_module.VOICES.get(name, [])}


@app.post("/api/settings/tts/test")
async def test_tts(body: TTSSettings | None = None) -> dict:
    try:
        result = await tts_module.synthesize("测试一二。", body.voice if body else None, use_cache=False)
        rel = Path(result["path"]).relative_to(DATA).as_posix()
        return {"ok": True, "duration": result["duration"], "cached": result.get("cached", False),
                "url": f"/media/files/{rel}"}
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else f"{type(exc).__name__}（没有错误信息）"
        return {"ok": False, "error": detail}


@app.post("/api/ai/tts")
async def ai_tts(body: TTSRequest) -> dict:
    try:
        result = await tts_module.synthesize(body.text, body.voice)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    path = Path(result["path"])
    rel = path.relative_to(DATA).as_posix()
    asset = store.get_asset_by_path(rel) or store.add_asset(
        "audio", rel, size=path.stat().st_size,
        meta={"origin": "tts", "text": body.text[:120], "purpose": "narration"})
    slot = 0.0
    if body.shot_id:
        shot = store.get_shot(body.shot_id)
        found = _shot_video(shot) if shot else None
        if found and found[1].exists():
            try:
                slot = await ffmpeg.duration_of(found[1])
            except Exception:
                slot = 0.0
    tempo = tts_module.tempo_for(result["duration"], slot) if slot else 1.0
    return {
        "asset_id": asset["id"],
        "url": f"/media/files/{rel}",
        "duration": result["duration"],
        "cached": result.get("cached", False),
        "slot": round(slot, 2),
        "tempo": tempo,
        "too_long": bool(slot and tempo >= 1.3),
    }


def _edit_state_map(project_id: str) -> dict[str, dict]:
    raw = store.get_setting(_edit_state_key(project_id), "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return {str(e.get("shot_id")): e for e in (data.get("shot_edits") or []) if e.get("shot_id")}


def _neighbors_for(project_id: str, shot_id: str) -> dict:
    """前后镜上下文：标题 + 压缩描述 + 已有旁白，供模型保持连贯、避免重复。"""
    siblings = sorted(store.list_shots(project_id), key=lambda s: s["idx"])
    index = next((i for i, s in enumerate(siblings) if s["id"] == shot_id), -1)
    edits = _edit_state_map(project_id)

    def pack(item: dict | None) -> dict:
        if not item:
            return {"title": "", "description": "", "narration": ""}
        edit = edits.get(item["id"]) or {}
        narration = str(edit.get("narration") or "").strip()
        raw = ai_script.shot_description(item)
        return {
            "title": item.get("title", ""),
            "description": ai_script.compact_description(raw)[:120] if raw else "",
            "narration": narration[:60],
        }

    prev_item = siblings[index - 1] if index > 0 else None
    next_item = siblings[index + 1] if 0 <= index < len(siblings) - 1 else None
    prev_pack = pack(prev_item)
    next_pack = pack(next_item)
    return {
        "prev": prev_pack["title"],
        "next": next_pack["title"],
        "prev_prompt": prev_pack["description"],
        "next_prompt": next_pack["description"],
        "prev_narration": prev_pack["narration"],
        "next_narration": next_pack["narration"],
        "index": index + 1 if index >= 0 else 0,
        "total": len(siblings),
    }


@app.post("/api/ai/prompt-preview")
async def ai_prompt_preview(body: ScriptRequest) -> dict:
    """返回这次 AI 生成将要发送的完整提示词，供前端弹框展示与编辑。"""
    shot = store.get_shot(body.shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    kind = body.kind if body.kind in {"subtitle", "narration"} else "subtitle"
    project = store.get_project(shot["project_id"]) or {}
    neighbors = _neighbors_for(shot["project_id"], shot["id"])
    found = _shot_video(shot)
    duration = 5.0
    if found and found[1].exists():
        try:
            duration = await ffmpeg.duration_of(found[1]) or 5.0
        except Exception:
            pass
    edits = _edit_state_map(shot["project_id"])
    saved_outline = str((store.list_settings() or {}).get(f"outline.{shot['project_id']}", "") or "")
    try:
        system, user = ai_script.build_prompt(kind, shot, project, neighbors, duration,
                                              body.style or {}, outline=body.outline or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "kind": kind,
        "system": system,
        "user": user,
        "duration": round(duration, 2),
        "budget": ai_script.char_budget(kind, duration),
        "frames_available": bool(found and found[1].exists()),
        "outline": saved_outline,
        "shot_count": len(edits) or len(store.list_shots(shot["project_id"])),
    }


@app.post("/api/ai/script")
async def ai_script_one(body: ScriptRequest) -> dict:
    shot = store.get_shot(body.shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    kind = body.kind if body.kind in {"subtitle", "narration"} else "subtitle"
    project = store.get_project(shot["project_id"]) or {}
    neighbors = _neighbors_for(shot["project_id"], shot["id"])

    found = _shot_video(shot)
    duration = 5.0
    if found and found[1].exists():
        try:
            duration = await ffmpeg.duration_of(found[1]) or 5.0
        except Exception:
            pass

    budget = ai_script.char_budget(kind, duration)

    # 字幕优先跟随旁白，但要先确认旁白确实对应这个画面
    if kind == "subtitle" and body.narration.strip():
        description = ai_script.shot_description(shot)
        matched = await ai_script.narration_matches(body.narration, description)
        if matched:
            return ai_script.fit_narration(body.narration, budget)
        result = await ai_script.generate(kind, shot, project, neighbors, duration, body.style or {})
        result["narration_mismatch"] = True
        result["reason"] = "旁白和画面描述不一致，已按画面描述生成字幕，建议重新写旁白"
        return result

    # 没有旁白：先看镜头里有没有人声/口播
    if kind == "subtitle" and found and found[1].exists():
        try:
            ratio = await ffmpeg.speech_ratio(found[1])
        except Exception:
            ratio = 0.0
        if ratio < 0.15:
            return {"skip": "silent", "reason": "这个镜头没有明显人声，按设置不加字幕",
                    "text": "", "chars": 0, "budget": budget, "duration": round(duration, 2)}
        if not asr.available():
            raise HTTPException(
                status_code=400,
                detail="检测到这个镜头有口播，但还没有配置语音转写（ASR）",
            )
        try:
            text = await asr.transcribe(found[1])
        except Exception as exc:
            message = str(exc)
            if " 400" in message:
                # 有声音但模型没听出人声（多半是音乐/环境音）
                return {"skip": "silent", "reason": "检测到声音但没有识别到人声，按设置不加字幕",
                        "text": "", "chars": 0, "budget": budget, "duration": round(duration, 2)}
            raise HTTPException(status_code=400, detail=message)
        text = ai_script.clean(text)
        if len(text) > budget:
            text = text[:budget].rstrip("，。！？、,.!? ")
        return {"text": text, "chars": len(text), "budget": budget, "over": False,
                "compressed": False, "original_chars": len(text),
                "transcribed": True, "duration": round(duration, 2)}

    images: list[Path] = []
    if body.frames > 0 and found and found[1].exists():
        frame_dir = DATA / "thumbs" / "frames"
        picks = body.frame_picks
        count = max(body.frames, (max(picks) + 1) if picks else 0)
        try:
            images = await ffmpeg.extract_frames(found[1], frame_dir, count,
                                                 prefix=f"shot_{shot['id']}")
        except Exception:
            images = []
        if picks and images:
            # 前端勾了具体哪几张，就按序号取
            images = [images[i] for i in picks if 0 <= i < len(images)]
    try:
        return await ai_script.generate(kind, shot, project, neighbors, duration,
                                       body.style or {}, images=images,
                                       system_override=body.system_prompt,
                                       user_override=body.user_prompt,
                                       outline=body.outline or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def _backfill_durations(items: list[dict], budget: int = 20) -> None:
    """老记录没有 duration，顺手补一次并写回库，避免前端显示空。"""
    done = 0
    for item in items:
        if done >= budget:
            return
        if item.get("duration") or not item.get("output_path"):
            continue
        target = DATA / item["output_path"]
        if not target.exists():
            continue
        try:
            value = await ffmpeg.duration_of(target)
        except Exception:
            continue
        if value:
            item["duration"] = round(value, 2)
            store.update_render(item["id"], duration=item["duration"])
        done += 1


@app.get("/api/activity/new-counts")
async def activity_new_counts(jobs_since: float = 0, renders_since: float = 0) -> dict:
    """给侧边栏角标用：分别统计「此后新完成」的任务数与成片数。"""
    def count(sql: str, since: float) -> int:
        with store.connect() as conn:
            row = conn.execute(sql, (since,)).fetchone()
            return int(row[0] or 0) if row else 0

    jobs = count(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('succeeded','failed') "
        "AND COALESCE(finished_at, created_at) > ?", jobs_since)
    renders = count(
        "SELECT COUNT(*) FROM renders WHERE status = 'succeeded' "
        "AND COALESCE(finished_at, created_at) > ?", renders_since)
    return {"jobs": jobs, "renders": renders}


@app.get("/api/renders")
async def list_all_renders(limit: int = 50, status: str | None = None,
                           project_id: str | None = None) -> dict:
    items = store.list_renders_all(limit * 4 if project_id else limit, status)
    if project_id:
        items = [r for r in items if r.get("project_id") == project_id][:limit]
    enriched = [_enrich_render(r) for r in items]
    await _backfill_durations(enriched)
    return {"items": enriched}


@app.post("/api/renders/{render_id}/start")
async def start_render(render_id: str) -> dict:
    render = store.get_render(render_id)
    if not render:
        raise HTTPException(status_code=404, detail="成片不存在")
    if render["status"] not in {"draft", "failed"}:
        raise HTTPException(status_code=400, detail="只有草稿或失败的成片可以重新开始")
    store.update_render(render_id, status="queued", progress=0.0, message="排队中",
                        error="", started_at=None, finished_at=None)
    await render_runner.enqueue(render_id)
    return _enrich_render(store.get_render(render_id) or render)


@app.post("/api/renders/{render_id}/cancel")
async def cancel_render(render_id: str) -> dict:
    render = store.get_render(render_id)
    if not render:
        raise HTTPException(status_code=404, detail="成片不存在")
    if render["status"] in {"succeeded", "failed", "canceled"}:
        raise HTTPException(status_code=400, detail="这个成片已经结束")
    render_runner.cancel(render_id)
    store.update_render(render_id, message="取消中…", status="rendering" if render["status"] == "rendering" else render["status"])
    return _enrich_render(store.get_render(render_id) or render)


@app.get("/api/renders/{render_id}/subtitles")
async def render_subtitles(render_id: str):
    render = store.get_render(render_id)
    if not render:
        raise HTTPException(status_code=404, detail="成片不存在")
    path = DATA / "renders" / render_id / "subtitles.srt"
    if not path.exists():
        raise HTTPException(status_code=404, detail="这次导出没有生成字幕")
    return FileResponse(path, media_type="text/plain; charset=utf-8",
                        filename=f"{render_id}.srt")


@app.get("/api/projects/{project_id}/renders")
async def list_renders(project_id: str, limit: int = 20) -> dict:
    return {"items": [_enrich_render(r) for r in store.list_renders(project_id, limit)]}


@app.get("/api/renders/{render_id}")
async def render_detail(render_id: str) -> dict:
    render = store.get_render(render_id)
    if not render:
        raise HTTPException(status_code=404, detail="成片任务不存在")
    return _enrich_render(render)


@app.delete("/api/renders/{render_id}")
async def delete_render(render_id: str) -> dict:
    render = store.get_render(render_id)
    if not render:
        raise HTTPException(status_code=404, detail="成片任务不存在")
    folder = DATA / "renders" / render_id
    if folder.exists():
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    with store.connect() as conn:
        conn.execute("DELETE FROM renders WHERE id=?", (render_id,))
    return {"ok": True}


# ---------------------------------------------------------------- 提示词助手
PROMPT_MODES = {
    "t2i": {"key": "imagePrompt", "label": "文生图", "desc": "写图片提示词"},
    "t2v": {"key": "keyframeT2va", "label": "文生视频", "desc": "没有任何参考图"},
    "i2v": {"key": "keyframeI2va", "label": "图生视频", "desc": "一张首帧"},
    "flf2v": {"key": "keyframeFl2va", "label": "首尾帧", "desc": "首帧 + 尾帧"},
    "r2v": {"key": "fullReference", "label": "多参考", "desc": "多图/多素材参考"},
}


def _skill_prompts() -> dict:
    path = CONTENT / "skill-prompt.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@app.get("/api/prompt/modes")
async def prompt_modes() -> dict:
    prompts = _skill_prompts()
    items = []
    for mode, meta in PROMPT_MODES.items():
        items.append({
            "mode": mode,
            "label": meta["label"],
            "desc": meta["desc"],
            "available": bool(prompts.get(meta["key"])),
        })
    ai_key = bool(settings.get("ai.api_key", ""))
    return {"items": items, "ai_configured": ai_key, "model": settings.get("ai.model", "")}


@app.get("/api/prompt/examples")
async def prompt_examples() -> dict:
    path = CONTENT / "apiimageprompt.yaml"
    if not path.exists():
        return {"items": []}
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"items": data.get("prompts", [])}


class RewriteRequest(BaseModel):
    mode: str = "t2v"
    brief: str
    extra: str = ""




PROMPT_ORDER = [
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
]


def _format_prompt_content(raw: str) -> str:
    """把模型返回的 JSON 转成 H3 工作流习惯的六段式文本。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except Exception:
        return raw
    if not isinstance(data, dict):
        return raw

    blocks: list[str] = []
    keys = [k for k in PROMPT_ORDER if k in data] + [k for k in data if k not in PROMPT_ORDER]
    for key in keys:
        value = data[key]
        if isinstance(value, list):
            body = "\n".join(str(v).strip() for v in value if str(v).strip())
        elif isinstance(value, str):
            body = value.strip()
        else:
            body = json.dumps(value, ensure_ascii=False)
        blocks.append(f"{key}:\n{body}")
    return "\n\n".join(blocks)


@app.post("/api/prompt/rewrite")
async def rewrite_prompt(body: RewriteRequest) -> dict:
    prompts = _skill_prompts()
    meta = PROMPT_MODES.get(body.mode)
    if not meta:
        raise HTTPException(status_code=400, detail="未知模式")
    system = prompts.get(meta["key"])
    if not system:
        raise HTTPException(status_code=400, detail="提示词系统模板缺失")
    api_key = settings.get("ai.api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="没有配置 ai.api_key，无法调用提示词模型")
    base = str(settings.get("ai.base_url", "")).rstrip("/")
    model = settings.get("ai.model", "")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": body.brief + (("\n\n补充要求：" + body.extra) if body.extra else "")},
        ],
        "temperature": 0.7,
    }
    try:
        proxy = str(settings.get("ai.proxy", "") or "").strip()
        client_kwargs: dict[str, Any] = {"timeout": 120, "trust_env": False}
        if proxy:
            client_kwargs["proxy"] = proxy
        elif settings.get("ai.trust_env", False):
            client_kwargs["trust_env"] = True
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"提示词模型返回 {resp.status_code}：{resp.text[:200]}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {"ok": True, "content": _format_prompt_content(content), "model": model}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"调用提示词模型失败：{exc}") from exc


# ---------------------------------------------------------------- 前端
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="web-assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> Any:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="接口不存在")
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = WEB_DIST / "index.html"
        if index.exists():
            return FileResponse(
                index,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        raise HTTPException(status_code=404, detail="前端尚未构建")
else:
    @app.get("/")
    async def dev_root() -> JSONResponse:
        return JSONResponse({
            "message": "后端已启动，但前端还没构建。开发模式请运行 web 目录的 npm run dev；"
                       "生产模式请先 npm run build。",
            "api": "/api/health",
        })
