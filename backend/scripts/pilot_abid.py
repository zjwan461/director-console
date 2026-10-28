"""《大逼兜》上集 A1–A3 试跑：出静帧 → 图生视频 → 合成 9:16 小成片。

    cd backend
    python scripts/pilot_abid.py

只跑开场三镜（约 14 秒），用于验证人物造型、手、场景、剪辑点。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

B = "http://127.0.0.1:6006"
PROJECT_NAME = "大逼兜·上集 试跑"
client = httpx.Client(trust_env=False, timeout=120)

STYLE = ("冷调古装短剧，刘宋太庙内殿，石墙与深色木柱，壁龛里放着素面木牌位，"
         "没有任何文字和书法，长柄铜烛台，石台上铜香炉香烟缭绕，烛火为主光，"
         "环境光偏冷，电影感，浅景深，竖屏 9:16")

NEGATIVE = ("画面中不要出现任何文字、匾额、楹联、书法、印章；不要出现多余的侍从路人")

SHOTS = [
    {
        "title": "A1 上香",
        "still": (f"{STYLE}。中景背影：一位四十出头的清瘦男子，苍白肤色，短须，"
                  "头戴黑色冕冠（顶平板、两侧垂珠串），身穿玄色礼服、高白领，"
                  "背对镜头站在香炉前，双手举香行礼，肩背略显拘谨。" + NEGATIVE),
        "motion": "镜头极缓慢向前推近，香烟在烛光里缓缓上升飘动，烛火轻微跳动，"
                  "人物保持举香姿势，只有衣袖和背部有极细微的呼吸起伏，不转头，不转身",
        "duration": 6,
    },
    {
        "title": "A2 拍肩",
        "still": (f"{STYLE}。大特写：画面只出现一个人的右肩与袖口，"
                  "深灰黑色旧长袍（洗得发白但完好）、褐色革带边缘，"
                  "袖口布料粗糙；一只布满皱纹的老年男性手掌从画面右侧伸入，"
                  "轻轻悬在肩头上方，手指自然微曲。" + NEGATIVE),
        "motion": "那只苍老的手从画外缓慢伸入，轻轻落在肩上，指尖微微下压，"
                  "袖口布料随之轻晃；镜头几乎不动，只有极轻微的呼吸感",
        "duration": 4,
    },
    {
        "title": "A3 回头",
        "still": (f"{STYLE}。近景：四十出头的清瘦男子，苍白肤色，短须，"
                  "黑色冕冠（顶平板、两侧垂珠串），玄色礼服、高白领，"
                  "正侧过身猛回头，眼睛睁大、嘴唇微张，神情惊愕，视线看向画面左前方，"
                  "不看镜头，冕冠垂珠因转身轻轻摆动。" + NEGATIVE),
        "motion": "人物从侧身快速回头转向镜头左前方，冕冠垂珠随之晃动，"
                  "眼睛睁大、瞳孔微颤，呼吸急促，镜头保持不动只有轻微手持感",
        "duration": 4,
    },
]


def log(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def get(path: str, **kwargs):
    last = None
    for _ in range(6):
        try:
            return client.get(B + path, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(3)
    raise last


def wait_job(job_id: str, timeout: int = 2400) -> dict:
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        job = get(f"/api/jobs/{job_id}").json()
        msg = str(job.get("message") or "")
        if msg and msg != last:
            last = msg
            log(f"      · {msg}")
        if job.get("status") in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(6)
    return get(f"/api/jobs/{job_id}").json()


def submit(payload: dict) -> dict:
    resp = client.post(B + "/api/jobs", json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"提交失败 {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def ensure_project() -> str:
    items = get("/api/projects").json()["items"]
    found = next((p for p in items if p["name"] == PROJECT_NAME), None)
    if found:
        return found["id"]
    project = client.post(B + "/api/projects", json={"name": PROJECT_NAME}).json()
    return project["id"]


def main() -> int:
    project_id = ensure_project()
    log(f"项目：{PROJECT_NAME}（{project_id}）")

    existing = get(f"/api/projects/{project_id}/shots").json().get("items") or []
    shots = {s["title"]: s for s in existing}
    results = []

    for index, spec in enumerate(SHOTS, start=1):
        title = spec["title"]
        log(f"\n[{index}/3] {title}")

        shot = shots.get(title)
        if not shot:
            shot = client.post(B + "/api/shots", json={
                "project_id": project_id, "title": title, "preset_id": "h3.i2v",
            }).json()
        shot_id = shot["id"]

        # 已经有成功视频就跳过（可重复运行）
        jobs = get("/api/jobs?limit=100").json()["items"]
        done = next((j for j in jobs if j.get("shot_id") == shot_id
                     and j.get("status") == "succeeded"
                     and any(str(o.get("kind")) == "video" for o in (j.get("outputs") or []))), None)
        if done:
            video = next(o for o in done["outputs"] if str(o.get("kind")) == "video")
            log(f"   已有成片，跳过：{video.get('url')}")
            results.append({"title": title, "shot_id": shot_id, "video": video.get("url")})
            continue

        log("   1/2 出静帧…")
        image_job = submit({
            "preset_id": "image.c16",
            "project_id": project_id,
            "inputs": {"prompt": spec["still"],
                       "size": {"aspect": "9:16", "megapixels": 0.8},
                       "seed": -1},
        })
        image_job = wait_job(image_job["id"])
        if image_job.get("status") != "succeeded":
            log(f"   静帧失败：{image_job.get('status')} {str(image_job.get('error'))[:200]}")
            return 1
        image = next((o for o in image_job.get("outputs") or []
                      if str(o.get("kind")) == "image"), None)
        if not image:
            log("   静帧没有产物")
            return 1
        log(f"   静帧：{image.get('url')}")

        log("   2/2 图生视频…")
        video_job = submit({
            "preset_id": "h3.i2v",
            "project_id": project_id,
            "shot_id": shot_id,
            "inputs": {"first_frame": image["asset_id"],
                       "prompt": spec["motion"],
                       "size": {"aspect": "9:16", "megapixels": 0.4},
                       "duration": spec["duration"]},
        })
        video_job = wait_job(video_job["id"])
        if video_job.get("status") != "succeeded":
            log(f"   视频失败：{video_job.get('status')} {str(video_job.get('error'))[:300]}")
            return 1
        video = next((o for o in video_job.get("outputs") or []
                      if str(o.get("kind")) == "video"), None)
        if not video:
            log("   视频没有产物")
            return 1
        client.post(B + f"/api/shots/{shot_id}/activate-take",
                    json={"job_id": video_job["id"]})
        client.patch(B + f"/api/shots/{shot_id}", json={"cover": image.get("url")})
        log(f"   完成：{video.get('url')}")
        results.append({"title": title, "shot_id": shot_id, "video": video.get("url")})

    log("\n合成 9:16 成片…")
    shot_ids = [r["shot_id"] for r in results]
    render = client.post(B + f"/api/projects/{project_id}/renders", json={
        "shot_ids": shot_ids,
        "options": {"width": 720, "height": 1280, "bgm": False, "subtitles": False},
    })
    if render.status_code >= 400:
        log(f"  建草稿失败：{render.status_code} {render.text[:200]}")
        return 1
    render = render.json()
    client.post(B + f"/api/renders/{render['id']}/start")

    started = time.time()
    while time.time() - started < 900:
        time.sleep(5)
        items = get(f"/api/renders?project_id={project_id}").json()["items"]
        current = next((r for r in items if r["id"] == render["id"]), None)
        if not current:
            continue
        log(f"  {current.get('status')} {round(float(current.get('progress') or 0) * 100)}%")
        if current.get("status") in ("done", "succeeded", "failed", "canceled"):
            if current.get("status") in ("done", "succeeded"):
                log(f"\n成片：{current.get('url')}")
                log(f"项目页：{B}/?tab=edit&project={project_id}")
                return 0
            log(f"合成失败：{current.get('error')}")
            return 1
    log("合成超时")
    return 1


if __name__ == "__main__":
    sys.exit(main())
