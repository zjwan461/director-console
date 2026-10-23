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


SHOT_SECTION_RE = re.compile(
    r"^\s*\[Shot\s*\d+\]\s*(.+?)(?=^\s*\[Shot\s*\d+\]|^\s*[a-z][a-z_]{3,}\s*:|\Z)",
    re.S | re.M,
)
SUMMARY_RE = re.compile(
    r"^\s*summary\s*[:：]\s*(.+?)(?=^\s*[a-z][a-z_]{3,}\s*:|\Z)", re.S | re.M,
)
MARKUP_RE = re.compile(r"</?(?:Picture|Subject|Video|Image)\s*\d*>", re.I)

# 压缩后的描述上限（字符）
COMPACT_LIMIT = 320


def compact_description(raw: str) -> str:
    """把「视频生成提示词」压成给人看的画面说明。

    这类 prompt 常带 subject_definitions / retention_analysis /
    overall_soundscape 等工程字段，对写旁白没帮助，还会稀释信息。
    优先取 [Shot N] 正文段落，其次 summary，最后退回清洗后的正文。
    """
    if not (raw or "").strip():
        return ""
    # 占位符换成可读词，避免“framing , in a ...”这种残缺
    text = re.sub(r"</?Picture\s*\d*>", "首帧", raw, flags=re.I)
    text = re.sub(r"</?Subject\s*\d*>", "主角", text, flags=re.I)
    text = MARKUP_RE.sub("", text).replace("\r", "")

    candidates: list[str] = []
    for match in SHOT_SECTION_RE.finditer(text):
        candidates.append(match.group(1))
    summary = SUMMARY_RE.search(text)
    if summary:
        candidates.append(summary.group(1))
    # 兜底：去掉工程字段标题，保留正文
    stripped = re.sub(r"^\s*[a-z][a-z_]{3,}\s*:\s*$", "", text, flags=re.M | re.I)
    candidates.append(stripped)

    for chunk in candidates:
        cleaned = re.sub(r"\s+", " ", chunk).strip(" \n:：-")
        cleaned = re.sub(r"^(?:keyframe completion|continues from)\s*", "", cleaned, flags=re.I)
        # 明显是工程术语的整段跳过
        if re.search(r"fully_preserved|partially_preserved|not_preserved", cleaned[:80]):
            continue
        if len(cleaned) >= 12:
            return cleaned[:COMPACT_LIMIT].rstrip(" ,，。")

    return re.sub(r"\s+", " ", text).strip()[:COMPACT_LIMIT]


async def narration_matches(narration: str, description: str) -> bool:
    """让模型判断旁白和画面描述是否在说同一件事（跨语言）。"""
    api_key = str(settings.get("ai.api_key", "") or "")
    base = str(settings.get("ai.base_url", "")).rstrip("/")
    model = str(settings.get("ai.model", "") or "")
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


def build_prompt(kind: str, shot: dict, project: dict, neighbors: dict,
                 duration: float, style: dict) -> tuple[str, str]:
    """返回 (system, user_text)，用于「AI 提示词弹框」的预览与编辑。"""
    prompts = _prompts()
    system = prompts.get(PROMPT_KEYS[kind])
    if not system:
        raise ValueError("缺少 AI 文案提示词模板（content/ai-prompts.json）")
    raw_description = shot_description(shot)
    if not raw_description:
        raise ValueError("这个镜头没有画面描述，AI 无法对照画面；请先在项目页填写「画面描述」")
    description = compact_description(raw_description)
    budget = char_budget(kind, duration)
    narration_style = dict(style or {})
    if kind == "narration":
        narration_style["language"] = "zh"
        narration_style["narration_language"] = "zh"
    user_text = json.dumps({
        "kind": kind,
        "char_budget": budget,
        "duration_seconds": round(duration, 2),
        "style": narration_style,
        "language_rule": "旁白只写中文，不要出现英文单词或英文句子" if kind == "narration" else "",
        "project": {"name": project.get("name", "")},
        "shot": {
            "title": shot.get("title", ""),
            "description": description,
            "preset": shot.get("preset_id", ""),
            "duration_seconds": round(duration, 2),
        },
        "neighbors": neighbors,
    }, ensure_ascii=False)
    return system, user_text


async def generate(kind: str, shot: dict, project: dict, neighbors: dict,
                   duration: float, style: dict, images: list[Path] | None = None,
                   system_override: str | None = None,
                   user_override: str | None = None) -> dict:
    system, context = build_prompt(kind, shot, project, neighbors, duration, style)
    if system_override and system_override.strip():
        system = system_override.strip()
    if user_override and user_override.strip():
        context = user_override.strip()

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
    budget = char_budget(kind, duration)

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


def build_title_prompt(project: dict, shots: list[dict], kind: str = "title") -> tuple[str, str]:
    """片头/片尾提示词，供弹框预览和编辑。"""
    prompts = _prompts()
    system = prompts.get("titleGen")
    if not system:
        raise ValueError("缺少片名提示词模板（content/ai-prompts.json）")
    if kind == "tail":
        task = ("本次任务：只写【片尾】文案。形如「第一集 · 完」或「下一集，雪夜归人」。"
                "不要写成片名，不要加解释，不要引号。")
    else:
        task = ("本次任务：只写【片头】片名。4~10 个汉字，有画面感。"
                "严禁出现「完」「本集」「第一集」「下一集」这类收尾字样，不要加解释，不要引号。")
    user = task + "\n\n" + json.dumps({
        "kind": kind,
        "project": project.get("name", ""),
        "shots": [
            {"title": s.get("title", ""), "description": shot_description(s)[:80]}
            for s in shots[:8]
        ],
    }, ensure_ascii=False)
    return system, user


async def title_for(project: dict, shots: list[dict], kind: str = "title",
                    system_override: str | None = None,
                    user_override: str | None = None) -> str:
    system, user_text = build_title_prompt(project, shots, kind)
    if system_override and system_override.strip():
        system = system_override.strip()
    if user_override and user_override.strip():
        user_text = user_override.strip()

    api_key = str(settings.get("ai.api_key", "") or "")
    base = str(settings.get("ai.base_url", "")).rstrip("/")
    model = str(settings.get("ai.model", "") or "")
    proxy = str(settings.get("ai.proxy", "") or "").strip()
    if not api_key:
        raise ValueError("没有配置 ai.api_key")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.8,
        "stream": False,
    }
    kwargs: dict = {"timeout": httpx.Timeout(connect=10, read=60, write=20, pool=20), "trust_env": False}
    if proxy:
        kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.post(base + "/chat/completions",
                                 headers={"Authorization": "Bearer " + api_key}, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"片名模型返回 {resp.status_code}：{resp.text[:200]}")
    text = clean(resp.json()["choices"][0]["message"]["content"])
    text = text.strip("《》\"'“”")
    return tidy_title(text, kind)
