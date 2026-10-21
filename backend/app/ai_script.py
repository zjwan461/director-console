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


def clean(text) -> str:
    """content 可能是字符串，也可能是多模态返回的 [{"type":"text","text":...}] 列表。"""
    if isinstance(text, list):
        text = "".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in text
        )
    text = str(text or "").strip()
    text = re.sub(r"^```.*?\n|```$", "", text, flags=re.S).strip()
    text = text.strip("\"'“”‘’ ")
    text = re.sub(r"^(字幕|旁白)[:：]\s*", "", text)
    return re.sub(r"\s*\n+\s*", " ", text).strip()


DESC_KEYS = ("prompt", "description", "画面描述", "desc", "text", "scene")


def shot_description(shot: dict) -> str:
    """镜头描述可能在 shot.prompt，也可能在 values 的某个字段里。"""
    direct = str(shot.get("prompt") or "").strip()
    if direct:
        return direct
    values = shot.get("values") or {}
    if isinstance(values, dict):
        for key in DESC_KEYS:
            value = values.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


async def narration_matches(narration: str, description: str) -> bool:
    """让模型判断旁白和画面描述是否在说同一件事（跨语言）。"""
    api_key = str(settings.get("ai.api_key", "") or "")
    base = str(settings.get("ai.base_url", "")).rstrip("/")
    model = str(settings.get("ai.model", "") or "")
    if images:
        vision_model = str(settings.get("ai.vision_model", "") or "").strip()
        if not vision_model:
            raise ValueError("要带视频截图给 AI，需要先在提示词助手配置「多模态模型」")
        model = vision_model
    proxy = str(settings.get("ai.proxy", "") or "").strip()
    if not (api_key and base and description):
        return True
    kwargs: dict = {"timeout": httpx.Timeout(connect=10, read=60, write=20, pool=20), "trust_env": False}
    if proxy:
        kwargs["proxy"] = proxy
    prompt = (
        "判断下面两段内容是否在描述同一个画面/场景。"
        "只回答「是」或「否」，不要解释。\n\n"
        f"画面描述：{description[:1200]}\n\n旁白：{narration}"
    )
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.post(
                base + "/chat/completions",
                headers={"Authorization": "Bearer " + api_key},
                json={"model": model,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0, "stream": False},
            )
        if resp.status_code >= 400:
            return True
        text = resp.json()["choices"][0]["message"]["content"].strip()
        return not text.startswith("否")
    except Exception:
        return True


def fit_narration(narration: str, budget: int) -> dict:
    """字幕跟随旁白：不超预算就原样用，超了才压缩。"""
    text = clean(narration)
    return {
        "text": text if len(text) <= budget else text[:budget].rstrip("，。！？、,.!? "),
        "chars": min(len(text), budget),
        "budget": budget,
        "over": len(text) > budget,
        "compressed": len(text) > budget,
        "original_chars": len(text),
        "followed_narration": True,
    }


async def generate(kind: str, shot: dict, project: dict, neighbors: dict,
                   duration: float, style: dict, images: list[Path] | None = None) -> dict:
    prompts = _prompts()
    system = prompts.get(PROMPT_KEYS[kind])
    if not system:
        raise ValueError("缺少 AI 文案提示词模板（content/ai-prompts.json）")

    api_key = str(settings.get("ai.api_key", "") or "")
    if not api_key:
        raise ValueError("没有配置 ai.api_key")
    base = str(settings.get("ai.base_url", "")).rstrip("/")
    model = str(settings.get("ai.model", "") or "")
    if images:
        vision_model = str(settings.get("ai.vision_model", "") or "").strip()
        if not vision_model:
            raise ValueError("要带视频截图给 AI，需要先在提示词助手配置「多模态模型」")
        model = vision_model
    proxy = str(settings.get("ai.proxy", "") or "").strip()

    description = shot_description(shot)
    if not description:
        raise ValueError("这个镜头没有画面描述，AI 无法对照画面；请先在项目页填写「画面描述」")

    budget = char_budget(kind, duration)
    context = json.dumps({
                "kind": kind,
                "char_budget": budget,
                "duration_seconds": round(duration, 2),
                "style": style,
                "project": {"name": project.get("name", "")},
                "shot": {
                    "title": shot.get("title", ""),
                    "description": description,
                    "preset": shot.get("preset_id", ""),
                    "duration_seconds": round(duration, 2),
                },
                "neighbors": neighbors,
            }, ensure_ascii=False)
    user_content: list[dict] = [{"type": "text", "text": context}]
    for image in (images or []):
        import base64

        data = base64.b64encode(image.read_bytes()).decode()
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{data}"},
        })
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
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
    original_chars = len(text)
    compressed = False
    if len(text) > budget:
        # 超预算：让模型自己压缩一次，避免直接截断丢语义
        try:
            text = await _compress(client_factory(kwargs), base, api_key, model, system,
                                   text, budget, kind)
            compressed = True
        except Exception:
            pass
    if len(text) > budget:
        text = text[:budget].rstrip("，。！？、,.!? ")
    return {
        "text": text,
        "chars": len(text),
        "budget": budget,
        "over": len(text) > budget,
        "compressed": compressed,
        "original_chars": original_chars,
        "duration": round(duration, 2),
    }


def client_factory(kwargs: dict):
    return lambda: httpx.AsyncClient(**kwargs)


async def _compress(make_client, base: str, api_key: str, model: str,
                    system: str, text: str, budget: int, kind: str) -> str:
    instruction = (
        f"上一次输出是：{text}\n"
        f"它超过了 {budget} 字的预算。请压缩到 {budget} 字以内，保留原意和画面依据，"
        f"仍只输出一行正文，不要解释。"
    )
    async with make_client() as client:
        resp = await client.post(
            base + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": instruction},
                ],
                "temperature": 0.4,
                "stream": False,
            },
        )
    if resp.status_code >= 400:
        return text
    body = resp.json()
    try:
        return clean(body["choices"][0]["message"]["content"])
    except Exception:
        return text
