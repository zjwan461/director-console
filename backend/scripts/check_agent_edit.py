"""离线验证：改图意图能走到确认卡（不点确认、不提交 ComfyUI）。"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = BACKEND / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(BACKEND))

import qa  # noqa: E402


def main() -> int:
    pid = qa.new_project("QA-改图意图")
    tid = qa.new_thread(pid, "改图")["id"]
    qa.add_artifacts(tid, [
        {"note": "雪地里的人", "params": {"prompt": "雪地里的人", "aspect": "9:16",
                                     "megapixels": 1.0, "duration": 5, "seed": 1}},
        {"note": "另一个人物", "params": {"prompt": "另一个人物", "aspect": "9:16",
                                     "megapixels": 1.0, "duration": 5, "seed": 2}},
    ])
    phrases = [
        "把背景换成雪夜山门，人物别动",
        "去掉画面右边的那只手",
        "把图 2 的人放到图 1 里",
        "换成竖屏",              # 这条应该还是 revise
    ]
    for text in phrases:
        run, _reply = qa.send(tid, text, timeout=180)
        pending = run.get("pending") or {}
        print("=" * 60)
        print("Q:", text)
        print("status:", run.get("status"), "| action:", pending.get("action"))
        params = pending.get("params") or {}
        for key in ("prompt", "resolution", "image_asset_id", "extra_asset_ids", "base_name"):
            if key in params:
                print(f"   {key} = {params[key]}")
        print("   summary:", pending.get("summary"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
