"""只发文件不说话：应该确认收到并引导，且记住这张图/这段音频。

    python tests/test_files_only.py
"""
import sys
import time
import wave

import httpx

import qa


def upload(name, data, kind, mime):
    return httpx.Client(trust_env=False, timeout=60).post(
        qa.B + "/api/assets/upload", files={"file": (name, data, mime)},
        data={"kind": kind}).json()


def send(tid, text, attachments=None, wait=40):
    before = len(qa.messages(tid))
    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": text, "attachments": attachments or []}).json()
    run = {}
    for _ in range(wait):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    reply = ""
    for _ in range(12):
        msgs = qa.messages(tid)
        if len(msgs) > before and msgs[-1]["role"] == "assistant":
            reply = msgs[-1]["content"]
            break
        time.sleep(0.3)
    return run, reply


def main() -> int:
    image = upload("face.png", b"\x89PNG\r\n\x1a\n", "image", "image/png")
    wav_path = r"D:\temp\qa_only.wav"
    with wave.open(wav_path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(b"\x00\x00" * 32000)
    with open(wav_path, "rb") as fh:
        audio = upload("only.wav", fh.read(), "audio", "audio/wav")

    pid = qa.new_project("QA-只发文件")
    tid = qa.new_thread(pid, "只发文件")["id"]
    checks = []

    run, reply = send(tid, "", [image["id"]])
    checks.append(("只发图片有回应", run.get("status") == "done" and "收到图片" in reply, reply[:40]))

    run, reply = send(tid, "做成视频")
    pending = run.get("pending") or {}
    params = pending.get("params") or {}
    checks.append(("接着能做成视频", pending.get("mode") == "i2v"
                   and bool(params.get("image_asset_id")), str(pending.get("mode"))))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    run, reply = send(tid, "", [audio["id"]])
    checks.append(("只发音频有回应", run.get("status") == "done" and "收到音频" in reply, reply[:40]))

    for name, ok, extra in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}｜{extra}")

    qa.drop_project(pid)
    for asset in (image, audio):
        try:
            httpx.Client(trust_env=False, timeout=20).delete(qa.B + f"/api/assets/{asset['id']}")
        except Exception:
            pass
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
