"""Agentic 循环：规则没覆盖的说法，看状态后能否做对。

    python tests/test_agent_loop.py
"""
import sys
import time

import httpx

import qa

CASES = [
    ("把第一镜的画面做成 5 秒动态镜头", {"action": "video", "mode": "i2v"}, "从镜头做视频"),
    ("给我看看现在项目里有几个镜头，都是什么", {"reply_has": "镜头"}, "查镜头列表"),
    ("这条片子还缺什么", {"reply_has": "建议下一步"}, "片子体检"),
    ("把刚才那张图塞进第二镜当首帧", {"action": "video", "mode": "i2v"}, "图放进镜头当首帧"),
]


def main() -> int:
    pid = qa.new_project("QA-Agent循环")
    tid = qa.new_thread(pid, "循环")["id"]
    shot1 = qa.make_shot(pid, "雪夜山门", "h3.t2v", "雪夜山门")
    shot2 = qa.make_shot(pid, "蓝衣女子", "h3.t2v", "蓝衣女子推门")
    qa.save_edit_state(pid, {"options": {}, "shot_edits": [
        {"shot_id": shot1["id"], "narration_on": True, "in_point": 0, "out_point": 5},
        {"shot_id": shot2["id"], "narration_on": True, "in_point": 0, "out_point": 5},
    ]})
    qa.add_artifacts(tid, [
        {"note": "雪地里的黑猫", "params": {"prompt": "雪地里的黑猫", "aspect": "9:16",
                                        "megapixels": 1.0, "duration": 5}},
    ])

    failed = 0
    for text, expect, label in CASES:
        before = len(qa.messages(tid))
        res = httpx.Client(trust_env=False, timeout=60).post(
            qa.B + f"/api/agent/threads/{tid}/messages", json={"text": text}).json()
        run = {}
        for _ in range(120):
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
        pending = run.get("pending") or {}

        ok = True
        if expect.get("action"):
            ok = ok and pending.get("action") == expect["action"]
        if expect.get("mode"):
            ok = ok and pending.get("mode") == expect["mode"]
        if expect.get("reply_has"):
            ok = ok and expect["reply_has"] in reply
        print(f"[{'PASS' if ok else 'FAIL'}] {label}｜{text}｜action={pending.get('action')} "
              f"mode={pending.get('mode')}｜{reply[:30]}")
        if not ok:
            failed += 1
        if run.get("status") == "waiting_confirm":
            qa.confirm(run["id"], False)

    qa.drop_project(pid)
    print(f"\nAgent 循环：{'全部通过' if failed == 0 else str(failed) + ' 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
