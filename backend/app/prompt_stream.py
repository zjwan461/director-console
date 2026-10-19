"""提示词助手：透传上游 OpenAI 兼容接口的 SSE。"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import settings

router = APIRouter()

MODES = {
    "t2v": "keyframeT2va",
    "i2v": "keyframeI2va",
    "flf2v": "keyframeFl2va",
    "r2v": "fullReference",
}


class RewriteRequest(BaseModel):
    mode: str = "t2v"
    brief: str
    extra: str = ""


def _skill_prompts() -> dict:
    path = Path(settings.paths["content"]) / "skill-prompt.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _error(message: str) -> str:
    body = json.dumps({"message": message}, ensure_ascii=False)
    return "event: error\\ndata: " + body + "\\n\\n"


@router.post("/api/prompt/rewrite/stream")
async def rewrite_stream(body: RewriteRequest):
    prompts = _skill_prompts()
    prompt_key = MODES.get(body.mode)
    if not prompt_key:
        raise HTTPException(status_code=400, detail="未知模式")
    system = prompts.get(prompt_key)
    if not system:
        raise HTTPException(status_code=400, detail="提示词系统模板缺失")
    api_key = str(settings.get("ai.api_key", "") or "")
    if not api_key:
        raise HTTPException(status_code=400, detail="没有配置 ai.api_key")

    base = str(settings.get("ai.base_url", "")).rstrip("/")
    model = settings.get("ai.model", "")
    text = body.brief + (("\\n\\n补充要求：" + body.extra) if body.extra else "")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0.7,
        "stream": True,
    }

    proxy = str(settings.get("ai.proxy", "") or "").strip()
    kwargs = {"timeout": httpx.Timeout(connect=15, read=300, write=30, pool=30), "trust_env": False}
    if proxy:
        kwargs["proxy"] = proxy
    elif settings.get("ai.trust_env", False):
        kwargs["trust_env"] = True

    async def gen():
        async with httpx.AsyncClient(**kwargs) as client:
            async with client.stream(
                "POST",
                base + "/chat/completions",
                headers={"Authorization": "Bearer " + api_key},
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body_text = (await resp.aread()).decode("utf-8", "replace")
                    yield _error("提示词模型返回 " + str(resp.status_code) + "：" + body_text[:300])
                    return
                async for chunk in resp.aiter_raw():
                    yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
