"""视觉能力回归：看图写运镜（i2v / r2v）、看图理解修订（模糊评价 / 改画幅）。

    python tests/test_vision.py
"""
import sys
import time

import httpx
from PIL import Image, ImageDraw

import qa

GENERIC = ("人物轻微呼吸与发丝摆动", "让这张图动起来")


def upload(name, path, kind="image"):
    with open(path, "rb") as fh:
        return httpx.Client(trust_env=False, timeout=60).post(
            qa.B + "/api/assets/upload", files={"file": (name, fh, "image/png")},
            data={"kind": kind}).json()


def make_image(path, palette=((20, 24, 38), (225, 215, 205))):
    img = Image.new("RGB", (512, 512), palette[0])
    draw = ImageDraw.Draw(img)
    draw.ellipse((170, 140, 340, 320), fill=palette[1])
    draw.rectangle((150, 330, 360, 390), fill=(120, 40, 40))
    img.save(path)
    return path


def send(tid, text, attachments=None, wait=120):
    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": text, "attachments": attachments or []}).json()
    run = {}
    for _ in range(wait):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    return run


def main() -> int:
    pid = qa.new_project("QA-视觉")
    tid = qa.new_thread(pid, "视觉")["id"]
    checks = []

    # 1) 图生视频：没写提示词 → 看图写运镜
    subject = upload("i2v.png", make_image(r"D:\temp\qa_vision_i2v.png"))
    httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "", "attachments": [subject["id"]]})
    time.sleep(3)
    run = send(tid, "做成视频")
    params = (run.get("pending") or {}).get("params") or {}
    prompt = str(params.get("prompt") or "")
    checks.append(("i2v 看图写运镜", bool(prompt) and not any(g in prompt for g in GENERIC), prompt[:36]))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    # 2) 参考生视频：整句只是命令 → 也看图写
    ref = upload("r2v.png", make_image(r"D:\temp\qa_vision_r2v.png", ((30, 40, 50), (200, 210, 220))))
    run = send(tid, "参考这张图做个视频", [ref["id"]])
    pending = run.get("pending") or {}
    params = pending.get("params") or {}
    prompt = str(params.get("prompt") or "")
    checks.append(("r2v 看图写运镜", pending.get("mode") == "r2v"
                   and bool(prompt) and not any(g in prompt for g in GENERIC),
                   f"status={run.get('status')} mode={pending.get('mode')} {prompt[:30]}"))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    # 3) 修订：模糊评价 → 视觉翻译成具体改动
    base = upload("base.png", make_image(r"D:\temp\qa_vision_base.png"))
    qa.add_artifacts(tid, [{
        "note": "深蓝背景里的浅色球体",
        "url": f"/media/files/{base['path']}",
        "params": {"prompt": "深蓝背景里的浅色球体", "aspect": "1:1",
                   "megapixels": 1.0, "duration": 5},
    }])
    run = send(tid, "这张太乱了，改干净一点")
    pending = run.get("pending") or {}
    summary = str(pending.get("summary") or "")
    checks.append(("模糊修订走视觉", pending.get("action") == "revise" and "看图：" in summary,
                   summary[:40]))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    # 4) 改画幅：视觉给构图调整
    run = send(tid, "改成横屏")
    pending = run.get("pending") or {}
    summary = str(pending.get("summary") or "")
    checks.append(("改画幅给构图建议", pending.get("action") == "revise" and "看图：" in summary,
                   summary[:40]))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    for name, ok, extra in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}｜{extra}")

    qa.drop_project(pid)
    for asset in (subject, ref, base):
        try:
            httpx.Client(trust_env=False, timeout=20).delete(qa.B + f"/api/assets/{asset['id']}")
        except Exception:
            pass
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
