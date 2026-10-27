"""统一的对话模型调用：兼容 DeepSeek 系 reasoning_content。

国内多数 OpenAI 兼容服务（DeepSeek / vLLM / SGLang / Qwen）会把思考过程放在
`reasoning_content`（或 `reasoning`）字段里，`content` 要等思考结束才出现。
这里统一解析，并把思考增量单独抛出来，前端可以边等边显示。

设置项 `ai.reasoning_mode`：
- auto      ：有 reasoning_content 就显示，没有就忽略（默认）
- deepseek  ：强制按 DeepSeek 字段解析
- off       ：关闭思考（对支持 enable_thinking 的模型有效）
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import settings
from .netutil import proxy_for

MODES = ("auto", "deepseek", "off")


def reasoning_mode() -> str:
    mode = str(settings.get("ai.reasoning_mode", "auto") or "auto").strip().lower()
    return mode if mode in MODES else "auto"


def _endpoint() -> tuple[str, str, str, str]:
    base = str(settings.get("ai.base_url", "") or "").rstrip("/")
    key = str(settings.get("ai.api_key", "") or "")
    model = str(settings.get("ai.model", "") or "")
    proxy = str(settings.get("ai.proxy", "") or "")
    return base, key, model, proxy


def ready() -> bool:
    base, key, model, _ = _endpoint()
    return bool(base and key and model)


def _payload(messages: list[dict], *, temperature: float, max_tokens: int | None,
             stream: bool) -> dict[str, Any]:
    _, _, model, _ = _endpoint()
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    if reasoning_mode() == "off":
        # Qwen3 / 部分网关支持；不支持的服务会忽略这个字段
        body["enable_thinking"] = False
    return body


def _client(proxy: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(180.0, connect=15.0),
        proxy=proxy_for(str(settings.get("ai.base_url", "") or ""), proxy),
        trust_env=False,
    )


def extract_reasoning(message: dict) -> str:
    return str(message.get("reasoning_content") or message.get("reasoning") or "")


def to_dicts(messages) -> list[dict]:
    """把 langchain 消息对象（或 dict）转成 OpenAI 格式。"""
    out: list[dict] = []
    for message in messages:
        if isinstance(message, dict):
            out.append(message)
            continue
        kind = getattr(message, "type", "") or ""
        role = {"human": "user", "ai": "assistant", "system": "system"}.get(kind, kind or "user")
        content = getattr(message, "content", "")
        out.append({"role": role, "content": content if isinstance(content, str) else str(content)})
    return out


async def chat_once(messages: list[dict], *, temperature: float = 0.3,
                    max_tokens: int | None = None) -> dict:
    """一次性返回 {content, reasoning, raw}。"""
    base, key, _, proxy = _endpoint()
    if not (base and key):
        raise RuntimeError("还没配置大模型（设置 → AI）")
    body = _payload(messages, temperature=temperature, max_tokens=max_tokens, stream=False)

    async with _client(proxy) as client:
        resp = await client.post(f"{base}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {key}"})
        if resp.status_code >= 400 and "enable_thinking" in body:
            body.pop("enable_thinking", None)
            resp = await client.post(f"{base}/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        data = resp.json()

    message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
    # 推理模型会把 max_tokens 先花在思考上，正文可能被挤空——放大预算重试一次
    if max_tokens and not str(message.get("content") or "").strip() and extract_reasoning(message):
        async with _client(proxy) as client:
            retry_body = dict(body)
            retry_body["max_tokens"] = max_tokens * 3
            retry = await client.post(f"{base}/chat/completions", json=retry_body,
                                      headers={"Authorization": f"Bearer {key}"})
            retry.raise_for_status()
            data = retry.json()
        message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
    return {
        "content": str(message.get("content") or ""),
        "reasoning": extract_reasoning(message),
        "raw": data,
    }


async def chat_stream(messages: list[dict], *, temperature: float = 0.3,
                      max_tokens: int | None = None) -> AsyncIterator[dict]:
    """流式返回 {"type": "reasoning"|"content", "text": str}。"""
    base, key, _, proxy = _endpoint()
    if not (base and key):
        raise RuntimeError("还没配置大模型（设置 → AI）")
    body = _payload(messages, temperature=temperature, max_tokens=max_tokens, stream=True)

    async with _client(proxy) as client:
        async with client.stream("POST", f"{base}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {key}"}) as resp:
            if resp.status_code >= 400 and "enable_thinking" in body:
                await resp.aread()
                body.pop("enable_thinking", None)
                async with client.stream("POST", f"{base}/chat/completions", json=body,
                                         headers={"Authorization": f"Bearer {key}"}) as retry:
                    retry.raise_for_status()
                    async for event in _iter_sse(retry):
                        yield event
                return
            resp.raise_for_status()
            async for event in _iter_sse(resp):
                yield event


async def _iter_sse(resp: httpx.Response) -> AsyncIterator[dict]:
    async for line in resp.aiter_lines():
        line = (line or "").strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line.endswith(chr(93)): break
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        choices = data.get("choices") or list()
        choice = choices.pop() if choices else dict()
        delta = choice.get("delta") or choice.get("message") or dict()
        reasoning = str(delta.get("reasoning_content") or delta.get("reasoning") or "")
        if reasoning:
            yield dict(type="reasoning", text=reasoning)
        content = delta.get("content")
        if type(content) is list:
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if content:
            yield dict(type="content", text=str(content))


def vision_model_name() -> str:
    return str(settings.get("ai.vision_model") or settings.get("ai.model") or "")


async def chat_vision(image_b64_list: list[tuple[str, str]], instruction: str,
                      *, max_tokens: int = 900, temperature: float = 0.6) -> str:
    """看图说话：image_b64_list 为 [(mime, base64), ...]。"""
    base, key, _, proxy = _endpoint()
    if not (base and key):
        raise RuntimeError("还没配置大模型（设置 → AI）")

    content: list[dict] = [{"type": "text", "text": instruction}]
    for mime, b64 in image_b64_list[:4]:
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"}})

    body = {
        "model": vision_model_name(),
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with _client(proxy) as client:
        resp = await client.post(f"{base}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        data = resp.json()
    message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
    text = str(message.get("content") or "").strip()
    if not text:
        # 推理模型会把预算花在思考上，正文被挤空——放大预算重试一次
        body["max_tokens"] = max_tokens * 2
        body["messages"] = [{"role": "user", "content": content}]
        async with _client(proxy) as client:
            retry = await client.post(f"{base}/chat/completions", json=body,
                                      headers={"Authorization": f"Bearer {key}"})
            retry.raise_for_status()
            data = retry.json()
        message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
        text = str(message.get("content") or "").strip()
    return text
