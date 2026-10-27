"""视频提示词应经 AI 优化：纯文本扩写、带参考图结合图内容。

    python tests/test_optimize.py
"""
import sys
import time

import httpx
from PIL import Image, ImageDraw

import qa


def main() -> int:
    pid = qa.new_project("QA-优化")
    tid = qa.new_thread(pid, "优化")["id"]
    checks = []

    # 1) 纯文本：一句话应扩成完整提示词
    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "做一个雪夜打斗视频"}).json()
    run = {}
    for _ in range(150):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    pending = run.get("pending") or {}
    params = pending.get("params") or {}
    prompt = str(params.get("prompt") or "")
    checks.append(("纯文本提示词被优化", len(prompt) >= 30 and params.get("ai_optimized") is True,
                   prompt[:40]))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    # 2) 带参考图：应走 i2v 并结合图内容
    img = Image.new("RGB", (512, 512), (16, 18, 28))
    draw = ImageDraw.Draw(img)
    draw.ellipse((130, 120, 380, 390), fill=(150, 150, 160))
    draw.ellipse((200, 230, 240, 270), fill=(20, 20, 20))
    draw.ellipse((290, 230, 330, 270), fill=(20, 20, 20))
    path = r"D:\temp\qa_opt_cat.png"
    img.save(path)
    with open(path, "rb") as fh:
        asset = httpx.Client(trust_env=False, timeout=60).post(
            qa.B + "/api/assets/upload", files={"file": ("c.png", fh, "image/png")},
            data={"kind": "image"}).json()
    httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "", "attachments": [asset["id"]]})
    time.sleep(3)

    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages", json={"text": "让它动起来"}).json()
    for _ in range(150):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    pending = run.get("pending") or {}
    params = pending.get("params") or {}
    prompt = str(params.get("prompt") or "")
    checks.append(("带图走 i2v", pending.get("mode") == "i2v"
                   and params.get("image_asset_id") == asset["id"], prompt[:40]))
    checks.append(("提示词结合了图", len(prompt) >= 15 and "雪" not in prompt, prompt[:40]))

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
