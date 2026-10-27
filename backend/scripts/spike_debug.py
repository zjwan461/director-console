"""调试：看 deepagents 在失败用例里到底回了什么。"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from deepagents import create_deep_agent  # noqa: E402

from scripts.deepagent_spike import (  # noqa: E402
    SYSTEM, _model, describe_state, list_shots, find_assets, make_image, make_video,
)

CASES = ["让它动起来", "有没有生成好的视频", "视频啊"]


async def main() -> None:
    agent = create_deep_agent(
        model=_model(),
        tools=[describe_state, list_shots, find_assets, make_image, make_video],
        system_prompt=SYSTEM.format(thread_id="th_x", project_id="prj_x",
                                    state='{"artifacts":[{"ref":1,"kind":"image","note":"黑猫"}]}'),
        checkpointer=MemorySaver(),
    )
    for index, text in enumerate(CASES):
        config = {"configurable": {"thread_id": f"dbg_{index}"}}
        result = await agent.ainvoke({"messages": [{"role": "user", "content": text}]}, config)
        print("\n===", text)
        for msg in result.get("messages") or []:
            kind = getattr(msg, "type", "?")
            content = str(getattr(msg, "content", ""))[:150].replace("\n", " ")
            tool_calls = getattr(msg, "tool_calls", None)
            line = f"  [{kind}] {content}"
            if tool_calls:
                line += " | calls=" + json.dumps(
                    [{"name": c.get("name"), "args": c.get("args")} for c in tool_calls],
                    ensure_ascii=False)[:200]
            sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))


asyncio.run(main())
