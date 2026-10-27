"""多步计划回归：复合请求能否拆成多步、一次确认、连续执行。

不需要 GPU（所有 GPU 类计划都在确认卡处取消）。
"""
import sys
import time

import qa

CASES = [
    ("第 2 张再亮一点，然后导出成片", 2),
    ("配点轻快的音乐，然后把片头改成《归人》", 2),
    ("帮我补字幕和旁白，然后导出 720p", 2),
    ("画一张雪夜黑猫，然后做成 3 秒视频", 2),
]


def main() -> int:
    pid = qa.new_project("QA-多步")
    tid = qa.new_thread(pid, "多步")["id"]
    shot = qa.make_shot(pid, "镜一", "h3.t2v", "雪地")
    qa.save_edit_state(pid, {"options": {}, "shot_edits": [
        {"shot_id": shot["id"], "narration_on": True, "in_point": 0, "out_point": 5}]})
    qa.add_artifacts(tid, [
        {"note": "雪地里的黑猫", "params": {"prompt": "雪地里的黑猫", "aspect": "9:16",
                                        "megapixels": 1.0, "duration": 5}},
        {"note": "雪地里的白狐", "params": {"prompt": "雪地里的白狐", "aspect": "16:9",
                                        "megapixels": 0.8, "duration": 5}},
    ])

    failed = 0
    for text, want in CASES:
        run, _ = qa.send(tid, text, timeout=120)
        pending = run.get("pending") or {}
        steps = (pending.get("params") or {}).get("steps") or []
        ok = pending.get("action") == "multi" and len(steps) >= want
        print(f"[{'PASS' if ok else 'FAIL'}] {text}｜steps={len(steps)}｜{pending.get('summary')}")
        if not ok:
            failed += 1
        if run.get("status") == "waiting_confirm":
            qa.confirm(run["id"], False)

    # 连续执行：两步都不依赖 GPU，确认后应同时落库
    run, _ = qa.send(tid, "配点轻快的音乐，然后把片头改成《归人》", timeout=120)
    ok_exec = False
    if (run.get("pending") or {}).get("action") == "multi":
        qa.confirm(run["id"], True)
        time.sleep(3)
        opts = qa.edit_state(pid).get("options") or {}
        ok_exec = bool((opts.get("title") or {}).get("text")) and bool(opts.get("bgm_tracks"))
        print(f"[{'PASS' if ok_exec else 'FAIL'}] 两步连续执行｜"
              f"title={(opts.get('title') or {}).get('text')} bgm={len(opts.get('bgm_tracks') or [])}")
    if not ok_exec:
        failed += 1

    qa.drop_project(pid)
    print(f"\n多步计划：{'全部通过' if failed == 0 else str(failed) + ' 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
