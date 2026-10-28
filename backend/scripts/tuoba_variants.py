"""拓跋焘·多版挑脸：一次出 5 个变体，挑最"糙"的那张当锚点。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

B = "http://127.0.0.1:6006"
client = httpx.Client(trust_env=False, timeout=120)

NEG = ("no text, no calligraphy, no plaques, no Chinese characters, no extra people, no modern objects, "
       "handsome idol face, beauty filter, smooth flawless skin, glamour lighting, makeup, k-pop, "
       "young man, youthful face, boyish look, clean-shaven model, porcelain skin, pretty face")

STYLE = ("写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身，"
         "documentary-style hard light from above, dust and sweat on skin, no beauty retouching, "
         "plain grey stone wall background, shallow depth of field")

ARMOUR = ("wearing dusty dark lamellar armour with a matted grey fur collar, round dented helmet, "
          "holding a small shabby bundle of dried herbs in his right hand")

VARIANTS = {
    "V1": ("a lean rough Chinese soldier, 38 years old, slightly crooked broken nose, sunburnt peeling "
           "cheeks, old smallpox scars on the jaw, deep crow feet, chapped lips, uneven patchy black "
           "beard with grey strands, scar through one eyebrow, narrow smug eyes, dirty fingernails"),
    "V2": ("a stocky heavy-set Chinese soldier, 40 years old, wide flat face, heavy jowls, small close-set "
           "eyes, wide flattened nose, full untrimmed scruffy black beard covering the jaw, thick neck, "
           "sweaty forehead, smug unpleasant grin, a chipped front tooth"),
    "V3": ("a gaunt hollow-cheeked Chinese soldier, 38 years old, sunken tired eyes with dark circles, "
           "sharp cheekbones, sunburnt flaking skin, greasy strands of hair under the helmet, sparse "
           "crooked yellow teeth, patchy stubble, a long thin scar down one cheek, cold smug squint"),
    "V4": ("a broad-faced Chinese soldier, 39 years old, thick heavy eyebrows almost meeting, big fleshy "
           "nose, deep nasolabial folds, coarse stubbled jaw, one eye slightly squinting from an old "
           "wound, dirty sweat streaks, an unpleasant toothy grin, weathered leathery skin"),
    "V5": ("a tired weather-beaten Chinese soldier, 42 years old, balding under the helmet with a few "
           "grey hairs stuck to the forehead, grey-streaked untrimmed beard, bloodshot eyes, broken "
           "veins on the cheeks, deep wrinkles, missing one tooth, a lazy contemptuous smirk"),
}


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


def wait_job(job_id: str, timeout: int = 1200) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        job = get(f"/api/jobs/{job_id}").json()
        if job.get("status") in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(4)
    return get(f"/api/jobs/{job_id}").json()


def main() -> int:
    items = get("/api/projects").json()["items"]
    project = next((p for p in items if p["name"] == "大逼兜·锚点 v3"), None)
    pid = project["id"] if project else client.post(
        B + "/api/projects", json={"name": "大逼兜·锚点 v3"}).json()["id"]

    for name, face in VARIANTS.items():
        prompt = f"{STYLE}：\n{face}, {ARMOUR}, relaxed arrogant posture\n{NEG}"
        job = client.post(B + "/api/jobs", json={
            "preset_id": "image.c16", "project_id": pid,
            "inputs": {"prompt": prompt,
                       "size": {"aspect": "9:16", "megapixels": 1.0}, "seed": -1},
        }).json()
        job = wait_job(job["id"])
        image = next((o for o in job.get("outputs") or [] if str(o.get("kind")) == "image"), None)
        if not image:
            log(f"{name} 失败：{str(job.get('error'))[:140]}")
            continue
        log(f"{name}: {image.get('url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
