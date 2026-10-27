"""Agentic 决策循环（Step 3 / 方案 B）。

和原来的「意图分类器」不同：模型能看到**当前状态**，还能**主动调工具查东西**，
再决定做什么。规则只保留高频快通道，长尾全部交给这里。

协议（模型只输出 JSON）：
  {"type": "tool", "tool": "describe_state" | "find_assets" | "card_info", "args": {...}}
  {"type": "propose", "steps": [{"tool": "...", "args": {...}}], "reply": "..."}
  {"type": "chat", "reply": "..."}
"""
from __future__ import annotations

import json
import re

from . import planner, state as agent_state, store as agent_store, tools

MAX_ROUNDS = 3

READ_TOOLS = {
    "describe_state": "看当前会话有哪些产物、项目有哪些镜头、这条消息带了什么附件",
    "find_assets": "按类型/关键词找素材（kind: image|video|audio，q 关键词）",
    "card_info": "查某个能力卡支持哪些参数（id 如 h3.i2v）",
}

LOOP_SYSTEM = """你是导演台的执行大脑。你能看状态、查素材，然后决定下一步做什么。

可执行的工具（动作，会弹确认卡给用户）：
{tools}

只读工具（先查清楚再决定）：
{read_tools}

输出协议（只输出一个 JSON，不要解释）：
- 需要更多信息时：{{"type":"tool","tool":"describe_state","args":{{}}}}
- 可以执行时：{{"type":"propose","steps":[{{"tool":"make_video","args":{{...}}}}],"reply":"对用户说的话"}}
- 只是聊天/解释时：{{"type":"chat","reply":"..."}}

规则：
0. 涉及项目本身的问题（有几个镜头、还缺什么、现在什么状态）→ 必须先调 describe_state，再回答；不要凭空说「看不到」
1. 先看状态再决定：用户说「这张图/刚才那个/第二个镜头」时，先用 describe_state 确认到底指什么
2. 不确定素材存不存在时，用 find_assets 查，不要凭空假设
3. steps 最多 3 个；能一步完成就不要拆
4. 参数里不要编造用户没说的信息；prompt 用用户原话里的画面描述
5. 后一步依赖前一步产物时，args.depends_on 写前一步序号，视频 mode 用 i2v
6. 不要重复调用同一个只读工具超过一次
7. add_shots 只用于「新增空镜头」；「把这张图放进第 N 镜 / 当首帧」应该用 make_video（mode=i2v）
8. 「用第 N 镜的画面/镜头做成视频」→ make_video mode=i2v，image_asset_id 取该镜的 cover_asset_id

当前状态：
{state}
"""


def _state_text(thread_id: str, project_id: str, attachments: list[dict]) -> str:
    st = agent_state.thread_state(thread_id)
    lines = [f"- 会话产物 {st['count']} 个（#n 是编号）"]
    for item in st["artifacts"][-6:]:
        note = item.get("note") or (item.get("prompt") or "")[:20]
        lines.append(f"    #{item['ref']} {item['kind']} {note}")
    shots = agent_state._shot_refs(project_id)
    if shots:
        lines.append(f"- 项目镜头 {len(shots)} 个：" + "、".join(
            f"{s['ref']}={s['title']}" for s in shots[:8]))
    if attachments:
        lines.append("- 本条消息附件：")
        for att in attachments:
            name = str(att.get("path") or "").rsplit("/", 1)[-1]
            lines.append(f"    {att.get('kind')} asset_id={att.get('id')} {name}")
    return "\n".join(lines)


def _read_tool(name: str, args: dict, thread_id: str, project_id: str,
               attachments: list[dict]) -> dict:
    if name == "describe_state":
        st = agent_state.thread_state(thread_id)
        return {
            "artifacts": [{"ref": a["ref"], "kind": a["kind"], "note": a["note"] or a["prompt"][:30],
                           "params": a["params"]} for a in st["artifacts"][-8:]],
            "shots": [
                {**s, "cover_asset_id": tools.asset_from_url(str(s.get("cover") or ""), "")
                 if s.get("cover") else ""}
                for s in agent_state._shot_refs(project_id)
            ],
            "attachments": [{"kind": a.get("kind"), "asset_id": a.get("id"),
                             "name": str(a.get("path") or "").rsplit("/", 1)[-1]} for a in attachments],
        }
    if name == "find_assets":
        raw = tools.list_assets(str(args.get("kind") or ""), str(args.get("q") or ""), "", 8)
        data = json.loads(raw)
        return {"items": [{"id": i["id"], "kind": i.get("kind"), "path": i.get("path"),
                           "url": i.get("url")} for i in (data.get("items") or [])[:8]]}
    if name == "card_info":
        card = tools.get_card(str(args.get("id") or ""))
        if not card:
            return {"error": "没有这张能力卡"}
        public = tools.public_card(card)
        return {"id": public.get("id"), "name": public.get("name"),
                "fields": [{"key": f.get("key"), "type": f.get("type"), "label": f.get("label"),
                            "required": f.get("required")} for f in (public.get("fields") or [])]}
    return {"error": f"未知只读工具 {name}"}


def _parse(text: str) -> dict:
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
    start, end = body.find("{"), body.rfind("}")
    if start >= 0 and end > start:
        body = body[start:end + 1]
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def run(text: str, thread_id: str, project_id: str,
              attachments: list[dict] | None = None) -> dict:
    """返回 {"steps": [...], "reply": ..., "source": "loop"|"error"}。"""
    from .. import llm

    if not llm.ready():
        return {"steps": [], "reply": "还没配置大模型（设置 → AI）。", "source": "error"}

    attachments = attachments or []
    tools_text = "\n".join(
        f"- {name}（{spec['desc']}）：{', '.join(spec['args'])}"
        for name, spec in planner.TOOLS.items())
    read_text = "\n".join(f"- {name}：{desc}" for name, desc in READ_TOOLS.items())

    messages = [
        {"role": "system", "content": LOOP_SYSTEM.format(
            tools=tools_text, read_tools=read_text,
            state=_state_text(thread_id, project_id, attachments))},
        {"role": "user", "content": text},
    ]

    for round_index in range(MAX_ROUNDS):
        try:
            result = await llm.chat_once(messages, temperature=0.2, max_tokens=1500)
        except Exception as exc:
            return {"steps": [], "reply": f"决策失败：{exc}", "source": "error"}
        data = _parse(result.get("content") or "")

        kind = str(data.get("type") or "")
        if kind == "tool":
            name = str(data.get("tool") or "")
            if name not in READ_TOOLS:
                messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
                messages.append({"role": "user", "content": "这个工具不存在，请用协议里的只读工具或直接 propose。"})
                continue
            payload = _read_tool(name, data.get("args") or {}, thread_id, project_id, attachments)
            messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
            messages.append({"role": "user", "content":
                             "工具结果：" + json.dumps(payload, ensure_ascii=False)[:1500]
                             + "\n继续：还需要信息就再调工具，够了就 propose 或 chat。"})
            continue

        if kind == "propose":
            steps = planner.normalize(data.get("steps") or [])
            return {"steps": steps, "reply": str(data.get("reply") or ""), "source": "loop"}

        if kind == "chat":
            return {"steps": [], "reply": str(data.get("reply") or ""), "source": "loop"}

        # 模型没按协议来：把它当作闲聊回复
        reply = str(data.get("reply") or result.get("content") or "").strip()
        return {"steps": [], "reply": reply[:500], "source": "loop"}

    return {"steps": [], "reply": "我想了几轮还是没定下来，你能再说具体一点吗？", "source": "loop"}
