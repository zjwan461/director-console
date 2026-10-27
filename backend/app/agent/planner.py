"""多步计划（Step 2）：把「一句话多件事」拆成有序动作。

设计要点：
1. 规则快速通道优先——单意图直接返回一个步骤，仍然是 0.5 秒
2. 只有出现明显并列/递进标记，或规则判不出意图时，才调用模型规划
3. 模型只输出「调哪个工具、参数是什么」，不决定是否执行（确认门仍在图里）
4. 最多 4 步，工具白名单，非法步骤直接丢弃
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import graph as graph_module
from . import state as agent_state

MAX_STEPS = 4

# 工具白名单：与 graph 里的意图一一对应
TOOLS: dict[str, dict[str, Any]] = {
    "make_image": {"intent": "generate", "desc": "生成图片：要一张静态画面/剧照时用",
                   "args": {"prompt": "画面描述", "aspect": "9:16|16:9", "megapixels": "0.8~2.0"}},
    "make_video": {"intent": "generate_video",
                   "desc": "生成视频：要动的画面时用；有首帧图就 mode=i2v",
                   "args": {"prompt": "画面描述", "mode": "t2v|i2v|r2v", "duration": "秒",
                            "aspect": "9:16|16:9"}},
    "revise": {"intent": "revise",
               "desc": "改上一版：用户说「再亮一点/慢一点/换成竖屏/时长改 8 秒」时用，不要重新写 prompt",
               "args": {"raw": "用户原话，例如 第 2 张再亮一点"}},
    "lookup_assets": {"intent": "lookup", "desc": "查素材", "args": {"q": "关键词", "kind": "image|video|audio"}},
    "export_film": {"intent": "export", "desc": "导出成片：用户要 mp4/成片时用",
                    "args": {"quality": "1080p|720p"}},
    "polish_film": {"intent": "polish", "desc": "AI 剪辑：字幕/旁白/配音",
                    "args": {"kinds": "both|subtitle|narration", "tts": "bool"}},
    "set_bgm": {"intent": "bgm", "desc": "配乐", "args": {"mode": "auto|asset|off", "query": "关键词"}},
    "set_film_options": {"intent": "film_options", "desc": "转场/片头/片尾/画幅",
                         "args": {"raw": "用户原话"}},
    "create_project": {"intent": "create_project", "desc": "新建项目", "args": {"name": "项目名"}},
    "add_shots": {"intent": "add_shot", "desc": "批量加镜头", "args": {"raw": "用户原话"}},
}

# 复合句标记：出现这些才认为「一句话多件事」
COMPOUND_RE = re.compile(r"(然后|接着|再|并且|同时|之后|顺便|，再|；|;)")
# 依赖标记：后一步要用前一步的产物
DEPENDS_RE = re.compile(r"(这张图|这个图|刚才那|用它|基于它|把(它|这张)做成|这张.*视频|首帧)")

PLAN_SYSTEM = """你是导演台的执行规划器。把用户一句话拆成有序动作。

可用工具（只能选这些，冒号后面是「什么时候用」）：
{tools}

规则：
1. 只输出 JSON，形如 {{"steps":[{{"tool":"make_image","args":{{...}},"why":"一句话"}}],"reply":"对用户说的话"}}
2. 最多 {max_steps} 步；**能一步完成就不要拆**，宁可少拆也不要多拆
3. 参数里不要编造用户没说的信息；prompt 用用户原话里的画面描述
4. 后一步要用前一步的图（例如先出图再做视频）时：mode 设为 i2v，并在 args.depends_on 写前一步序号（从 1 开始）
5. 用户只是在聊天/提问时，输出 {{"steps":[],"reply":"..."}}
6. 不要输出解释、不要输出 markdown，只输出 JSON

示例：
用户「画一张雪夜黑猫，然后做成 5 秒视频」
→ {{"steps":[{{"tool":"make_image","args":{{"prompt":"雪夜黑猫","aspect":"9:16"}}}},
            {{"tool":"make_video","args":{{"prompt":"雪夜黑猫，5 秒","mode":"i2v","duration":5,"depends_on":1}}}}],
    "reply":"先出图，再拿它做视频"}}

用户「配点轻快的音乐，然后把片头改成《归人》」
→ {{"steps":[{{"tool":"set_bgm","args":{{"mode":"auto"}}}},
            {{"tool":"set_film_options","args":{{"raw":"片头改成《归人》"}}}}],"reply":"配乐和片头一起改"}}
"""


def _tools_text() -> str:
    lines = []
    for name, spec in TOOLS.items():
        args = "，".join(f"{k}: {v}" for k, v in spec["args"].items())
        lines.append(f"- {name}（{spec['desc']}）：{args}")
    return "\n".join(lines)


def looks_compound(text: str) -> bool:
    """粗略判断是否一句话多件事。"""
    if len(COMPOUND_RE.findall(text or "")) >= 1:
        return True
    # 同时出现两类动作关键词
    kinds = 0
    for pattern in (r"(画|出图|生成图)", r"(做.*视频|生成视频)", r"(字幕|旁白|配音)",
                    r"(配乐|音乐)", r"(导出|成片)", r"(片头|片尾|转场)"):
        if re.search(pattern, text or ""):
            kinds += 1
    return kinds >= 2


def steps_from_intent(intent: str, args: dict, text: str) -> list[dict]:
    tool = next((name for name, spec in TOOLS.items() if spec["intent"] == intent), "")
    if not tool:
        return []
    return [{"tool": tool, "args": dict(args or {}), "text": text}]


def normalize(steps: list[dict]) -> list[dict]:
    """白名单 + 上限 + 依赖序号修正。"""
    cleaned: list[dict] = []
    for index, step in enumerate(steps[:MAX_STEPS], start=1):
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool") or "").strip()
        if tool not in TOOLS:
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        depends_on = args.pop("depends_on", None)
        try:
            depends_on = int(depends_on) if depends_on is not None else None
        except (TypeError, ValueError):
            depends_on = None
        cleaned.append({
            "index": index,
            "tool": tool,
            "intent": TOOLS[tool]["intent"],
            "args": args,
            "why": str(step.get("why") or "")[:60],
            "depends_on": depends_on if depends_on and depends_on < index else None,
        })
    # 自动推断依赖：先出图/出片、再做视频，说明后一步要用前一步的产物
    for pos, step in enumerate(cleaned):
        if pos == 0 or step["depends_on"]:
            continue
        prev = cleaned[pos - 1]
        if (step["tool"] == "make_video"
                and prev["tool"] in ("make_image", "revise", "make_video")):
            step["depends_on"] = prev["index"]
            args = dict(step.get("args") or {})
            if not args.get("mode") or args.get("mode") == "t2v":
                args["mode"] = "i2v"
            # 「做成 3 秒视频」这类是命令不是画面描述，继承上一步的画面
            prompt = str(args.get("prompt") or "").strip()
            if re.match(r"^(做成|做一个|把它|把这个|用它|来一?个|生成)", prompt):
                base = str((prev.get("args") or {}).get("prompt") or "").strip()
                extra = re.sub(r"^(做成|做一个|把它|把这个|用它|来一?个|生成)", "", prompt).strip(" ，,。")
                args["prompt"] = f"{base}，{extra}" if base and extra else (base or extra or prompt)
            step["args"] = args

    # 去掉依赖不存在或指向自己之后的步骤
    return [s for s in cleaned if s["depends_on"] in (None,) or s["depends_on"] < s["index"]]


def split_by_rules(text: str) -> list[dict]:
    """不用模型的分句法：按「然后/接着/再/并且」切，再逐句跑规则意图。"""
    parts = [p.strip(" ，,。；;") for p in re.split(r"(?:然后|接着|之后|顺便|并且|，再|；|;)", text or "")]
    parts = [p for p in parts if len(p) >= 2]
    if len(parts) < 2:
        return []
    steps: list[dict] = []
    for part in parts:
        intent = graph_module._fast_intent({"text": part, "thread_id": "", "project_id": ""})
        if not intent:
            steps = []
            break
        tool_steps = steps_from_intent(intent.get("intent", ""), intent.get("args") or {}, part)
        if not tool_steps:
            steps = []
            break
        steps.extend(tool_steps)
    return normalize(steps)


async def plan(text: str, thread_id: str, project_id: str) -> dict:
    """返回 {"steps": [...], "reply": "...", "source": "fast|rules|llm"}。"""
    from .. import llm

    # 1) 单意图快速通道：不做任何规划
    fast = graph_module._fast_intent({"text": text, "thread_id": thread_id,
                                      "project_id": project_id})
    if fast and not looks_compound(text):
        steps = steps_from_intent(fast.get("intent", ""), fast.get("args") or {}, text)
        if steps:
            return {"steps": normalize(steps), "reply": fast.get("reply") or "",
                    "source": "fast", "intent": fast.get("intent")}

    # 2) 规则分句（免费、可解释）
    rule_steps = split_by_rules(text)
    if len(rule_steps) >= 2:
        return {"steps": rule_steps, "reply": "好，我按顺序做这几步。", "source": "rules"}

    # 3) 模型规划（只在复合/模糊时调用）
    if not llm.ready():
        return {"steps": [], "reply": "还没配置大模型（设置 → AI）。", "source": "llm"}

    summary = _state_summary(thread_id, project_id)
    messages = [
        {"role": "system", "content": PLAN_SYSTEM.format(
            tools=_tools_text(), max_steps=MAX_STEPS)},
        {"role": "system", "content": summary},
        {"role": "user", "content": text},
    ]
    try:
        result = await llm.chat_once(messages, temperature=0.1, max_tokens=1200)
        data = _parse(result.get("content") or "")
    except Exception as exc:
        return {"steps": [], "reply": f"规划失败：{exc}", "source": "llm"}

    steps = normalize(data.get("steps") or [])
    return {"steps": steps, "reply": str(data.get("reply") or ""), "source": "llm"}


def _state_summary(thread_id: str, project_id: str) -> str:
    st = agent_state.thread_state(thread_id)
    lines = [f"当前会话产物 {st['count']} 个："]
    for item in st["artifacts"][-6:]:
        lines.append(f"  #{item['ref']} {item['kind']} {item['note'] or item['prompt'][:20]}")
    shots = agent_state._shot_refs(project_id)
    if shots:
        lines.append(f"项目镜头 {len(shots)} 个：" + "、".join(s["title"] for s in shots[:6]))
    return "\n".join(lines)


def _parse(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
