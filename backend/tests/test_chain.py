"""依赖链回归：先出图 → 自动续跑视频。

会真实调用 ComfyUI（出图 + 提交视频），默认跳过：
    python tests/test_chain.py --gpu
"""
import sys
import time

import qa

USE_GPU = "--gpu" in sys.argv


def main() -> int:
    if not USE_GPU:
        print("[SKIP] 依赖链需要真实出图，加 --gpu 才跑")
        return 0

    pid = qa.new_project("QA-依赖链")
    tid = qa.new_thread(pid, "链")["id"]

    run, _ = qa.send(tid, "画一张雪地黑猫，然后做成 3 秒视频", timeout=120)
    pending = run.get("pending") or {}
    steps = (pending.get("params") or {}).get("steps") or []
    print("计划:", [(s.get("index"), s.get("tool"), s.get("depends_on")) for s in steps])
    if pending.get("action") != "multi":
        print("[FAIL] 没有拆成多步")
        qa.drop_project(pid)
        return 1

    qa.confirm(run["id"], True, pending.get("params"))
    image_ok = video_job = ""
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(6)
        for item in qa.artifacts(tid):
            if item.get("kind") == "image" and item.get("url"):
                image_ok = True
            if item.get("kind") == "video" and str(item.get("ref_id", "")).startswith("job_"):
                video_job = item["ref_id"]
        if image_ok and video_job:
            break

    ok = bool(image_ok and video_job)
    print(f"[{'PASS' if ok else 'FAIL'}] 图={image_ok} 视频任务={video_job or '未触发'}")
    if video_job:
        try:
            qa.c.post(qa.B + f"/api/jobs/{video_job}/cancel")
        except Exception:
            pass
    qa.drop_project(pid)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
