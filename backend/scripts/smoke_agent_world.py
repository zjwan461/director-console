"""冒烟：问三类「以前答不上来」的问题，看引擎是否先查再答。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

B = "http://127.0.0.1:6006"
c = httpx.Client(trust_env=False, timeout=60)


def ask(text: str) -> str:
    pid = "prj_f029af8a3e8a"
    tid = c.post(B + "/api/agent/threads", json={"project_id": pid, "title": "smoke-offline"}).json()["id"]
    run = c.post(f"{B}/api/agent/threads/{tid}/messages", json={"text": text}).json()
    for _ in range(90):
        time.sleep(1)
        data = c.get(B + "/api/agent/runs/" + run["run_id"]).json()
        if data["status"] in ("waiting_confirm", "done", "failed"):
            break
    msgs = c.get(f"{B}/api/agent/threads/{tid}/messages").json()["items"]
    reply = msgs[-1]["content"] if msgs else ""
    c.delete(f"{B}/api/agent/threads/{tid}")
    return reply


def main() -> int:
    for question in ("comfyui 现在通吗？", "我做过多少项目？", "这个项目现在什么进度？"):
        started = time.time()
        print("=" * 60)
        print("Q:", question)
        print(ask(question))
        print(f"（{time.time() - started:.0f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
