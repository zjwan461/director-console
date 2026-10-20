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
from . import ffmpeg
from .render import runner as render_runner
from .comfy import ComfyError, make_client, probe
from .config import settings
from .jobs import runner
from .launcher import LaunchError, get_launcher
from .presets import default_values, get_card, load_cards, public_card, validate
from .prompt_stream import router as prompt_stream_router
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
    runner.start()
    render_runner.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await runner.stop()
    await render_runner.stop()


# ---------------------------------------------------------------- 基础
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
    time.sleep(1)
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
async def upload_asset(file: UploadFile = File(...), kind: str = Form("image")) -> dict:
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
    asset = store.add_asset(kind, rel, size=size, width=width, height=height,
                            meta={"origin_name": file.filename})
    asset["url"] = f"/media/files/{rel}"
    return asset


@app.get("/api/assets/{asset_id}")
async def asset_detail(asset_id: str) -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    asset["url"] = f"/media/files/{asset['path']}"
    return asset


@app.get("/api/assets")
async def assets(kind: str | None = None, limit: int = 100) -> dict:
    items = store.list_assets(kind, limit)
    for item in items:
        item["url"] = f"/media/files/{item['path']}"
    return {"items": items}


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


@app.post("/api/shots")
async def create_shot(body: ShotCreate) -> dict:
    if not store.get_project(body.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
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


@app.get("/api/shots/{shot_id}/takes")
async def shot_takes(shot_id: str, limit: int = 12) -> dict:
    return {"items": store.list_jobs_by_shot(shot_id, limit)}


# ---------------------------------------------------------------- 成片导出
def _enrich_render(render: dict) -> dict:
    if render.get("output_path"):
        render["output_url"] = f"/media/files/{render['output_path']}"
        render["download_name"] = Path(render["output_path"]).name
    if render.get("cover_path"):
        render["cover_url"] = f"/media/files/{render['cover_path']}"
    return render


class RenderCreate(BaseModel):
    shot_ids: list[str] = []
    options: dict[str, Any] = {}


@app.get("/api/ffmpeg/status")
async def ffmpeg_status() -> dict:
    return ffmpeg.status()


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
    }
    if options["width"] < 64 or options["height"] < 64:
        raise HTTPException(status_code=400, detail="分辨率太小")
    if not ffmpeg.status()["available"]:
        raise HTTPException(status_code=400, detail=ffmpeg.status()["hint"])
    render = store.create_render(project_id, shot_ids, options)
    await render_runner.enqueue(render["id"])
    return _enrich_render(render)


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
