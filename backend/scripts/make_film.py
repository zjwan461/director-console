"""用「雪地武打片」项目做一条 3 镜头成片（真实出片）。

流程：建 3 个镜头 → 逐镜 t2v 出 5 秒 → 合成 720p 成片。
    cd backend
    python scripts/make_film.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

B = "http://127.0.0.1:6006"
PROJECT = "prj_016a1968910b"  # 雪地武打片
client = httpx.Client(trust_env=False, timeout=120)


def get(path: str, **kwargs):
    """轮询接口偶发连接重置，重试几次再放弃。"""
    last = None
    for _ in range(5):
        try:
            return client.get(B + path, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(3)
    raise last

SHOTS = [
    ("雪夜独行", "雪夜，山门前的石阶上，一名黑衣剑客独自走来，深色劲装、腰间长剑，"
                "风雪卷起地面雪粒，冷蓝月光照亮侧脸，远景缓慢推近"),
    ("拔剑对峙", "雪夜山门前，白衣女子拔剑出鞘，对面黑衣剑客横剑相迎，红衣斗篷被风掀起，"
                "剑刃反光映在雪地上，中景环绕镜头"),
    ("雪地收势", "雪地激战过后，黑衣剑客单膝跪地，长剑斜插入雪中，雪花缓慢飘落，"
                "呼吸带起白雾，低角度特写缓慢推近"),
]


def log(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def wait_job(job_id: str, timeout: int = 1500) -> dict:
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        job = get(f"/api/jobs/{job_id}").json()
        status = job.get("status")
        msg = str(job.get("message") or "")
        if msg and msg != last:
            last = msg
            log(f"    · {msg}")
        if status in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(5)
    return get(f"/api/jobs/{job_id}").json()


def main() -> int:
    project = get("/api/projects").json()["items"]
    target = next((p for p in project if p["id"] == PROJECT), None)
    if not target:
        log(f"项目不存在：{PROJECT}")
        return 1
    log(f"项目：《{target['name']}》 {PROJECT}")

    existing = get(f"/api/projects/{PROJECT}/shots").json().get("items") or []
    if existing:
        log(f"已有 {len(existing)} 个镜头，继续沿用")
        shots = existing
    else:
        shots = []
        for title, prompt in SHOTS:
            shot = client.post(f"{B}/api/shots", json={
                "project_id": PROJECT, "title": title,
                "preset_id": "h3.t2v", "prompt": prompt}).json()
            shots.append(shot)
            log(f"建镜头：{title}（{shot['id']}）")

    finished: dict[str, str] = {}
    jobs = get("/api/jobs?limit=100").json()["items"]
    for job in jobs:
        if job.get("shot_id") and job.get("status") == "succeeded":
            video = next((o for o in (job.get("outputs") or [])
                          if str(o.get("kind")) == "video"), None)
            if video:
                finished[job["shot_id"]] = str(video.get("url"))

    videos: list[str] = []
    for index, (shot, (title, prompt)) in enumerate(zip(shots, SHOTS), start=1):
        if shot["id"] in finished:
            videos.append(finished[shot["id"]])
            log(f"\n[{index}/3] {title} 已有成片，跳过：{finished[shot['id']]}")
            continue
        log(f"\n[{index}/3] {title} 出片中…")
        job = client.post(f"{B}/api/shots/{shot['id']}/generate", json={
            "preset_id": "h3.t2v",
            "values": {"prompt": prompt, "aspect": "16:9", "duration": 5,
                       "megapixels": 0.4},
        })
        if job.status_code >= 400:
            log(f"  提交失败：{job.status_code} {job.text[:160]}")
            return 1
        job = wait_job(job.json()["id"])
        if job.get("status") != "succeeded":
            log(f"  失败：{job.get('status')} {str(job.get('error'))[:200]}")
            return 1
        outputs = job.get("outputs") or []
        video = next((o for o in outputs if str(o.get("kind")) == "video"), None)
        if not video:
            log(f"  没有视频产物：{outputs}")
            return 1
        videos.append(str(video.get("url")))
        log(f"  完成：{videos[-1]}")

    log("\n合成 720p 成片…")
    render = client.post(f"{B}/api/projects/{PROJECT}/renders", json={
        "shot_ids": [s["id"] for s in shots],
        "options": {"width": 1280, "height": 720, "bgm": True, "subtitles": False},
    })
    if render.status_code >= 400:
        log(f"  建草稿失败：{render.status_code} {render.text[:200]}")
        return 1
    render = render.json()
    client.post(f"{B}/api/renders/{render['id']}/start")

    started = time.time()
    while time.time() - started < 900:
        time.sleep(5)
        data = get(f"/api/renders?project_id={PROJECT}").json()["items"]
        current = next((r for r in data if r["id"] == render["id"]), None)
        if not current:
            continue
        log(f"  {current.get('status')} {round(float(current.get('progress') or 0) * 100)}% "
            f"{current.get('message') or ''}")
        if current.get("status") in ("done", "succeeded", "failed", "canceled"):
            if current.get("status") in ("done", "succeeded"):
                log(f"\n成片：{current.get('url')}")
                log(f"剪辑页：{B}/?tab=edit&project={PROJECT}")
                return 0
            log(f"合成失败：{current.get('error')}")
            return 1
    log("合成超时")
    return 1


if __name__ == "__main__":
    sys.exit(main())
