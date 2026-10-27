"""音频上传 + 对口型：附件进消息、确认卡带音频（不提交 GPU）。

    python tests/test_audio.py
"""
import sys
import time
import wave

import httpx

import qa


def main() -> int:
    wav_path = r"D:\temp\qa_voice.wav"
    with wave.open(wav_path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(b"\x00\x00" * 16000)

    with open(wav_path, "rb") as fh:
        audio = httpx.Client(trust_env=False, timeout=60).post(
            qa.B + "/api/assets/upload",
            files={"file": ("qa_voice.wav", fh, "audio/wav")},
            data={"kind": "audio", "purpose": "narration"}).json()
    image = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + "/api/assets/upload",
        files={"file": ("face.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"kind": "image"}).json()
    print("素材:", audio["id"], image["id"])

    pid = qa.new_project("QA-音频")
    tid = qa.new_thread(pid, "音频")["id"]
    res = httpx.Client(trust_env=False, timeout=60).post(
        qa.B + f"/api/agent/threads/{tid}/messages",
        json={"text": "用这张图做对口型", "attachments": [audio["id"], image["id"]]}).json()

    got = {}
    for _ in range(40):
        time.sleep(1)
        got = qa.c.get(qa.B + f"/api/agent/runs/{res['run_id']}").json()
        if got.get("status") in ("waiting_confirm", "done", "failed"):
            break
    pending = got.get("pending") or {}
    params = pending.get("params") or {}
    msgs = qa.messages(tid)
    part_types = [p.get("type") for p in (msgs[0].get("parts") or [])]

    checks = [
        ("音频附件进消息", part_types == ["audio", "image"]),
        ("识别为对口型", pending.get("mode") == "lipsync"),
        ("确认卡带音频", params.get("audio_asset_id") == audio["id"]),
        ("音频槽正确", params.get("audio_slot") == "audio"),
    ]
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")

    if got.get("status") == "waiting_confirm":
        qa.confirm(got["id"], False)
    qa.drop_project(pid)
    for aid in (audio["id"], image["id"]):
        try:
            qa.c.delete(qa.B + f"/api/assets/{aid}")
        except Exception:
            pass
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
