"""认知语料回归：34 条中文语句，检查意图 / 指代 / 修订是否落对。

默认不调用 GPU：需要真实出图/出视频的用例会被跳过。
要跑全量：`python tests/test_corpus.py --gpu`
"""
import sys
import time

import qa

USE_GPU = "--gpu" in sys.argv

CASES = [
    # 生成
    ("画一张雪夜剑客，竖屏", {"action": "image", "gpu": True}, "生成图片"),
    ("做一个 5 秒的雪地奔跑视频，横屏", {"action": "video", "gpu": True}, "生成视频"),
    ("可以，就用这张图", {"action": "video", "mode": "i2v", "gpu": True}, "图生视频承接"),
    ("用刚才这张图做视频", {"action": "video", "mode": "i2v", "gpu": True}, "图生视频"),
    # 导出 / 剪辑 / 配乐 / 设置
    ("导出成片", {"action": "export"}, "导出"),
    ("导出 720p", {"action": "export"}, "带参数导出"),
    ("帮我补字幕和旁白", {"action": "polish"}, "AI 剪辑"),
    ("配点背景音乐", {"action": "bgm"}, "配乐"),
    ("片头写《雪夜归人》，用淡入转场", {"action": "film_options"}, "成片设置"),
    # 修订与指代
    ("第 1 张再亮一点", {"action": "revise", "ref": 1}, "序号+修订"),
    ("刚才那个慢一点", {"action": "revise", "ref": 3}, "最近产物修订"),
    ("雪地里的白狐那张改成横屏", {"action": "revise", "ref": 2}, "描述指代+参数"),
    ("第 3 张时长改成 8 秒", {"action": "revise", "ref": 3}, "序号+时长"),
    ("再亮一点", {"action": "revise", "ref": 3}, "省略目标默认最近"),
    ("第 2 张再暗一点", {"action": "revise", "ref": 2, "patch_has": "压暗"}, "序号+压暗"),
    ("把第 1 张换成竖屏", {"action": "revise", "ref": 1, "patch_has": "9:16"}, "换成竖屏"),
    ("刚才那个快一点", {"action": "revise", "ref": 3, "patch_has": "加快"}, "加快"),
    ("第 2 张清晰度调到 2mp", {"action": "revise", "ref": 2, "patch_has": "2"}, "改清晰度"),
    ("上一版再快一点", {"action": "revise", "ref": 3, "patch_has": "加快"}, "上一版说法"),
    ("第 2 个改成 1.5mp", {"action": "revise", "ref": 2, "patch_has": "1.5"}, "个/清晰度"),
    # 查询
    ("有没有生成好的视频", {"action": None, "lookup": True, "reply_has": "找到"}, "查询成片"),
    ("有没有做好的图", {"action": None, "lookup": True, "reply_has": "找到"}, "查询图片"),
    ("有哪些成片", {"action": None, "lookup": True}, "查询成片（有哪些）"),
    ("看看之前的镜头", {"action": None, "lookup": True}, "查询历史镜头"),
    ("素材库里有什么猫的图", {"action": None, "lookup": True}, "素材检索"),
    # 问答
    ("你有哪些视频工作流可供选择？", {"action": None, "reply_has": "工作流"}, "列工作流"),
    ("怎么做图生视频？", {"action": None, "reply_has": "首帧"}, "解释：图生视频"),
    ("导出能选分辨率吗？", {"action": None, "reply_has": "720p"}, "解释：导出"),
    ("这些视频工作流有什么区别？", {"action": None, "reply_has": "参考图"}, "解释：区别"),
    ("你是谁？", {"action": None}, "闲聊"),
    # 项目 / 镜头
    ("加三个镜头：雪夜山门，蓝衣女子推门，她回身望向红灯", {"action": "add_shot"}, "批量加镜头"),
    ("把刚才那个存成镜头", {"action": None, "reply_has": "任务"}, "存镜头（数据是造的）"),
    ("新建一个项目叫《QA-子项目》", {"action": "create_project"}, "建项目"),
    # 边界
    ("第 9 张改一下", {"action": None, "reply_has": "产物"}, "越界提示"),
    ("第 1 张改一下", {"action": None, "reply_has": "改"}, "无改动提示"),
]


def main() -> int:
    pid = qa.new_project("QA-认知语料")
    tid = qa.new_thread(pid, "语料")["id"]
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

    passed = failed = skipped = 0
    for text, expect, label in CASES:
        if expect.get("gpu") and not USE_GPU:
            skipped += 1
            print(f"[SKIP] {label}｜需要 GPU（加 --gpu 才跑）")
            continue
        run, reply = qa.send(tid, text, timeout=120)
        pending = run.get("pending") or {}
        action = pending.get("action")
        params = pending.get("params") or {}

        ok, detail = True, []
        if expect.get("action"):
            ok = ok and run.get("status") == "waiting_confirm" and action == expect["action"]
            detail.append(f"action={action}")
        if expect.get("mode"):
            ok = ok and pending.get("mode") == expect["mode"]
            detail.append(f"mode={pending.get('mode')}")
        if expect.get("ref"):
            ok = ok and params.get("base_ref") == expect["ref"]
            detail.append(f"base=#{params.get('base_ref')}")
        if expect.get("patch_has"):
            blob = str(params.get("patch") or "")
            ok = ok and expect["patch_has"] in blob
            detail.append(blob[:36])
        if expect.get("reply_has"):
            ok = ok and expect["reply_has"] in reply
            detail.append(reply[:34])
        if expect.get("lookup"):
            msgs = qa.messages(tid)
            ok = ok and any(any(p.get("type") == "assets" for p in m["parts"]) for m in msgs)

        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {label}｜{text}｜{'；'.join(detail)}")

        if run.get("status") == "waiting_confirm":
            qa.confirm(run["id"], False)

    for proj in qa.c.get(qa.B + "/api/projects").json()["items"]:
        if proj["name"].startswith("QA-"):
            qa.drop_project(proj["id"])

    print(f"\n认知语料：{passed}/{passed + failed} 通过，跳过 {skipped} 条")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
