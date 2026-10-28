"""把 12 个镜头按顺序铺进项目，填好能力卡、提示词、参考图、时长，交给用户手动出片。

- A1/A2 已有视频：直接设为当前 take
- A3..D3：只建镜头 + 预填参数，不自动生成
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

from dabidou_prompts import (  # noqa: E402
    A3_PROMPT_PLAIN, A4_PROMPT, B1_PROMPT, B2_PROMPT, C1_PROMPT_PLAIN, C2_PROMPT_PLAIN,
    C3_PROMPT, D1_PROMPT_PLAIN, D2_PROMPT, D3_PROMPT,
)

B = "http://127.0.0.1:6006"
PROJECT = "prj_f029af8a3e8a"
PACK = json.loads((Path(__file__).resolve().parents[2] / "logs" / "dabidou_pack.json")
                  .read_text(encoding="utf-8"))
STATE = json.loads((Path(__file__).resolve().parents[2] / "logs" / "dabidou_state.json")
                   .read_text(encoding="utf-8"))

client = httpx.Client(trust_env=False, timeout=120)

REF = {
    "yilong": PACK["anchor_yilong"]["asset_id"],
    "liuyu": PACK["anchor_liuyu"]["asset_id"],
    "tuoba": PACK["anchor_tuoba"]["asset_id"],
}

SHOTS = [
    {"key": "a1", "title": "A1 上香", "preset": "h3.i2v", "duration": 6, "mp": 0.4,
     "prompt": STATE["videos"].get("a1", {}).get("url") and "（首帧）", "still": PACK["a1"]["asset_id"],
     "note": "背影上香，只有香烟与烛火在动"},
    {"key": "a2", "title": "A2 拍肩", "preset": "h3.i2v", "duration": 4, "mp": 0.4,
     "prompt": "（首帧）", "still": PACK["a2"]["asset_id"],
     "note": "只出现一只老人的手，注意别多手"},
    {"key": "a3", "title": "A3 回头", "preset": "h3.r2v", "duration": 4, "mp": 0.7,
     "prompt": A3_PROMPT_PLAIN, "refs": ["yilong"], "note": "猛回头，惊愕"},
    {"key": "a4", "title": "A4 爹", "preset": "h3.r2v9", "duration": 8, "mp": 0.7,
     "prompt": A4_PROMPT, "refs": ["liuyu", "yilong"], "note": "弹香灰 + 「爹」「嗯」"},
    {"key": "b1", "title": "B1 北伐", "preset": "h3.r2v9", "duration": 10, "mp": 0.7,
     "prompt": B1_PROMPT, "refs": ["liuyu", "yilong"], "note": "打到长安了吗 / 没呢爹"},
    {"key": "b2", "title": "B2 二百多天", "preset": "h3.r2v9", "duration": 8, "mp": 0.7,
     "prompt": B2_PROMPT, "refs": ["liuyu", "yilong"], "note": "围了多久 / 二百多天"},
    {"key": "c1", "title": "C1 长江", "preset": "h3.r2v", "duration": 6, "mp": 0.7,
     "prompt": C1_PROMPT_PLAIN, "refs": ["liuyu", "yilong"], "note": "画外音，两人同时转头"},
    {"key": "c2", "title": "C2 拓跋焘出场", "preset": "h3.r2v", "duration": 7, "mp": 0.7,
     "prompt": C2_PROMPT_PLAIN, "refs": ["tuoba"], "note": "拎着药走进来，笑面赢家"},
    {"key": "c3", "title": "C3 三人", "preset": "h3.r2v9", "duration": 9, "mp": 0.7,
     "prompt": C3_PROMPT, "refs": ["liuyu", "yilong", "tuoba"], "note": "滚滚滚 / 你怎么会在这"},
    {"key": "d1", "title": "D1 两千七百人", "preset": "h3.r2v", "duration": 10, "mp": 0.7,
     "prompt": D1_PROMPT_PLAIN, "refs": ["liuyu"], "note": "长台词，压着火"},
    {"key": "d2", "title": "D2 一巴掌", "preset": "h3.u22", "duration": 4, "mp": 0.7,
     "prompt": D2_PROMPT, "refs": ["liuyu", "yilong"], "note": "武术卡，注意接触力道"},
    {"key": "d3", "title": "D3 跑了", "preset": "h3.u22", "duration": 4, "mp": 0.7,
     "prompt": D3_PROMPT, "refs": ["yilong", "liuyu"], "note": "捂脸转身跑出画面"},
]


def api(method: str, path: str, payload: dict | None = None) -> dict:
    for _ in range(5):
        try:
            resp = client.request(method, B + path, json=payload)
            if resp.status_code < 500:
                return resp.json() if resp.content else {}
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return {}


def main() -> int:
    existing = {s["title"]: s for s in api("GET", f"/api/projects/{PROJECT}/shots").get("items", [])}

    for spec in SHOTS:
        title = spec["title"]
        values = {"prompt": spec["prompt"], "size": {"aspect": "9:16", "megapixels": spec["mp"]},
                  "duration": spec["duration"]}
        if spec.get("still"):
            values["first_frame"] = spec["still"]
        for index, ref in enumerate(spec.get("refs", []), start=1):
            values[f"ref_{index}"] = REF[ref]

        shot = existing.get(title)
        if shot:
            api("PATCH", f"/api/shots/{shot['id']}", {"preset_id": spec["preset"], "values": values})
            log = f"更新 {title}"
        else:
            shot = api("POST", "/api/shots", {"project_id": PROJECT, "title": title,
                                              "preset_id": spec["preset"], "values": values})
            api("PATCH", f"/api/shots/{shot['id']}", {"values": values})
            log = f"新建 {title}"

        cover = spec.get("still") or (REF[spec["refs"][0]] if spec.get("refs") else "")
        if cover:
            asset = api("GET", f"/api/assets/{cover}")
            if asset.get("path"):
                api("PATCH", f"/api/shots/{shot['id']}", {"cover": f"/media/files/{asset['path']}"})

        print(f"{log}  {spec['preset']}  {spec['duration']}s  {spec['note']}")

    # A1/A2 已有视频 → 设为当前 take
    jobs = api("GET", "/api/jobs?limit=50").get("items", [])
    for spec in SHOTS[:2]:
        shot = next((s for s in api("GET", f"/api/projects/{PROJECT}/shots").get("items", [])
                     if s["title"] == spec["title"]), None)
        if not shot:
            continue
        done = next((j for j in jobs if j.get("shot_id") == shot["id"]
                     and j.get("status") == "succeeded"
                     and any(str(o.get("kind")) == "video" for o in (j.get("outputs") or []))), None)
        if done:
            api("POST", f"/api/shots/{shot['id']}/activate-take", {"job_id": done["id"]})
            print(f"  已挂上成片：{spec['title']} <- {done['id']}")

    shots = api("GET", f"/api/projects/{PROJECT}/shots").get("items", [])
    print(f"\n项目里现在有 {len(shots)} 个镜头：")
    for s in shots:
        print(f"  {s['title']}  {s.get('preset_id')}  有片子={bool(s.get('active_job'))}")
    print(f"\n打开：{B}/?tab=edit&project={PROJECT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
