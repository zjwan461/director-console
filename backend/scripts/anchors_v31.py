"""v3.1：把刘义隆/拓跋焘改老、改糙，验证效果。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

B = "http://127.0.0.1:6006"
client = httpx.Client(trust_env=False, timeout=120)

NEG = ("no text, no calligraphy, no plaques, no Chinese characters, no extra people, no bare head, "
       "no modern objects, handsome idol face, beauty filter, smooth flawless skin, glamour lighting, "
       "makeup, k-pop, young man, youthful face, boyish look, twink, clean-shaven model")

STYLE = "写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身："

ANCHORS = {
    "liuyilong_v31": STYLE + "\n"
    "a gaunt, clearly middle-aged Chinese man, 45 years old, with a thin worn face, hollow cheeks and "
    "sunken temples, sallow greyish uneven skin, visible pores, old acne marks and broken capillaries, "
    "heavy dark eye bags, deep forehead lines and deep nasolabial folds, graying stubble, a tired "
    "downturned mouth, thinning hair with grey at the temples, wearing a proper mian crown: a flat "
    "black rectangular board resting on top of his head like a small table, slightly tilted forward, "
    "with only a few short strings of white beads hanging in front of his forehead, black ceremonial "
    "robe with an oversized high white collar, stooped shoulders, anxious and slightly pathetic, "
    "looking like a nervous middle-aged official who has not slept\n"
    "documentary-style hard side light from a candle, harsh shadows under the eyes, oily shine and "
    "sweat on the skin, no beauty retouching, plain grey stone wall background, shallow depth of field\n" + NEG,
    "tuobatao_v31": STYLE + "\n"
    "a lean, worn-out Chinese man, 38 years old but looks older from weather, with a narrow sunburnt "
    "face, peeling windburnt skin, deep crow's feet and forehead creases, chapped lips, uneven patchy "
    "black beard with grey hairs, a small scar through one eyebrow, tired narrow eyes with a smug "
    "unpleasant half-smile, wearing dusty dark lamellar armour with a matted grey fur collar, round "
    "dented helmet, holding a small shabby bundle of dried herbs in his right hand, relaxed arrogant "
    "posture, looking like a smug victorious soldier who has been on campaign for years\n"
    "documentary-style hard light from above, sweat and dust on the forehead, no beauty retouching, "
    "plain grey stone wall background, shallow depth of field\n" + NEG,
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

    for name, prompt in ANCHORS.items():
        job = client.post(B + "/api/jobs", json={
            "preset_id": "image.c16", "project_id": pid,
            "inputs": {"prompt": prompt,
                       "size": {"aspect": "9:16", "megapixels": 1.0}, "seed": -1},
        }).json()
        job = wait_job(job["id"])
        image = next((o for o in job.get("outputs") or [] if str(o.get("kind")) == "image"), None)
        if not image:
            log(f"{name} 失败：{str(job.get('error'))[:160]}")
            return 1
        log(f"{name}: {image.get('url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
