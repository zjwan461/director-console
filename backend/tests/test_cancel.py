"""确认卡取消后，回复应该明确说「已取消」，不能像要继续。

    python tests/test_cancel.py
"""
import sys
import time

import httpx

import qa


def main() -> int:
    pid = qa.new_project("QA-取消")
    tid = qa.new_thread(pid, "取消")["id"]

    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "画一张雪夜黑猫，竖屏"}).json()
    run = {}
    for _ in range(40):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    if run.get("status") != "waiting_confirm":
        print("[FAIL] 没有出现确认卡")
        qa.drop_project(pid)
        return 1

    before = len(qa.messages(tid))
    qa.confirm(run["id"], False)
    reply = ""
    for _ in range(20):
        time.sleep(0.5)
        msgs = qa.messages(tid)
        if len(msgs) > before and msgs[-1]["role"] == "assistant":
            reply = msgs[-1]["content"]
            break

    misleading = any(word in reply for word in ("我来", "稍等", "这就", "马上"))
    ok = reply.startswith("已取消") and not misleading
    print(f"[{'PASS' if ok else 'FAIL'}] 取消回复｜{reply[:50]}")
    print(f"[{'PASS' if not qa.artifacts(tid) else 'FAIL'}] 没有产生任务")
    qa.drop_project(pid)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
