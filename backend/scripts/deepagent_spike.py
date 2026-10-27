"""deepagents 迁移评估（spike，不改动生产代码）。

目的：用同一批真实语句，比较 deepagents 与原实现的「意图理解 + 工具选择」表现，
并验证确认门（interrupt_on）能否桥接到我们现有的确认卡机制。

运行：
    cd backend
    python scripts/deepagent_spike.py

注意：make_image / make_video 是**干跑**，只记录参数，不会提交 ComfyUI。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from deepagents import create_deep_agent  # noqa: E402

from app import runtime  # noqa: E402
from app.agent import state as agent_state, store as agent_store, tools  # noqa: E402
from app.config import settings  # noqa: E402

runtime.apply_runtime_settings()

CALLS: list[dict] = []

FIXTURE = {
    "artifacts": [
        {"ref": 1, "kind": "image", "note": "黑猫舔爪子"},
        {"ref": 2, "kind": "image", "note": "雪夜剑客"},
    ],
    "shots": [
        {"ref": "S1", "title": "雪夜山门", "has_cover": True},
        {"ref": "S2", "title": "蓝衣女子", "has_cover": False},
    ],
}


def _model() -> ChatOpenAI:
    return ChatOpenAI(
        model=str(settings.get("ai.model") or ""),
        base_url=str(settings.get("ai.base_url") or ""),
        api_key=str(settings.get("ai.api_key") or ""),
        temperature=0,
        timeout=180,
        max_retries=1,
    )


@tool
def describe_state(thread_id: str) -> str:
    """查看当前会话有哪些产物、项目有哪些镜头。"""
    CALLS.append({"tool": "describe_state", "prompt": ""})
    return json.dumps({"artifacts": FIXTURE["artifacts"],
                       "count": len(FIXTURE["artifacts"]),
                       "last_ref": FIXTURE["artifacts"][-1]["ref"]}, ensure_ascii=False)


@tool
def list_shots(project_id: str) -> str:
    """列出项目里的镜头（序号、标题、有没有画面）。"""
    CALLS.append({"tool": "list_shots", "prompt": ""})
    return json.dumps(FIXTURE["shots"], ensure_ascii=False)


@tool
def find_assets(kind: str = "", q: str = "") -> str:
    """按类型（image/video/audio）和关键词找素材。"""
    CALLS.append({"tool": "find_assets", "prompt": kind or q})
    if kind == "video":
        return json.dumps([{"id": "ast_v1", "kind": "video", "note": "雪夜山门 5s"}],
                          ensure_ascii=False)
    return json.dumps([{"id": "ast_fixture_img", "kind": kind or "image"}], ensure_ascii=False)


@tool
def make_image(prompt: str, aspect: str = "9:16", megapixels: float = 1.0) -> str:
    """生成图片（会真实出图，本次为干跑）。"""
    CALLS.append({"tool": "make_image", "prompt": prompt, "aspect": aspect,
                  "megapixels": megapixels})
    return json.dumps({"ok": True, "dry_run": True, "would_submit": "image"}, ensure_ascii=False)


@tool
def make_video(prompt: str, mode: str = "t2v", duration: float = 5,
               image_ref: str = "") -> str:
    """生成视频。mode: t2v 文生视频 / i2v 用一张图当首帧 / r2v 参考图生成。"""
    CALLS.append({"tool": "make_video", "prompt": prompt, "mode": mode,
                  "duration": duration, "image_ref": image_ref})
    return json.dumps({"ok": True, "dry_run": True, "would_submit": "video"}, ensure_ascii=False)


SYSTEM = """你是导演台的执行助手，负责把用户的话变成具体操作。

可用工具：
- describe_state(thread_id)：看会话里有什么产物
- list_shots(project_id)：看项目镜头
- find_assets(kind, q)：找素材
- make_image(prompt, aspect, megapixels)：出图
- make_video(prompt, mode, duration, image_ref)：出视频（有图就 i2v，参考图就 r2v）

规则：
1. 用户提到「这张图 / 刚才那个 / 第几镜」时，先查状态再决定，不要猜
2. 提示词要写成可拍的画面描述（主体动作 + 环境 + 光线 + 运镜），40~70 字
3. 能一步完成就不要多步
4. 拿不准就先 describe_state

当前会话：thread_id={thread_id}，项目：project_id={project_id}
{state}
"""

CASES = [
    ("做一个雪夜打斗视频", {"make_video"}),
    ("让它动起来", {"make_video"}),
    ("这张太乱了，改干净一点", {"make_image", "make_video"}),
    ("改成横屏", {"make_image", "make_video"}),
    ("把第一镜的画面做成 5 秒动态镜头", {"make_video"}),
    ("有没有生成好的视频", {"find_assets", "describe_state"}),
    ("这条片子还缺什么", {"describe_state", "list_shots"}),
    ("生化危机", {"make_image", "make_video"}),
    ("视频啊", {"make_video"}),
    ("把刚才那张图塞进第二镜当首帧", {"make_video"}),
]


async def run_case(agent, text: str, thread_id: str, project_id: str) -> dict:
    CALLS.clear()
    started = time.time()
    config = {"configurable": {"thread_id": f"spike_{abs(hash(text)) % 100000}"}}
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": text}]}, config)
        elapsed = time.time() - started
        messages = result.get("messages") or []
        final = ""
        for msg in reversed(messages):
            if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
                final = str(msg.content)[:80]
                break
        return {"ok": True, "seconds": round(elapsed, 1), "calls": list(CALLS),
                "reply": final}
    except Exception as exc:
        return {"ok": False, "seconds": round(time.time() - started, 1),
                "error": f"{type(exc).__name__}: {exc}"[:200]}


async def check_interrupt(thread_id: str) -> dict:
    """确认门探针：把 make_image 标成需要人工确认，看 invoke 是否停下。"""
    agent = create_deep_agent(
        model=_model(),
        tools=[describe_state, make_image],
        system_prompt=SYSTEM.format(thread_id=thread_id, project_id="prj_x", state=""),
        interrupt_on={"make_image": True},
        checkpointer=MemorySaver(),
    )
    CALLS.clear()
    config = {"configurable": {"thread_id": "spike_interrupt"}}
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "画一张雪夜黑猫"}]}, config)
    snapshot = await agent.aget_state(config)
    interrupts = [i for task in snapshot.tasks for i in task.interrupts]
    return {"paused": bool(interrupts), "interrupt_count": len(interrupts),
            "calls": list(CALLS), "messages": len(result.get("messages") or [])}


async def main() -> None:
    # 造一个会话/项目上下文（只读，不写业务数据）
    project_id = "prj_spike"
    thread_id = "th_spike"
    state_text = json.dumps({
        "artifacts": [{"ref": 1, "kind": "image", "note": "黑猫舔爪子"},
                      {"ref": 2, "kind": "image", "note": "雪夜剑客"}],
        "shots": [{"ref": "S1", "title": "雪夜山门", "has_cover": True},
                  {"ref": "S2", "title": "蓝衣女子", "has_cover": False}],
    }, ensure_ascii=False)

    agent = create_deep_agent(
        model=_model(),
        tools=[describe_state, list_shots, find_assets, make_image, make_video],
        system_prompt=SYSTEM.format(thread_id=thread_id, project_id=project_id,
                                    state=state_text),
        checkpointer=MemorySaver(),
    )

    lines = ["# deepagents spike 结果", "",
             f"- 版本：deepagents 0.7.32 / 模型 {settings.get('ai.model')}",
             "- 工具：describe_state / list_shots / find_assets / make_image(干跑) / make_video(干跑)",
             "",
             "| 用例 | 命中 | 耗时 | 调用的工具 | 回复摘要 |",
             "|---|---|---|---|---|"]
    passed = 0
    for text, expect in CASES:
        result = await run_case(agent, text, thread_id, project_id)
        used = {c["tool"] for c in result.get("calls", [])}
        ok = bool(used & expect) if result.get("ok") else False
        passed += int(ok)
        detail = ""
        for call in result.get("calls", [])[:2]:
            detail += f" {call['tool']}({str(call.get('prompt') or call.get('mode') or '')[:28]})"
        reply = str(result.get("reply") or result.get("error") or "")[:40]
        line = (f"| {text} | {'PASS' if ok else 'FAIL'} | {result.get('seconds')}s | "
                f"{detail or '-'} | {reply} |")
        sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
        lines.append(line)
    lines.append("")
    lines.append(f"工具选择命中：{passed}/{len(CASES)}")

    probe = await check_interrupt(thread_id)
    print("\n确认门探针：", json.dumps(probe, ensure_ascii=False))
    lines += ["", "## 确认门探针", "", f"```json\n{json.dumps(probe, ensure_ascii=False, indent=2)}\n```", ""]

    out = Path(__file__).resolve().parents[2] / "docs" / "spike-deepagents.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n结果已写入", out)


if __name__ == "__main__":
    asyncio.run(main())
