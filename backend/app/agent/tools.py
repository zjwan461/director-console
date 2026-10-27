"""M1 工具：环境探测、素材检索、提交图片生成、查任务。

设计约定
- 生成类工具是 async（要 await runner.enqueue）
- 返回 JSON 字符串（LangChain tool content 是文本）
- 关键动作只负责"提交"，不等结果
- 不抛异常给模型：失败也返回 {"ok": false, "error": ..., "hint": ...}
- inputs 存的是**语义值**（prompt / size{aspect,megapixels} / seed），
  由 presets.build_bindings 在提交时翻译成节点绑定
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from .. import store
from ..jobs import runner
from ..render import runner as render_runner
from ..presets import (build_bindings, get_card, is_video_card, load_cards, public_card,
                       size_from, validate)

IMAGE_CARD_ID = "image.c16"

# 视频模式 -> (能力卡, 必填的图片槽位)
VIDEO_CARDS = {
    "t2v": ("h3.t2v", ""),
    "i2v": ("h3.i2v", "first_frame"),
    "r2v": ("h3.r2v", "ref_1"),
    # 对口型：一张人像 + 一段音频
    "lipsync": ("h3.lipsync", "portrait"),
    # 九图多参考 + 配音：图片参考，可选参考音频
    "r2v9": ("h3.r2v9", "ref_1"),
}
VIDEO_MAX_DURATION = 15

ASPECT_RATIO: dict[str, tuple[int, int]] = {
    "16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1),
    "4:3": (4, 3), "3:4": (3, 4), "21:9": (21, 9), "3:2": (3, 2), "2:3": (2, 3),
}


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _card_field(card: dict, key: str) -> dict:
    for field in card.get("fields") or []:
        if field.get("key") == key:
            return field
    return {}


def default_megapixels(card: dict) -> float:
    field = _card_field(card, "size")
    return float(field.get("default_megapixels") or 1.0)


def build_values(card: dict, *, prompt: str, aspect: str, megapixels: float | None = None,
                 seed: int = -1) -> dict[str, Any]:
    """构造能力卡的语义值（不是节点绑定）。"""
    size_field = _card_field(card, "size")
    aspect = aspect if aspect in ASPECT_RATIO else str(size_field.get("default_aspect") or "16:9")
    mp = float(megapixels or size_field.get("default_megapixels") or 1.0)
    values: dict[str, Any] = {"prompt": str(prompt or "").strip()}
    if size_field:
        values["size"] = {"aspect": aspect, "megapixels": mp}
    if _card_field(card, "seed"):
        values["seed"] = int(seed)
    return values


def image_inputs_preview(prompt: str, aspect: str = "9:16", megapixels: float | None = None,
                         seed: int = -1) -> dict:
    """给确认卡用：算出最终输入与尺寸，不提交。"""
    card = get_card(IMAGE_CARD_ID) or {}
    if not card:
        return {"preset_id": IMAGE_CARD_ID, "params": {}, "binds": {},
                "errors": ["图片能力卡不存在"]}
    size_field = _card_field(card, "size")
    values = build_values(card, prompt=prompt, aspect=aspect, megapixels=megapixels, seed=seed)
    errors = validate(card, values)
    binds = build_bindings(card, values, {}) if not errors else {}
    aspect_used = values.get("size", {}).get("aspect")
    mp = values.get("size", {}).get("megapixels")
    width, height = size_from(aspect_used, mp) if aspect_used and mp else (0, 0)
    return {
        "preset_id": IMAGE_CARD_ID,
        "params": {
            "prompt": values["prompt"],
            "aspect": aspect_used,
            "megapixels": mp,
            "width": width,
            "height": height,
            "seed": values.get("seed", seed),
        },
        "megapixels_options": size_field.get("megapixels_options") or [1.0, 2.0],
        "binds": binds,
        "errors": errors,
    }


# --------------------------------------------------------------------------- #
# 只读
# --------------------------------------------------------------------------- #
def env_check() -> str:
    presets = []
    for card in load_cards():
        if not card.get("_workflow_exists"):
            continue
        public = public_card(card)
        presets.append({
            "id": public.get("id"),
            "name": public.get("name"),
            "category": public.get("category"),
            "output_kind": public.get("output_kind"),
        })
    card = get_card(IMAGE_CARD_ID) or {}
    size_field = _card_field(card, "size")
    return _dumps({
        "ok": True,
        "presets": presets,
        "image_card": IMAGE_CARD_ID,
        "image_card_name": card.get("name", ""),
        "aspects": list(ASPECT_RATIO.keys()),
        "default_aspect": size_field.get("default_aspect", "16:9"),
        "default_megapixels": default_megapixels(card) if card else 1.0,
        "megapixels_options": size_field.get("megapixels_options") or [],
    })


def list_assets(kind: str = "", q: str = "", purpose: str = "", limit: int = 10) -> str:
    limit = max(1, min(int(limit or 10), 30))
    items, total = store.search_assets(kind or None, q or "", limit, 0, purpose or None)
    out = [{
        "id": item["id"],
        "kind": item["kind"],
        "path": item["path"],
        "url": f"/media/files/{item['path']}",
        "purpose": (item.get("meta") or {}).get("purpose", ""),
        "width": item.get("width"),
        "height": item.get("height"),
        "size": item.get("size"),
    } for item in items]
    return _dumps({"ok": True, "total": total, "items": out})


def job_status(job_id: str) -> str:
    job = store.get_job(job_id)
    if not job:
        return _dumps({"ok": False, "error": "job_not_found",
                       "hint": f"没有 id 为 {job_id} 的任务"})
    outputs = job.get("outputs") or []
    return _dumps({
        "ok": True,
        "job_id": job["id"],
        "status": job["status"],
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "error": job.get("error", ""),
        "outputs": outputs if isinstance(outputs, list) else [],
    })


# --------------------------------------------------------------------------- #
# 写（确认后执行）
# --------------------------------------------------------------------------- #
async def make_image(prompt: str, aspect: str = "9:16", megapixels: float | None = None,
                     seed: int = -1) -> str:
    preview = image_inputs_preview(prompt, aspect, megapixels, seed)
    if preview["errors"]:
        return _dumps({"ok": False, "error": "invalid_params",
                       "hint": "；".join(preview["errors"])})
    card = get_card(IMAGE_CARD_ID)
    if not card:
        return _dumps({"ok": False, "error": "card_missing",
                       "hint": f"图片能力卡 {IMAGE_CARD_ID} 不存在"})

    values = build_values(card, prompt=prompt, aspect=aspect, megapixels=megapixels, seed=seed)
    job = store.create_job(IMAGE_CARD_ID, values, "", "")
    try:
        await runner.enqueue(job["id"])
    except Exception as exc:
        return _dumps({"ok": False, "error": "enqueue_failed", "hint": str(exc),
                       "job_id": job["id"]})
    return _dumps({
        "ok": True,
        "job_id": job["id"],
        "preset_id": IMAGE_CARD_ID,
        "params": preview["params"],
    })


# --------------------------------------------------------------------------- #
# 视频（M2）
# --------------------------------------------------------------------------- #
def _card_default(card: dict, key: str, fallback=None):
    field = _card_field(card, key)
    return field.get("default", fallback)


async def audio_seconds(asset_id: str) -> float:
    """读音频素材时长（有缓存用缓存，没有就 ffprobe 一次）。"""
    if not asset_id:
        return 0.0
    asset = store.get_asset(asset_id)
    if not asset:
        return 0.0
    cached = (asset.get("meta") or {}).get("duration")
    if cached:
        try:
            return float(cached)
        except (TypeError, ValueError):
            pass
    from .. import ffmpeg
    from ..config import settings

    target = pathlib.Path(settings.paths["data"]) / str(asset.get("path") or "")
    if not target.exists():
        return 0.0
    try:
        seconds = float(await ffmpeg.duration_of(target))
    except Exception:
        return 0.0
    return round(seconds, 2)


def video_inputs_preview(prompt: str, mode: str = "t2v", aspect: str = "16:9",
                         duration: float | None = None,
                         image_asset_id: str = "",
                         megapixels: float | None = None,
                         audio_asset_id: str = "",
                         audio_asset_ids: list[str] | None = None) -> dict:
    """给确认卡用：算视频参数，不提交。"""
    card_id, image_slot = VIDEO_CARDS.get(mode, VIDEO_CARDS["t2v"])
    card = get_card(card_id)
    if not card:
        return {"preset_id": card_id, "errors": [f"能力卡 {card_id} 不存在"]}

    size_field = _card_field(card, "size")
    aspect = aspect if aspect in ASPECT_RATIO else str(size_field.get("default_aspect") or "16:9")
    mp = float(megapixels or size_field.get("default_megapixels") or 0.4)
    seconds = float(duration or _card_default(card, "duration", 5))
    lo = float(_card_field(card, "duration").get("min", 1))
    hi = float(_card_field(card, "duration").get("max", VIDEO_MAX_DURATION))
    seconds = max(lo, min(hi, seconds))

    values: dict[str, Any] = {
        "prompt": str(prompt or "").strip(),
        "size": {"aspect": aspect, "megapixels": mp},
        "duration": seconds,
    }
    if image_slot:
        values[image_slot] = image_asset_id or ""

    # 音频参考：卡片上的 audio 类字段依次填充（对口型 audio，九图 audio_1/2/3）
    audio_slots = [str(f.get("key")) for f in (card.get("fields") or [])
                   if str(f.get("type")) == "audio" and f.get("key")]
    supplied = [aid for aid in ((audio_asset_ids or []) or ([audio_asset_id] if audio_asset_id else []))
                if aid]
    for slot, aid in zip(audio_slots, supplied):
        values[slot] = aid
    for slot in audio_slots[len(supplied):]:
        values.setdefault(slot, "")
    audio_slot = audio_slots[0] if audio_slots else ""

    errors = validate(card, values)
    width, height = size_from(aspect, mp) if aspect else (0, 0)
    return {
        "preset_id": card_id,
        "mode": mode,
        "params": {
            "prompt": values["prompt"],
            "aspect": aspect,
            "duration": seconds,
            "megapixels": mp,
            "width": width,
            "height": height,
            "image_asset_id": image_asset_id,
            "audio_asset_id": supplied[0] if supplied else "",
            "audio_asset_ids": supplied,
            "audio_slot": audio_slot,
        },
        "megapixels_options": size_field.get("megapixels_options") or [0.4, 0.8],
        "values": values,
        "errors": errors,
    }


async def make_video(prompt: str, mode: str = "t2v", aspect: str = "16:9",
                     duration: float | None = None, image_asset_id: str = "",
                     megapixels: float | None = None,
                     audio_asset_id: str = "",
                     audio_asset_ids: list[str] | None = None) -> str:
    preview = video_inputs_preview(prompt, mode, aspect, duration, image_asset_id,
                                   megapixels, audio_asset_id, audio_asset_ids)
    if preview["errors"]:
        return _dumps({"ok": False, "error": "invalid_params",
                       "hint": "；".join(preview["errors"])})
    card_id = preview["preset_id"]
    job = store.create_job(card_id, preview["values"], "", "")
    try:
        await runner.enqueue(job["id"])
    except Exception as exc:
        return _dumps({"ok": False, "error": "enqueue_failed", "hint": str(exc),
                       "job_id": job["id"]})
    return _dumps({"ok": True, "job_id": job["id"], "preset_id": card_id,
                   "params": preview["params"]})


# --------------------------------------------------------------------------- #
# 成片导出（M2b）
# --------------------------------------------------------------------------- #
QUALITY = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "480p": (854, 480),
    "竖屏1080": (1080, 1920),
    "竖屏720": (720, 1280),
}


def _edit_state(project_id: str) -> dict:
    import json as _json

    raw = store.get_setting(f"edit_state.{project_id}", "")
    try:
        data = _json.loads(raw) if raw else {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def export_preview(project_id: str, quality: str = "1080p") -> dict:
    """给确认卡用：项目的镜头数、分辨率、预估时长。"""
    shots = store.list_shots(project_id)
    if not shots:
        return {"ok": False, "errors": ["项目里还没有镜头"]}
    width, height = QUALITY.get(quality, QUALITY["1080p"])
    state = _edit_state(project_id)
    options = state.get("options") or {}
    edits = {str(e.get("shot_id")): e for e in (state.get("shot_edits") or []) if e.get("shot_id")}

    title = options.get("title") or {}
    tail = options.get("tail") or {}
    total = 0.0
    for shot in shots:
        edit = edits.get(shot["id"], {})
        out_point = float(edit.get("out_point") or 0)
        in_point = float(edit.get("in_point") or 0)
        speed = float(edit.get("speed") or 1) or 1
        if out_point > in_point:
            total += (out_point - in_point) / speed
    return {
        "ok": True,
        "project_id": project_id,
        "shots": len(shots),
        "width": width,
        "height": height,
        "quality": quality,
        "subtitles": bool((options.get("subtitles") or {}).get("enabled")),
        "bgm": len(options.get("bgm_tracks") or []),
        "title_seconds": round(float(title.get("duration") or 0), 1) if title.get("enabled") else 0.0,
        "title_text": str(title.get("text") or ""),
        "tail_seconds": round(float(tail.get("duration") or 0), 1) if tail.get("enabled") else 0.0,
        "tail_text": str(tail.get("text") or ""),
        "approx_seconds": round(total, 1),
        "eta": max(30, int(total * 3)),
    }


async def make_film(project_id: str, quality: str = "1080p") -> str:
    """按剪辑页的状态导出成片（全部镜头）。"""
    preview = export_preview(project_id, quality)
    if not preview.get("ok"):
        return _dumps({"ok": False, "error": "no_shots", "hint": "；".join(preview.get("errors") or [])})

    shots = store.list_shots(project_id)
    shot_ids = [s["id"] for s in shots]
    state = _edit_state(project_id)
    options = dict(state.get("options") or {})
    options["width"], options["height"] = preview["width"], preview["height"]
    options.setdefault("fps", 24)
    options.pop("preview", None)
    options.pop("cache_key", None)

    render = store.create_render(project_id, shot_ids, options)
    edits = [e for e in (state.get("shot_edits") or []) if e.get("shot_id") in set(shot_ids)]
    if edits:
        store.save_render_shots(render["id"], edits)
    try:
        await render_runner.enqueue(render["id"])
    except Exception as exc:
        return _dumps({"ok": False, "error": "enqueue_failed", "hint": str(exc),
                       "render_id": render["id"]})
    return _dumps({"ok": True, "render_id": render["id"], "params": preview})


# --------------------------------------------------------------------------- #
# 产物 → 镜头
# --------------------------------------------------------------------------- #
async def save_as_shot(job_id: str, project_id: str, title: str = "") -> str:
    job = store.get_job(job_id)
    if not job:
        return _dumps({"ok": False, "error": "job_not_found", "hint": "任务不存在"})
    if job.get("status") != "succeeded":
        return _dumps({"ok": False, "error": "not_finished", "hint": "任务还没成功，先等等"})
    if job.get("shot_id"):
        return _dumps({"ok": False, "error": "already_shot",
                       "hint": f"这个任务已经是镜头 {job['shot_id']} 了"})
    if not store.get_project(project_id):
        return _dumps({"ok": False, "error": "project_missing", "hint": "项目不存在"})
    card = get_card(job.get("preset_id") or "")
    if card and not is_video_card(card):
        return _dumps({"ok": False, "error": "image_card",
                       "hint": "这是图片卡生成的结果，不能直接存成镜头；可以把它当视频卡的首帧"})

    shot = store.create_shot(project_id, title or f"镜头 {len(store.list_shots(project_id)) + 1}",
                             job.get("preset_id") or "")
    store.update_shot(shot["id"], values=job.get("inputs") or {})
    store.update_job(job_id, project_id=project_id, shot_id=shot["id"])
    updated = store.get_job(job_id)
    if updated and updated.get("outputs"):
        try:
            await runner._attach_last_frame(updated, updated["outputs"])
        except Exception:
            pass
    return _dumps({"ok": True, "shot_id": shot["id"],
                   "title": title or "新镜头", "project_id": project_id})


# --------------------------------------------------------------------------- #
# 剪辑侧（P1）：AI 剪辑 / 配乐 / 成片设置
# --------------------------------------------------------------------------- #
def polish_preview(project_id: str, kinds: str = "both", tts: bool = True,
                   titles: bool = True) -> dict:
    shots = store.list_shots(project_id)
    return {
        "ok": True,
        "project_id": project_id,
        "shots": len(shots),
        "kinds": kinds,
        "tts": bool(tts),
        "titles": bool(titles),
        "eta": max(30, len(shots) * 25),
    }


async def polish_film(project_id: str, kinds: str = "both", tts: bool = True,
                      titles: bool = True, rewrite: bool = False) -> str:
    """调服务端 AI 剪辑：写旁白 / 字幕 / 配音 / 调速 / 片头片尾。"""
    from .. import ai_edit

    if not store.list_shots(project_id):
        return _dumps({"ok": False, "error": "no_shots", "hint": "项目里还没有镜头"})
    run = await ai_edit.start(project_id, [], {
        "kind": kinds,
        "mode": "rewrite" if rewrite else "fill",
        "tts": tts,
        "auto_speed": tts,
        "titles": titles,
        "frames": 0,
    })
    return _dumps({"ok": True, "edit_run_id": run["id"],
                   "preview": polish_preview(project_id, kinds, tts, titles)})


def bgm_preview(project_id: str, mode: str = "auto", query: str = "",
                asset_id: str = "") -> dict:
    """配乐预演：auto=按段落自动挑；asset=按关键词找一首；off=关闭。"""
    music = [a for a in store.list_assets("audio", 200)
             if str((a.get("meta") or {}).get("purpose") or "") == "music"
             or "/music/" in str(a.get("path") or "")]
    picked = None
    if mode == "asset":
        if asset_id:
            # 用户上传的音频 / 手动指定的那条素材，优先于关键词匹配
            picked = store.get_asset(asset_id)
        if picked is None and query:
            picked = next((a for a in music
                           if query.lower() in str(a.get("path", "")).lower()), None)
        picked = picked or (music[0] if music else None)
    return {
        "ok": bool(music) or mode == "off",
        "project_id": project_id,
        "mode": mode,
        "query": query,
        "music_count": len(music),
        "picked": ({"id": picked["id"], "name": str(picked["path"]).rsplit("/", 1)[-1]}
                   if picked else None),
        "errors": [] if (music or mode == "off") else ["素材库里还没有背景音乐"],
    }


async def set_bgm(project_id: str, mode: str = "auto", query: str = "",
                  asset_id: str = "") -> str:
    """写入 bgm_tracks：auto 走按段落配乐，asset 选一首，off 清空。"""
    state = _edit_state(project_id)
    options = dict(state.get("options") or {})

    if mode == "off":
        options["bgm_tracks"] = []
        _save_edit_options(project_id, state, options)
        return _dumps({"ok": True, "mode": "off", "tracks": 0})

    if mode == "asset":
        preview = bgm_preview(project_id, "asset", query, asset_id)
        if not preview.get("ok") or not preview.get("picked"):
            return _dumps({"ok": False, "error": "no_music",
                           "hint": "；".join(preview.get("errors") or ["没有可用音乐"])})
        has_narration = any(bool((e or {}).get("narration_on"))
                            for e in (state.get("shot_edits") or []))
        track = {
            "id": f"t{int(__import__('time').time())}",
            "asset_id": preview["picked"]["id"],
            "volume_db": -18 if has_narration else -12,
            "start": 0, "end": None, "fade_in": 1, "fade_out": 2, "loop": True,
        }
        options["bgm_tracks"] = [track]
        _save_edit_options(project_id, state, options)
        return _dumps({"ok": True, "mode": "asset", "track": track,
                       "name": preview["picked"]["name"]})

    # auto：复用 /api/ai/bgm-plan 的选曲逻辑
    from ..main import TitleRequest, ai_bgm_plan

    plan = await ai_bgm_plan(TitleRequest(project_id=project_id))
    options["bgm_tracks"] = plan.get("tracks") or []
    _save_edit_options(project_id, state, options)
    return _dumps({"ok": True, "mode": "auto", "tracks": len(options["bgm_tracks"]),
                   "notes": plan.get("notes") or []})


def _save_edit_options(project_id: str, state: dict, options: dict) -> None:
    state = dict(state)
    state["options"] = options
    store.set_setting(f"edit_state.{project_id}", __import__("json").dumps(state, ensure_ascii=False))


def film_options_preview(project_id: str, transition: str = "", title: str = "",
                         tail: str = "", aspect: str = "") -> dict:
    state = _edit_state(project_id)
    options = dict(state.get("options") or {})
    current_transition = (options.get("transition") or {}).get("type") or "dissolve"
    return {
        "ok": True,
        "project_id": project_id,
        "transition": transition or current_transition,
        "title": title,
        "tail": tail,
        "aspect": aspect,
    }


async def set_film_options(project_id: str, transition: str = "", title: str = "",
                           tail: str = "", aspect: str = "") -> str:
    state = _edit_state(project_id)
    options = dict(state.get("options") or {})
    changed = []

    if transition:
        options["transition"] = {"type": transition,
                                 "duration": (options.get("transition") or {}).get("duration", 0.4)}
        changed.append(f"转场 {transition}")
    if title:
        options["title"] = {**(options.get("title") or {}), "text": title, "enabled": True}
        changed.append(f"片头《{title}》")
    if tail:
        options["tail"] = {**(options.get("tail") or {}), "text": tail, "enabled": True}
        changed.append(f"片尾《{tail}》")
    if aspect:
        width, height = (1080, 1920) if aspect.startswith("9:16") else (1920, 1080)
        options["width"], options["height"] = width, height
        changed.append(f"画幅 {aspect}")

    _save_edit_options(project_id, state, options)
    return _dumps({"ok": True, "changed": changed})


def rel_from_url(url: str) -> str:
    """把 /media/xxx/yyy 转成相对 data 的路径（三段前缀显式处理）。"""
    url = (url or "").strip()
    for prefix, root in (("/media/files/", ""), ("/media/outputs/", "outputs/"),
                         ("/media/uploads/", "uploads/")):
        if url.startswith(prefix):
            rest = url[len(prefix):]
            return f"{root}{rest}" if root else rest
    return ""


def asset_from_url(url: str, job_id: str = "") -> str:
    """把产物 URL 登记成素材，返回 asset_id（失败返回空串）。"""
    rel = rel_from_url(url)
    if not rel:
        return ""
    try:
        asset = store.get_asset_by_path(rel) or store.add_asset(
            "image", rel, meta={"origin": "agent", "job_id": job_id})
        return asset["id"] if asset else ""
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# 从零开始：建项目 / 加镜头
# --------------------------------------------------------------------------- #
def create_project(name: str) -> str:
    """建一个项目，并给它开一个会话（一会话一项目）。"""
    name = (name or "").strip()[:40] or "未命名项目"
    if store.list_projects() and any(p.get("name") == name for p in store.list_projects()):
        name = f"{name} 2"
    project = store.create_project(name)
    from . import store as agent_store

    thread = agent_store.create_thread(project["id"], name)
    return _dumps({"ok": True, "project_id": project["id"], "project_name": name,
                   "thread_id": thread["id"]})


def add_shot_preview(project_id: str, titles: list[str] | None = None) -> dict:
    shots = store.list_shots(project_id)
    return {"ok": True, "project_id": project_id, "existing": len(shots),
            "titles": titles or []}


async def add_shots(project_id: str, prompts: list[str]) -> str:
    """按顺序加几个镜头（每个 prompt 一镜，默认用文生视频卡）。"""
    if not store.get_project(project_id):
        return _dumps({"ok": False, "error": "project_missing", "hint": "项目不存在"})
    prompts = [str(p).strip() for p in (prompts or []) if str(p).strip()][:8]
    if not prompts:
        return _dumps({"ok": False, "error": "empty", "hint": "没有提供镜头画面描述"})

    created = []
    base = len(store.list_shots(project_id))
    for index, prompt in enumerate(prompts, start=1):
        shot = store.create_shot(project_id, f"镜头 {base + index}", "h3.t2v", prompt)
        store.update_shot(shot["id"], values={"prompt": prompt,
                                              "size": {"aspect": "16:9", "megapixels": 0.4},
                                              "duration": 5})
        created.append({"id": shot["id"], "title": f"镜头 {base + index}", "prompt": prompt})
    return _dumps({"ok": True, "created": created, "count": len(created)})


# --------------------------------------------------------------------------- #
# 修订：在上一版基础上改参数（Step 1）
# --------------------------------------------------------------------------- #
def _revision_params(target: dict, patch: dict) -> dict:
    base = dict(target.get("params") or {})
    prompt = str(base.get("prompt") or target.get("prompt") or "")
    # 历史数据里可能把文件路径存成了 prompt，这里挡一下
    if prompt.startswith(("uploads/", "outputs/")) or prompt.endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".wav")):
        prompt = ""
    suffix = str(patch.get("prompt_suffix") or "")
    if suffix:
        prompt = f"{prompt}，{suffix}" if prompt else suffix
    params = {
        "prompt": prompt,
        "aspect": patch.get("aspect") or base.get("aspect") or "9:16",
        "megapixels": patch.get("megapixels") or base.get("megapixels"),
        "duration": patch.get("duration") or base.get("duration") or 5,
        "mode": base.get("mode") or "t2v",
        "image_asset_id": base.get("image_asset_id") or "",
        "seed": base.get("seed", -1),
        "parent_ref": target.get("ref"),
        "note": f"基于 #{target.get('ref')}：{patch.get('prompt_suffix') or '参数调整'}",
    }
    return params


def revise_preview(thread_id: str, project_id: str, text: str) -> dict:
    from . import state as agent_state

    resolved = agent_state.resolve(text, thread_id, project_id)
    if resolved.get("ambiguous"):
        names = "、".join(f"#{a['ref']}" for a in resolved["ambiguous"][:4])
        return {"ok": False, "hint": f"你说的可能是 {names}，告诉我是第几个"}
    target = resolved.get("target")
    if not target:
        return {"ok": False, "hint": resolved.get("error") or "没找到要改的那一版"}

    if target.get("type") == "shot":
        return {"ok": False, "hint": "镜头不能直接改，先让我按这个镜头出一版，再改那一版"}

    patch = agent_state.build_patch(text)
    if not patch and not agent_state.SUBJECTIVE_RE.search(text):
        return {"ok": False, "hint": "没听出要改什么，可以说「再亮一点」「时长改成 8 秒」「换成竖屏」"}

    params = _revision_params(target, patch)
    kind = target.get("kind") or "image"
    return {
        "ok": True,
        "base_ref": target["ref"],
        "base_kind": kind,
        "base_url": target.get("url") or "",
        "patch": patch,
        "params": params,
        "summary": agent_state.describe_patch(patch, target),
        "how": resolved.get("how") or "",
        "eta": 200 if kind == "video" else 40,
    }


async def make_revision(thread_id: str, project_id: str, text: str) -> str:
    preview = revise_preview(thread_id, project_id, text)
    if not preview.get("ok"):
        return _dumps(preview)
    params = preview["params"]
    if preview["base_kind"] == "video":
        raw = await make_video(params["prompt"], params["mode"], params["aspect"],
                               params["duration"], params.get("image_asset_id") or "",
                               params.get("megapixels"))
    else:
        raw = await make_image(params["prompt"], params["aspect"], params.get("megapixels"),
                               int(params.get("seed") or -1))
    data = json.loads(raw)
    data["revision"] = preview
    data["params"] = params
    return _dumps(data)


DEFAULT_MOTION_PROMPT = "让这张图动起来：人物轻微呼吸与发丝摆动，镜头缓慢推近"

MOTION_INSTRUCTION = """这是视频首帧。请为它写一条「图生视频」的运镜提示词：
- 中文，一到两句，40 字以内
- 描述画面里**实际有的主体在怎么动**（人物动作、表情、动物姿态、光线、雪/雨/烟等）
- 加一个镜头运动（推/拉/摇/移/环绕），不要写画面里不存在的东西
- 直接输出提示词本身，不要引号、不要解释"""


async def image_b64(asset_id: str) -> tuple[str, str]:
    """读素材图片成 (mime, base64)。"""
    import base64

    asset = store.get_asset(asset_id)
    if not asset:
        return ("", "")
    from ..config import settings

    path = pathlib.Path(settings.paths["data"]) / str(asset.get("path") or "")
    if not path.exists():
        return ("", "")
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
    return (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


async def motion_prompt(asset_id: str, user_text: str = "") -> str:
    """用多模态模型看图写运镜提示词；输出太短就重试，仍不行才退回默认值。"""
    from .. import llm

    mime, b64 = await image_b64(asset_id)
    if not b64:
        return DEFAULT_MOTION_PROMPT
    hint = f"\n用户补充：{user_text.strip()[:80]}" if user_text.strip() else ""

    def usable(value: str) -> bool:
        text = value.strip().strip('"“”').strip()
        # 太短 / 只有颜色词 / 没有动作或镜头，都算不合格
        if len(text) < 10:
            return False
        if not any(word in text for word in ("镜头", "推", "拉", "摇", "移", "环绕", "动", "呼吸", "飘", "转")):
            return False
        return True

    for attempt in range(2):
        instruction = MOTION_INSTRUCTION + hint
        if attempt == 1:
            instruction += "\n（要求：至少 20 个字，必须包含主体动作和一个镜头运动）"
        try:
            text = await llm.chat_vision([(mime, b64)], instruction)
        except Exception:
            continue
        if usable(text):
            return text.strip().strip('"“”')[:200]

    return DEFAULT_MOTION_PROMPT


VISION_PATCH_INSTRUCTION = """这是要修改的一张图。用户的要求是：{request}

请给出**具体可执行的修改描述**（中文，一句话，40 字内），要求：
- 只描述怎么改，不要复述用户原话
- 如果是改画幅（{aspect}），说明构图如何调整（例如「人物保持在画面右侧，左侧延伸雪地场景」）
- 如果用户说的是主观评价（太乱/太暗/不好看），把它翻译成可执行画面调整（减少背景元素/提高曝光/统一色调）
- 直接输出这一句话，不要引号、不要解释"""


async def vision_patch(asset_id: str, request: str, aspect: str = "") -> str:
    """看图把模糊要求翻译成具体改动；失败返回空串，由调用方退回关键词方案。"""
    from .. import llm

    mime, b64 = await image_b64(asset_id)
    if not b64:
        return ""
    instruction = VISION_PATCH_INSTRUCTION.format(
        request=(request or "").strip()[:120] or "让画面更好看",
        aspect=aspect or "保持原画幅")
    for attempt in range(2):
        try:
            text = await llm.chat_vision([(mime, b64)], instruction, max_tokens=600)
        except Exception:
            continue
        text = text.strip().strip('"“”').strip()
        if len(text) >= 6:
            return text[:160]
    return ""


BRIEF_INSTRUCTION = """用户给的题材是「{topic}」。请把它写成一条可直接用于文生视频的画面描述：
- 中文，40~70 字，一到两句
- 包含：场景地点、主体与动作、光线/天气、镜头景别
- 不要出现「用户」「题材」「视频」这些词，不要引号，不要解释
- 只输出画面描述本身"""


async def expand_brief(topic: str) -> str:
    """把「生化危机」这种题材扩写成可拍的画面描述。"""
    from .. import llm

    topic = (topic or "").strip()
    if not topic:
        return ""
    try:
        result = await llm.chat_once(
            [{"role": "user", "content": BRIEF_INSTRUCTION.format(topic=topic[:40])}],
            temperature=0.7, max_tokens=600)
    except Exception:
        return ""
    text = str(result.get("content") or "").strip().strip('"“”').strip()
    if len(text) < 12:
        return ""
    return text[:200]


OPTIMIZE_INSTRUCTION = """把用户的诉求写成一条可直接用于视频生成的提示词。

用户说：{request}
{reference}

要求：
- 中文，40~70 字，一到两句
- 包含：主体与动作、场景环境、光线氛围、景别或运镜
- 不要出现「用户」「提示词」「视频」这些词，不要引号，不要解释
- 如果有参考图，必须以图里的实际内容为主体
- 只输出提示词本身"""


async def optimize_prompt(request: str, asset_id: str = "") -> str:
    """AI 优化提示词：有参考图就结合图，没有就纯文本扩写。"""
    from .. import llm

    request = (request or "").strip()
    if not request:
        return ""
    reference = ""
    images: list[tuple[str, str]] = []
    if asset_id:
        mime, b64 = await image_b64(asset_id)
        if b64:
            images.append((mime, b64))
            reference = "（附带一张参考图，请以图中的主体、服装、场景为准）"

    instruction = OPTIMIZE_INSTRUCTION.format(request=request[:120], reference=reference)
    for attempt in range(2):
        try:
            if images:
                text = await llm.chat_vision(images, instruction, max_tokens=700)
            else:
                result = await llm.chat_once([{"role": "user", "content": instruction}],
                                             temperature=0.6, max_tokens=700)
                text = str(result.get("content") or "")
        except Exception:
            continue
        text = text.strip().strip('"“”').strip()
        if len(text) >= 12:
            return text[:220]
    return ""
