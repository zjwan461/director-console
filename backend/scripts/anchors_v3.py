"""验证 v3「去美型」锚点提示词：出三张锚点图看脸。"""
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
       "makeup, young pop star, k-pop")

STYLE = ("写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身：")

ANCHORS = {
    "liuyilong": STYLE + "\n"
    "an ordinary-looking Chinese man in his mid forties, thin face with hollow cheeks, sallow uneven "
    "skin, visible pores and slight blemishes, dark circles under tired eyes, deep nasolabial folds, "
    "thin sparse beard, slightly receding hairline, wearing a black ceremonial crown with a flat "
    "rectangular board on top and short strings of white beads hanging to his eyebrows, black "
    "ceremonial robe with a high white collar that looks a bit too big for him, stooped shoulders, "
    "anxious and slightly pathetic expression, looking like a nervous middle-aged civil servant\n"
    "documentary-style hard side light from a candle, shadows on the face, some oily shine on the skin, "
    "no beauty retouching, plain grey stone wall background, shallow depth of field\n" + NEG,
    "liuyu": STYLE + "\n"
    "a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, high cheekbones, "
    "deep wrinkles across the forehead and around the mouth, coarse weathered skin with age spots and "
    "stubble, messy grey-streaked beard, thinning hair tied back with a dark cloth, small hard eyes, "
    "wearing a plain dark grey-black long robe that is worn but completely intact, brown leather belt, "
    "no sword, hands clasped behind his back, straight back, chin slightly raised, cold tired "
    "intimidating expression like an old soldier who has killed people\n"
    "harsh candlelight from the side, deep shadows in the eye sockets, no beauty retouching, plain grey "
    "stone wall background, shallow depth of field\n" + NEG,
    "tuobatao": STYLE + "\n"
    "a lean ordinary-looking Chinese man in his late thirties, narrow weathered sunburnt face, "
    "sunburnt uneven skin, a small scar on one cheekbone, short patchy black beard, crooked front "
    "tooth showing in a cocky half-smile, wearing dark lamellar armour with a grey fur collar that "
    "looks dusty and used, round helmet slightly dented, holding a small shabby bundle of herbs in "
    "his right hand, relaxed arrogant posture, looking like a smug victorious soldier\n"
    "documentary-style hard light from above, sweat shine on the forehead, no beauty retouching, "
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
    if not project:
        project = client.post(B + "/api/projects", json={"name": "大逼兜·锚点 v3"}).json()
    pid = project["id"]
    log(f"项目：{pid}")

    for name, prompt in ANCHORS.items():
        job = client.post(B + "/api/jobs", json={
            "preset_id": "image.c16", "project_id": pid,
            "inputs": {"prompt": prompt,
                       "size": {"aspect": "9:16", "megapixels": 1.0}, "seed": -1},
        }).json()
        job = wait_job(job["id"])
        image = next((o for o in job.get("outputs") or [] if str(o.get("kind")) == "image"), None)
        if not image:
            log(f"{name} 失败：{str(job.get('error') or job.get('outputs'))[:160]}")
            return 1
        log(f"{name}: {image.get('url')}")
    log("项目页：%s/?tab=edit&project=%s" % (B, pid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
