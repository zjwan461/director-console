"""音频增强：时长对齐 / 多段参考音频 / 上传音频当 BGM。

    python tests/test_audio2.py
"""
import sys
import time
import wave

import httpx

import qa


def upload(name, data, kind, mime, purpose=""):
    form = {"kind": kind}
    if purpose:
        form["purpose"] = purpose
    return httpx.Client(trust_env=False, timeout=60).post(
        qa.B + "/api/assets/upload", files={"file": (name, data, mime)}, data=form).json()


def wav_bytes(seconds, path):
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(b"\x00\x00" * int(16000 * seconds))
    with open(path, "rb") as fh:
        return fh.read()


def send(tid, text, attachments):
    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": text, "attachments": attachments}).json()
    run = {}
    for _ in range(40):
        time.sleep(1)
        run = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if run.get("status") in ("waiting_confirm", "done", "failed"):
            break
    return run


def main() -> int:
    voice3 = upload("v3.wav", wav_bytes(3.0, r"D:\temp\qa_v3.wav"), "audio", "audio/wav", "narration")
    voice5 = upload("v5.wav", wav_bytes(5.0, r"D:\temp\qa_v5.wav"), "audio", "audio/wav", "narration")
    image = upload("f1.png", b"\x89PNG\r\n\x1a\n", "image", "image/png")
    image2 = upload("f2.png", b"\x89PNG\r\n\x1a\n", "image", "image/png")

    pid = qa.new_project("QA-音频增强")
    tid = qa.new_thread(pid, "音频增强")["id"]
    checks = []

    run = send(tid, "用这张图做对口型", [voice3["id"], image["id"]])
    params = (run.get("pending") or {}).get("params") or {}
    duration = params.get("duration")
    checks.append(("对口型按音频时长", bool(duration) and abs(float(duration) - 3.0) < 0.6,
                   f"{duration}s"))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    run = send(tid, "用这两张图和两段音频做参考。参考音频生成一个视频",
               [image["id"], image2["id"], voice3["id"], voice5["id"]])
    params = (run.get("pending") or {}).get("params") or {}
    ids = params.get("audio_asset_ids") or []
    checks.append(("多段参考音频", len(ids) == 2, f"{len(ids)} 段"))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], False)

    run = send(tid, "把这段音频当背景音乐", [voice5["id"]])
    pending = run.get("pending") or {}
    params = pending.get("params") or {}
    checks.append(("识别为指定 BGM", pending.get("action") == "bgm"
                   and params.get("asset_id") == voice5["id"], str(pending.get("action"))))
    if run.get("status") == "waiting_confirm":
        qa.confirm(run["id"], True)
        time.sleep(2)
        opts = qa.edit_state(pid).get("options") or {}
        tracks = opts.get("bgm_tracks") or []
        hit = any(t.get("asset_id") == voice5["id"] for t in tracks)
        checks.append(("BGM 写入项目", hit, f"{len(tracks)} 条"))

    for name, ok, extra in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}｜{extra}")

    qa.drop_project(pid)
    for asset in (voice3, voice5, image, image2):
        try:
            httpx.Client(trust_env=False, timeout=20).delete(qa.B + f"/api/assets/{asset['id']}")
        except Exception:
            pass
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
