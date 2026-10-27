"""图生视频的提示词应该由图/上下文生成，而不是写死的模板；确认卡要标出能力卡。

    python tests/test_motion_prompt.py
"""
import sys
import time

import httpx
from PIL import Image, ImageDraw

import qa


def main() -> int:
    img = Image.new("RGB", (384, 384), (30, 34, 50))
    ImageDraw.Draw(img).ellipse((100, 100, 280, 280), fill=(230, 220, 210))
    path = r"D:\temp\qa_motion_subject.png"
    img.save(path)

    with open(path, "rb") as fh:
        asset = httpx.Client(trust_env=False, timeout=60).post(
            qa.B + "/api/assets/upload", files={"file": ("subject.png", fh, "image/png")},
            data={"kind": "image"}).json()

    pid = qa.new_project("QA-运镜")
    tid = qa.new_thread(pid, "运镜")["id"]

    httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "", "attachments": [asset["id"]]})
    time.sleep(3)

    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "做成视频"}).json()
    run = {}
    for _ in range(180):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break

    pending = run.get("pending") or {}
    prompt = str((pending.get("params") or {}).get("prompt") or "")
    generic = ("人物轻微呼吸与发丝摆动", "让这张图动起来")
    checks = [
        ("确认卡出现", run.get("status") == "waiting_confirm", str(run.get("status"))),
        ("i2v 模式", pending.get("mode") == "i2v", str(pending.get("mode"))),
        ("运镜是看图生成的", bool(prompt) and not any(g in prompt for g in generic),
         prompt[:40]),
        ("标出能力卡", bool(pending.get("preset_name")) and bool(pending.get("preset_id")),
         f"{pending.get('preset_name')} / {pending.get('preset_id')}"),
    ]
    for name, ok, extra in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}｜{extra}")

    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)
    qa.drop_project(pid)
    try:
        httpx.Client(trust_env=False, timeout=20).delete(qa.B + f"/api/assets/{asset['id']}")
    except Exception:
        pass
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
