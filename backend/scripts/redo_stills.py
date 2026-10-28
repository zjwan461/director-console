"""重出 4 张有问题的首帧：A1（冠错）、A3（冕帘太长）、C2（帽子错/太暗）、D2（冕帘遮脸/动作不清）。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

B = "http://127.0.0.1:6006"
STATE_PATH = Path(__file__).resolve().parents[2] / "logs" / "dabidou_state.json"
client = httpx.Client(trust_env=False, timeout=180)

NEG = ("no text, no calligraphy, no plaques, no banners, no Chinese characters anywhere, "
       "no extra people, no modern objects, handsome idol face, beauty filter, smooth flawless skin, "
       "glamour lighting, makeup, k-pop, young man, youthful face, boyish look, porcelain skin")

SCENE = ("冷调古装短剧，写实，非美型，竖屏，太庙内殿：灰色石墙、深色木柱、壁龛里竖着几块素面空白木牌位"
         "（木牌完全空白、没有任何刻字）、长柄铜烛台点着小火苗、石台上一个旧铜香炉冒着细香烟，"
         "冷色环境光，纪录片质感，浅景深，")

YILONG = ("a gaunt middle-aged Chinese man of 45, sallow greyish uneven skin, visible pores, heavy dark eye "
          "bags, deep nasolabial folds, graying stubble")

CROWN = ("black mian crown: a flat black rectangular board resting on top of the head like a small table, "
         "with only TWO short strings of white beads that end just above the eyebrows, not covering the face")

TUOBA = ("a tall broad-shouldered Chinese man of 38 with a hard square-jawed masculine face, thick straight "
         "brows, deep-set stern eyes, short trimmed black beard, weathered skin with a faint scar, wearing "
         "dark lamellar armour with a grey fur collar and a soft round dark leather cap with no fur trim")

REDO = {
    "a1": (SCENE + "中景背影偏侧，可以看到他的后脑和侧脸：" + YILONG + "，" + CROWN +
           "，black ceremonial robe with an oversized high white collar, standing with his back mostly to "
           "the camera, both hands holding three incense sticks up in front of his chest, stiff hunched "
           "posture\n" + NEG),
    "a3": (SCENE + "近景：" + YILONG + "，" + CROWN + "，black ceremonial robe with an oversized high white "
           "collar, body turned sharply to look over his right shoulder, eyes wide with panic, mouth "
           "slightly open, looking toward the left edge of the frame, NOT looking at the camera\n" + NEG),
    "c2": ("冷调古装短剧，写实，非美型，竖屏，太庙内殿侧廊：深色木柱之间有一道阴影，背景是灰石墙和虚化烛火，"
           "暖色火把从侧面照亮半边脸，记录片质感，浅景深\n中景：" + TUOBA + "，holding a small shabby bundle "
           "of dried herbs in his right hand, walking out of the shadow toward the camera, stern serious "
           "expression, mouth closed, the face clearly visible and well lit\n" + NEG),
    "d2": (SCENE + "双人中景，动作正在进行中：\n画面左侧 a weathered ordinary-looking Chinese man in his mid "
           "sixties, broad rough face, deep wrinkles, messy grey-streaked beard, dark grey-black robe, right "
           "arm fully raised with palm open, body weight forward\n画面右侧 " + YILONG + "，" + CROWN +
           "，black ceremonial robe with an oversized high white collar, head already snapping sideways to the "
           "right, one hand half-raised too late in defence, mouth open in shock, his face fully visible and "
           "not covered by beads\n两人距离很近，衣料被带起来，没有慢动作感\n" + NEG),
}


def log(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def get(path: str, **kwargs):
    for _ in range(6):
        try:
            resp = client.get(B + path, **kwargs)
            if resp.status_code < 500:
                return resp
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    return client.get(B + path, **kwargs)


def wait_job(job_id: str, timeout: int = 1800) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        job = get(f"/api/jobs/{job_id}").json()
        if job.get("status") in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(5)
    return get(f"/api/jobs/{job_id}").json()


def main() -> int:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    pid = state["project_id"]
    for key, prompt in REDO.items():
        log(f"重出 {key}…")
        resp = client.post(B + "/api/jobs", json={
            "preset_id": "image.c16", "project_id": pid,
            "inputs": {"prompt": prompt, "size": {"aspect": "9:16", "megapixels": 0.8}, "seed": -1}})
        if resp.status_code >= 400:
            log(f"  提交失败 {resp.status_code} {resp.text[:160]}")
            return 1
        job = wait_job(resp.json()["id"])
        image = next((o for o in job.get("outputs") or [] if str(o.get("kind")) == "image"), None)
        if not image:
            log(f"  失败 {job.get('status')} {str(job.get('error'))[:160]}")
            return 1
        state["stills"][key] = image["asset_id"]
        state["urls"][key] = image.get("url")
        log(f"  新图 {image.get('url')}")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    log("已更新 state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
