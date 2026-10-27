"""话题切换：先说题材（「生化危机」），再答「视频啊」，应按新题材生成而不是改上一张图。

    python tests/test_topic.py
"""
import sys
import time

import httpx

import qa


def send(tid, text, wait=120):
    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages", json={"text": text}).json()
    run = {}
    for _ in range(wait):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    return run


def main() -> int:
    pid = qa.new_project("QA-话题")
    tid = qa.new_thread(pid, "话题")["id"]

    # 先有一张猫图，模拟「上一轮的产物」
    qa.add_artifacts(tid, [{
        "note": "黑猫舔爪子",
        "params": {"prompt": "黑猫舔着爪子，眼神微眯，尾巴轻摆", "aspect": "9:16",
                   "megapixels": 1.0, "duration": 5},
    }])

    run = send(tid, "生化危机")
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    ctx = httpx.Client(trust_env=False, timeout=20).get(
        qa.B + f"/api/agent/threads/{tid}").json()["thread"].get("context") or {}
    noted = ctx.get("last_topic") == "生化危机"

    run = send(tid, "视频啊")
    pending = run.get("pending") or {}
    params = pending.get("params") or {}
    prompt = str(params.get("prompt") or "")

    checks = [
        ("记住题材", noted, str(ctx.get("last_topic"))),
        ("按新题材出视频", pending.get("action") == "video" and pending.get("mode") == "t2v",
         f"{pending.get('action')}/{pending.get('mode')}"),
        ("提示词已扩写", len(prompt) >= 15, prompt[:40]),
        ("没沿用上一张图", "猫" not in prompt, prompt[:30]),
    ]
    for name, ok, extra in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}｜{extra}")

    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)
    qa.drop_project(pid)
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
