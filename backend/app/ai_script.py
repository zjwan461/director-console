"""AI 剪辑文案：按镜头生成字幕 / 旁白。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from .config import settings

PROMPT_KEYS = {"subtitle": "subtitleGen", "narration": "narrationGen"}


def _prompts() -> dict:
    path = Path(settings.paths["content"]) / "ai-prompts.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def char_budget(kind: str, duration: float) -> int:
    duration = max(duration, 1.0)
    if kind == "subtitle":
        return max(8, min(int(duration * 4.5), 60))
    return max(10, min(int(duration * 4.0), 90))


def clean(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```.*?\n|```$", "", text, flags=re.S).strip()
    text = text.strip("\"'“”‘’ ")
    text = re.sub(r"^(字幕|旁白)[:：]\s*", "", text)
    return re.sub(r"\s*\n+\s*", " ", text).strip()


async def generate(kind: str, shot: dict, project: dict, neighbors: dict,
                   duration: float, style: dict) -> dict:
    prompts = _prompts()
    system = prompts.get(PROMPT_KEYS[kind])
    if not system:
        raise ValueError("缺少 AI 文案提示词模板（content/ai-prompts.json）")

    api_key = str(settings.get("ai.api_key", "") or "")
    if not api_key:
        raise ValueError("没有配置 ai.api_key")
    base = str(settings.get("ai.base_url", "")).rstrip("/")
    model = str(settings.get("ai.model", "") or "")
    proxy = str(settings.get("ai.proxy", "") or "").strip()

    budget = char_budget(kind, duration)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({
                "kind": kind,
                "char_budget": budget,
                "duration_seconds": round(duration, 2),
                "style": style,
                "project": {"name": project.get("name", "")},
                "shot": {
                    "title": shot.get("title", ""),
                    "description": shot.get("prompt", ""),
                    "preset": shot.get("preset_id", ""),
                },
                "neighbors": neighbors,
            }, ensure_ascii=False)},
        ],
        "temperature": 0.6,
        "stream": False,
    }

    kwargs: dict = {"timeout": httpx.Timeout(connect=15, read=120, write=30, pool=30), "trust_env": False}
    if proxy:
        kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.post(
            base + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key},
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"文案模型返回 {resp.status_code}：{resp.text[:300]}")
    body = resp.json()
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("文案模型返回格式异常")
    text = clean(text)
    return {
        "text": text,
        "chars": len(text),
        "budget": budget,
        "over": len(text) > budget,
        "duration": round(duration, 2),
    }
