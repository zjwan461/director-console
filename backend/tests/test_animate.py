"""上传图 + 「让它动起来」：应走图生视频，并且看图写运镜（不是文生视频）。

    python tests/test_animate.py
"""
import sys
import time

import httpx
from PIL import Image, ImageDraw

import qa


def make_cat(path: str) -> str:
    img = Image.new("RGB", (512, 512), (18, 20, 30))
    draw = ImageDraw.Draw(img)
    draw.ellipse((120, 110, 390, 400), fill=(240, 150, 60))
    draw.polygon([(150, 150), (200, 70), (250, 150)], fill=(240, 150, 60))
    draw.polygon([(270, 150), (320, 70), (370, 150)], fill=(240, 150, 60))
    draw.ellipse((190, 240, 230, 280), fill=(30, 30, 30))
    draw.ellipse((290, 240, 330, 280), fill=(30, 30, 30))
    draw.ellipse((235, 300, 285, 335), fill=(255, 120, 140))
    img.save(path)
    return path


def main() -> int:
    path = make_cat(r"D:\temp\qa_animate_cat.png")
    with open(path, "rb") as fh:
        asset = httpx.Client(trust_env=False, timeout=60).post(
            qa.B + "/api/assets/upload", files={"file": ("cat.png", fh, "image/png")},
            data={"kind": "image"}).json()

    pid = qa.new_project("QA-动起来")
    tid = qa.new_thread(pid, "动起来")["id"]
    httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "", "attachments": [asset["id"]]})
    time.sleep(3)

    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "让它动起来"}).json()
    run = {}
    for _ in range(150):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break

    pending = run.get("pending") or {}
    params = pending.get("params") or {}
    prompt = str(params.get("prompt") or "")
    checks = [
        ("走图生视频", pending.get("action") == "video" and pending.get("mode") == "i2v",
         f"{pending.get('action')}/{pending.get('mode')}"),
        ("用的是刚上传的图", params.get("image_asset_id") == asset["id"],
         str(params.get("image_asset_id"))),
        ("提示词由图生成", len(prompt) >= 10 and "黄昏" not in prompt, prompt[:40]),
        ("标出能力卡", bool(pending.get("preset_name")), str(pending.get("preset_name"))),
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
