"""新增能力回归：撤销 / 批量存镜头 / 逐步执行 / 「再快一点」不被当成复合句。

    python tests/test_actions.py
"""
import sys
import time

import httpx

import qa


def seed(pid: str, tid: str) -> None:
    qa.make_shot(pid, "雪夜山门", "h3.t2v", "雪夜山门")
    qa.add_artifacts(tid, [
        {"note": "雪地里的黑猫", "params": {"prompt": "雪地里的黑猫", "aspect": "9:16",
                                        "megapixels": 1.0, "duration": 5, "seed": 1}},
        {"note": "雪地里的白狐", "params": {"prompt": "雪地里的白狐", "aspect": "16:9",
                                        "megapixels": 0.8, "duration": 5, "seed": 1}},
        {"note": "雪夜剑客拔刀", "params": {"prompt": "雪夜剑客拔刀", "aspect": "9:16",
                                        "megapixels": 1.5, "duration": 5, "seed": 1}},
    ])


def ask(tid: str, text: str, wait: int = 120):
    before = len(qa.messages(tid))
    res = httpx.Client(trust_env=False, timeout=90).post(
        qa.B + f"/api/agent/threads/{tid}/messages", json={"text": text}).json()
    run = {}
    for _ in range(wait):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    reply = ""
    for _ in range(10):
        msgs = qa.messages(tid)
        if len(msgs) > before and msgs[-1]["role"] == "assistant":
            reply = msgs[-1]["content"]
            break
        time.sleep(0.3)
    return run, reply


def main() -> int:
    pid = qa.new_project("QA-新能力")
    tid = qa.new_thread(pid, "新")["id"]
    seed(pid, tid)
    checks = []

    # 1) 「再快一点」是单意图，必须出 revise 卡（曾经被复合句判断吃掉）
    run, _ = ask(tid, "上一版再快一点")
    action = (run.get("pending") or {}).get("action")
    checks.append(("再快一点 → revise", action == "revise", str(action)))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    # 2) 撤销
    run, reply = ask(tid, "撤销")
    checks.append(("撤销", "为准" in reply, reply[:36]))

    # 3) 批量存镜头
    run, reply = ask(tid, "把这 3 张都存成镜头")
    shots = httpx.Client(trust_env=False, timeout=20).get(
        qa.B + f"/api/projects/{pid}/shots").json()
    items = shots.get("items") if isinstance(shots, dict) else shots
    checks.append(("批量存镜头", len(items or []) >= 3, f"{len(items or [])} 个镜头"))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    # 4) 只执行第一步 → 说继续 → 剩余步骤重新确认
    run, _ = ask(tid, "配点轻快的音乐，然后把片头改成《归人》")
    pending = run.get("pending") or {}
    steps = (pending.get("params") or {}).get("steps") or []
    if run.get("status") == "waiting_confirm" and len(steps) > 1:
        httpx.Client(trust_env=False, timeout=90).post(
            qa.B + f"/api/agent/runs/{run['id']}/confirm",
            json={"approved": True, "only_first": True})
        time.sleep(3)
        run2, _ = ask(tid, "继续")
        pending2 = run2.get("pending") or {}
        left = (pending2.get("params") or {}).get("steps") or []
        checks.append(("逐步执行", pending2.get("action") == "multi" and len(left) >= 1,
                       f"剩余 {len(left)} 步"))
        if run2.get("status") == "waiting_confirm":
            qa.confirm(run2["id"], False)
    else:
        checks.append(("逐步执行", False, "多步卡未生成"))

    for name, ok, extra in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}｜{extra}")

    qa.drop_project(pid)
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
