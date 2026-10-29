"""复现语料里失败的「帮我补字幕和旁白」。"""

import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1] / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent))

import qa  # noqa: E402


def main() -> int:
    pid = qa.new_project("QA-调试-polish")
    tid = qa.new_thread(pid, "调试")["id"]
    shot = qa.make_shot(pid, "雪夜山门", "h3.t2v", "雪夜山门前黑衣剑客独行")
    qa.save_edit_state(pid, {"options": {}, "shot_edits": [
        {"shot_id": shot["id"], "narration_on": True, "in_point": 0, "out_point": 5}]})
    qa.add_artifacts(tid, [
        {"note": "雪地里的黑猫", "params": {"prompt": "雪地里的黑猫", "aspect": "9:16",
                                        "megapixels": 1.0, "duration": 5, "seed": 1}},
        {"note": "雪地里的白狐", "params": {"prompt": "雪地里的白狐", "aspect": "16:9",
                                        "megapixels": 0.8, "duration": 5, "seed": 1}},
        {"note": "雪夜剑客拔刀", "params": {"prompt": "雪夜剑客拔刀", "aspect": "9:16",
                                        "megapixels": 1.5, "duration": 5, "seed": 1}},
    ])
    for text in ("帮我补字幕和旁白", "配点背景音乐"):
        run, reply = qa.send(tid, text, timeout=180)
        pending = run.get("pending") or {}
        print("=" * 50)
        print("Q:", text)
        print("status:", run.get("status"), "action:", pending.get("action"))
        print("reply:", (reply or "")[:220])
    qa.cleanup(pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
