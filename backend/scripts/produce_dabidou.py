"""《大逼兜》上集 v1 · 全自动生产（可中断续跑）。

    1) 出三张角色锚点
    2) 出 8 张首帧
    3) 出 11 段视频（i2v / flf2v / r2v9）
    4) 组装 + 字幕 + BGM + 片头片尾 + 导出

    运行：cd backend && python scripts/produce_dabidou.py
    产物不进 git（data/outputs、data/renders 已忽略）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

B = "http://127.0.0.1:6006"
STATE_PATH = Path(__file__).resolve().parents[2] / "logs" / "dabidou_state.json"
PROJECT_NAME = "《大逼兜》上集 v1"
MUSIC_ASSET = "ast_39b0fc0d4f19"  # 燃_Volatile Reaction

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dabidou_prompts import (  # noqa: E402
    A3_PROMPT_PLAIN, A4_PROMPT, B1_PROMPT, B2_PROMPT, C1_PROMPT_PLAIN, C2_PROMPT_PLAIN,
    C3_PROMPT, D1_PROMPT_PLAIN, D2_PROMPT, D3_PROMPT,
)

client = httpx.Client(trust_env=False, timeout=180)

NEG = ("no text, no calligraphy, no plaques, no banners, no Chinese characters anywhere, "
       "no extra people, no modern objects, handsome idol face, beauty filter, smooth flawless skin, "
       "glamour lighting, makeup, k-pop, young man, youthful face, boyish look, porcelain skin")

# ---------------- 锚点 ----------------
ANCHORS = {
    "yilong": (
        "写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身：\n"
        "a gaunt, clearly middle-aged Chinese man, 45 years old, thin worn face with hollow cheeks and "
        "sunken temples, sallow greyish uneven skin, visible pores and old acne marks, heavy dark eye bags, "
        "deep forehead lines and deep nasolabial folds, graying stubble, a tired downturned mouth, thinning "
        "hair with grey at the temples, wearing a proper mian crown: a flat black rectangular board resting "
        "on top of his head like a small table, slightly tilted forward, with only a few short strings of "
        "white beads hanging in front of his forehead, black ceremonial robe with an oversized high white "
        "collar, stooped shoulders, anxious and slightly pathetic\n"
        "documentary-style hard side light from a candle, harsh shadows under the eyes, oily shine on the "
        "skin, no beauty retouching, plain grey stone wall background, shallow depth of field\n" + NEG),
    "liuyu": (
        "写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身：\n"
        "a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, high cheekbones, "
        "deep wrinkles across the forehead and around the mouth, coarse weathered skin with age spots and "
        "stubble, messy grey-streaked beard, thinning hair tied back with a dark cloth, small hard eyes, "
        "wearing a plain dark grey-black long robe that is worn but completely intact, brown leather belt, "
        "no sword, hands clasped behind his back, straight back, chin slightly raised, cold tired "
        "intimidating expression like an old soldier who has killed people\n"
        "harsh candlelight from the side, deep shadows in the eye sockets, no beauty retouching, plain grey "
        "stone wall background, shallow depth of field\n" + NEG),
    "tuoba": (
        "写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身：\n"
        "A Chinese man in his late thirties, tall and broad-shouldered, lean but strong boned, a hard "
        "masculine face with a square jaw, high cheekbones, thick straight brows, deep-set stern eyes "
        "looking straight at the camera, a short trimmed black beard, weathered sunburnt skin with a faint "
        "old scar on one cheekbone, hair in a tight topknot, wearing dark lamellar armour with a dusty grey "
        "fur collar and a simple leather cap, stern serious expression, mouth closed, jaw set, no smile, "
        "imposing and calm\n"
        "documentary-style hard light from above, dust and sweat on the skin, no beauty retouching, plain "
        "grey stone wall background, shallow depth of field\n"
        "no text, no calligraphy, no plaques, no Chinese characters, no extra people, no modern objects, "
        "feminine features, soft delicate face, eyeliner, glossy eyes, pretty boy, idol face, beauty filter, "
        "smooth flawless skin, glamour lighting, makeup, smile"),
}

SCENE = ("冷调古装短剧，写实，非美型，竖屏，太庙内殿：灰色石墙、深色木柱、壁龛里竖着几块素面空白木牌位"
         "（木牌完全空白、没有任何刻字）、长柄铜烛台点着小火苗、石台上一个旧铜香炉冒着细香烟，"
         "冷色环境光，纪录片质感，浅景深，")

YILONG_FACE = ("a gaunt middle-aged Chinese man of 45, sallow greyish uneven skin, visible pores and old "
               "acne marks, heavy dark eye bags, deep nasolabial folds, graying stubble")
YILONG_FACE_SHORT = ("a gaunt middle-aged Chinese man of 45, hollow cheeks, sallow greyish skin, heavy "
                     "eye bags, graying stubble")
YILONG_CROWN = ("black ceremonial crown with a flat rectangular board on top and short bead strings, "
                "black ceremonial robe with an oversized high white collar")
LIUYU_FACE = ("a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, deep "
              "wrinkles, messy grey-streaked beard, plain dark grey-black robe worn but intact, brown "
              "leather belt, no sword, hands clasped behind his back, straight back, cold expression")
TUOBA_FACE = ("a tall broad-shouldered Chinese man of 38 with a hard square-jawed masculine face, thick "
              "straight brows, deep-set stern eyes, short trimmed black beard, weathered skin with a faint "
              "scar, dusty dark lamellar armour with a grey fur collar, simple leather cap, stern and "
              "unsmiling")

# ---------------- 首帧 ----------------
STILLS = {
    "a1": (SCENE + "中景背影偏侧：" + YILONG_FACE_SHORT + "，" + YILONG_CROWN + "，standing with his back "
           "mostly to the camera, both hands holding three incense sticks up in front of his chest, stiff "
           "hunched posture, shoulders raised\n" + NEG),
    "a2": ("冷调古装短剧，写实，非美型，竖屏，太庙内殿，冷环境光，纪录片质感，浅景深\n"
           "大特写：画面里只出现一个人的右肩和袖口，a plain dark grey-black robe sleeve, worn but "
           "completely intact with no tears, coarse slightly dirty fabric, brown leather belt edge visible "
           "at the bottom；一只粗糙的老年男性手掌从画面右侧伸进来：干裂皮肤、指关节突出、指甲缝里有灰、"
           "手背青筋和老年斑明显，轻轻悬在肩上，手指自然微曲\n" + NEG),
}

# ---------------- 视频 ----------------
VIDEOS = {
    "a1": {"preset": "h3.i2v", "still": "a1", "duration": 6, "mp": 0.4, "title": "A1 上香",
           "prompt": "Static camera with a very slow push in. The man stands at the bronze incense burner, "
                     "seen from behind at a three-quarter angle, both hands holding the incense sticks over the "
                     "burner. Incense smoke drifts upward slowly, candle flames flicker gently. Only his sleeve, "
                     "his hands and his back show a very slight breathing motion. He does not turn around, does "
                     "not look at the camera, and does not speak. Ambient temple room tone, faint wind."},
    "a2": {"preset": "h3.i2v", "still": "a2", "duration": 4, "mp": 0.4, "title": "A2 拍肩",
           "prompt": "Extreme close-up on the shoulder and the sleeve, static camera. ONLY ONE elderly hand "
                     "enters from the right edge and settles on the shoulder; that is the only hand visible in "
                     "the whole shot. The man's own hands stay completely out of frame behind his back. No "
                     "second hand, no duplicate arm, no extra fingers, no ghost limbs, no hand entering twice. "
                     "The fingertips press down lightly once and stay still; the coarse sleeve fabric shifts a "
                     "little. Nothing else in frame moves. Soft cloth rustle, distant wind."},
    "a3": {"preset": "h3.r2v", "refs": ["yilong"], "duration": 4, "mp": 0.7, "title": "A3 回头",
           "prompt": A3_PROMPT_PLAIN},
    "a4": {"preset": "h3.r2v9", "refs": ["yilong", "liuyu"], "duration": 8, "mp": 0.7, "title": "A4 爹",
           "prompt": A4_PROMPT},
    "b1": {"preset": "h3.r2v9", "refs": ["yilong", "liuyu"], "duration": 10, "mp": 0.7, "title": "B1 北伐",
           "prompt": B1_PROMPT},
    "b2": {"preset": "h3.r2v9", "refs": ["yilong", "liuyu"], "duration": 8, "mp": 0.7, "title": "B2 二百多天",
           "prompt": B2_PROMPT},
    "c1": {"preset": "h3.r2v", "refs": ["yilong", "liuyu"], "duration": 6, "mp": 0.7, "title": "C1 长江",
           "prompt": C1_PROMPT_PLAIN},
    "c2": {"preset": "h3.r2v", "refs": ["tuoba"], "duration": 7, "mp": 0.7, "title": "C2 拓跋焘出场",
           "prompt": C2_PROMPT_PLAIN},
    "c3": {"preset": "h3.r2v9", "refs": ["yilong", "liuyu", "tuoba"], "duration": 9, "mp": 0.7,
           "title": "C3 三人", "prompt": C3_PROMPT},
    "d1": {"preset": "h3.r2v", "refs": ["liuyu"], "duration": 10, "mp": 0.7, "title": "D1 两千七百人",
           "prompt": D1_PROMPT_PLAIN},
    "d2": {"preset": "h3.u22", "refs": ["liuyu", "yilong"], "duration": 4, "mp": 0.7, "title": "D2 一巴掌",
           "prompt": D2_PROMPT},
    "d3": {"preset": "h3.u22", "refs": ["yilong", "liuyu"], "duration": 4, "mp": 0.7, "title": "D3 跑了",
           "prompt": D3_PROMPT},
}

ORDER = ["a1", "a2", "a3", "a4", "b1", "b2", "c1", "c2", "c3", "d1", "d2", "d3"]

SUBTITLES = {
    "a1": None, "a2": None, "a3": None,
    "a4": "爹。",
    "b1": "听说你又北伐了？打到长安了吗？",
    "b2": "围了多久？",
    "c1": "他退到长江了。",
    "c2": "听说你吓病了。给你带了点药。",
    "c3": "滚滚滚，谁要你的药。",
    "d1": "我当年两千七百人，破过他爹三万骑兵。",
    "d2": None,
    "d3": None,
}


def log(msg: str) -> None:
    sys.stdout.buffer.write((time.strftime("%H:%M:%S ") + msg + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"project_id": "", "anchors": {}, "stills": {}, "videos": {}, "shots": {}, "render_id": ""}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def get(path: str, **kwargs) -> httpx.Response:
    last: Exception | None = None
    for _ in range(6):
        try:
            resp = client.get(B + path, **kwargs)
            if resp.status_code < 500:
                return resp
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(3)
    if last:
        raise last
    return client.get(B + path, **kwargs)


def post(path: str, payload: dict | None = None, **kwargs) -> httpx.Response:
    last: Exception | None = None
    for _ in range(6):
        try:
            resp = client.post(B + path, json=payload, **kwargs)
            if resp.status_code < 500:
                return resp
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(3)
    if last:
        raise last
    return client.post(B + path, json=payload, **kwargs)


def wait_job(job_id: str, timeout: int = 3600) -> dict:
    started = time.time()
    last_msg = ""
    while time.time() - started < timeout:
        job = get(f"/api/jobs/{job_id}").json()
        status = job.get("status")
        msg = str(job.get("message") or "")
        if msg and msg != last_msg and not msg.startswith("生成中"):
            last_msg = msg
            log(f"      {msg}")
        if status in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(6)
    return get(f"/api/jobs/{job_id}").json()


def submit(preset: str, inputs: dict, shot_id: str = "", project_id: str = "") -> dict:
    resp = post("/api/jobs", {"preset_id": preset, "project_id": project_id,
                              "shot_id": shot_id, "inputs": inputs})
    if resp.status_code >= 400:
        raise RuntimeError(f"提交失败 {preset}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def image_output(job: dict) -> dict | None:
    return next((o for o in job.get("outputs") or [] if str(o.get("kind")) == "image"), None)


def video_output(job: dict) -> dict | None:
    return next((o for o in job.get("outputs") or [] if str(o.get("kind")) == "video"), None)


def ensure_project(state: dict) -> str:
    items = get("/api/projects").json()["items"]
    if state.get("project_id") and any(p["id"] == state["project_id"] for p in items):
        return state["project_id"]
    if state.get("project_id"):
        log("原项目已不存在，重建（素材仍在库里，会复用）")
        state["shots"] = {}
        state["render_id"] = ""
    found = next((p for p in items if p["name"] == PROJECT_NAME), None)
    if found:
        state["project_id"] = found["id"]
    else:
        state["project_id"] = post("/api/projects", {"name": PROJECT_NAME}).json()["id"]
    save_state(state)
    return state["project_id"]


def generate_image(state: dict, key: str, prompt: str, mp: float) -> str:
    cached = state["anchors"].get(key) if key in ANCHORS else state["stills"].get(key)
    if cached:
        return cached
    job = submit("image.c16", {"prompt": prompt, "size": {"aspect": "9:16", "megapixels": mp},
                               "seed": -1}, project_id=state["project_id"])
    job = wait_job(job["id"])
    image = image_output(job)
    if not image:
        raise RuntimeError(f"{key} 出图失败：{job.get('status')} {str(job.get('error'))[:200]}")
    if key in ANCHORS:
        state["anchors"][key] = image["asset_id"]
    else:
        state["stills"][key] = image["asset_id"]
    state.setdefault("urls", {})[key] = image.get("url")
    save_state(state)
    return image["asset_id"]


PACK_PATH = Path(__file__).resolve().parents[2] / "logs" / "dabidou_pack.json"


def apply_pack(state: dict) -> None:
    """用用户提供的静帧素材替换自动生成的锚点与无脸静帧。"""
    if not PACK_PATH.exists():
        return
    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    mapping = {"yilong": "anchor_yilong", "liuyu": "anchor_liuyu", "tuoba": "anchor_tuoba"}
    for name, key in mapping.items():
        if pack.get(key):
            state["anchors"][name] = pack[key]["asset_id"]
            state.setdefault("urls", {})[key] = pack[key]["url"]
    for name in ("a1", "a2"):
        if pack.get(name):
            state["stills"][name] = pack[name]["asset_id"]
            state.setdefault("urls", {})[name] = pack[name]["url"]
    save_state(state)
    log("已套用用户静帧素材（3 锚点 + A1/A2 静帧）")


def produce() -> int:
    state = load_state()
    apply_pack(state)
    pid = ensure_project(state)
    log(f"项目 {PROJECT_NAME}（{pid}）")

    # 1) 锚点
    for key, prompt in ANCHORS.items():
        if key in state["anchors"]:
            log(f"锚点 {key} 已有，跳过")
            continue
        log(f"锚点 {key} 出图中…")
        generate_image(state, key, prompt, 1.0)
        log(f"  完成 {state['urls'].get(key)}")

    # 2) 首帧
    for key, prompt in STILLS.items():
        if key in state["stills"]:
            log(f"首帧 {key} 已有，跳过")
            continue
        log(f"首帧 {key} 出图中…")
        generate_image(state, key, prompt, 0.8)
        log(f"  完成 {state['urls'].get(key)}")

    if STAGE == "stills":
        log("\n首帧全部出完，等待用户过目后再生成视频。")
        log(f"项目页：{B}/?tab=edit&project={pid}")
        return 0

    # 3) 视频（可用 DABIDOU_ONLY=a1,a2 只跑指定镜）
    only = [k.strip() for k in (os.environ.get("DABIDOU_ONLY") or "").split(",") if k.strip()]
    for key in (only or ORDER):
        if key not in VIDEOS:
            log(f"跳过未知镜头 {key}")
            continue
        spec = VIDEOS[key]
        if state["videos"].get(key, {}).get("url"):
            log(f"视频 {key} 已有，跳过")
            continue
        title = spec["title"]
        shot_id = state["shots"].get(key)
        if not shot_id:
            shot = post("/api/shots", {"project_id": pid, "title": title,
                                       "preset_id": spec["preset"]}).json()
            shot_id = shot["id"]
            state["shots"][key] = shot_id
            save_state(state)

        size = {"aspect": "9:16", "megapixels": spec["mp"]}
        if spec["preset"] in ("h3.r2v9", "h3.r2v", "h3.u22"):
            inputs: dict = {"prompt": spec["prompt"], "size": size, "duration": spec["duration"]}
            for index, ref in enumerate(spec["refs"], start=1):
                inputs[f"ref_{index}"] = state["anchors"][ref]
        elif spec["preset"] == "h3.flf2v":
            asset = state["stills"][spec["still"]]
            inputs = {"first_frame": asset, "last_frame": asset, "prompt": spec["prompt"],
                      "size": size, "duration": spec["duration"]}
        else:
            inputs = {"first_frame": state["stills"][spec["still"]], "prompt": spec["prompt"],
                      "size": size, "duration": spec["duration"]}

        log(f"视频 {key}（{title}）提交中… 预计 {spec['duration']}s")
        job = submit(spec["preset"], inputs, shot_id=shot_id, project_id=pid)
        job = wait_job(job["id"])
        video = video_output(job)
        if not video:
            log(f"  失败：{job.get('status')} {str(job.get('error'))[:300]}")
            return 1
        post(f"/api/shots/{shot_id}/activate-take", {"job_id": job["id"]})
        cover_url = state["urls"].get(spec.get("still", "")) or state["urls"].get(key)
        if cover_url:
            client.patch(B + f"/api/shots/{shot_id}", json={"cover": cover_url})
        state["videos"][key] = {"url": video["url"], "job_id": job["id"]}
        save_state(state)
        log(f"  完成 {video['url']}")

    # 4) 合成
    shot_ids = [state["shots"][key] for key in ORDER if state["shots"].get(key)]
    edits = []
    for key in ORDER:
        text = SUBTITLES.get(key)
        edit = {"shot_id": state["shots"][key], "narration_on": False}
        if text:
            edit["subtitle"] = text
        else:
            edit["burned_subtitle"] = True  # 抑制「镜头名烧字」
        edits.append(edit)

    options = {
        "width": 720, "height": 1280, "fps": 24,
        "subtitles": {"enabled": True, "position": "bottom"},
        "title": {"enabled": True, "text": "《大逼兜》上集", "duration": 1.5},
        "tail": {"enabled": True, "text": "上集 · 完", "duration": 3},
        "bgm_tracks": [{"asset_id": MUSIC_ASSET, "volume_db": -20, "start": 12,
                        "fade_in": 1.5, "fade_out": 2, "loop": True}],
    }
    log("合成成片中…")
    render = post(f"/api/projects/{pid}/renders",
                  {"shot_ids": shot_ids, "options": options, "shot_edits": edits})
    if render.status_code >= 400:
        log(f"建草稿失败：{render.status_code} {render.text[:200]}")
        return 1
    render = render.json()
    state["render_id"] = render["id"]
    save_state(state)
    post(f"/api/renders/{render['id']}/start")

    started = time.time()
    while time.time() - started < 1200:
        time.sleep(5)
        items = get(f"/api/renders?project_id={pid}").json()["items"]
        current = next((r for r in items if r["id"] == render["id"]), None)
        if not current:
            continue
        log(f"  {current.get('status')} {round(float(current.get('progress') or 0) * 100)}%")
        if current.get("status") in ("succeeded", "done"):
            log(f"\n成片：{current.get('output_url')}")
            log(f"项目页：{B}/?tab=edit&project={pid}")
            return 0
        if current.get("status") in ("failed", "canceled"):
            log(f"合成失败：{current.get('error')}")
            return 1
    log("合成超时")
    return 1


STAGE = ("stills" if "--stills" in sys.argv
         else "videos" if "--videos" in sys.argv
         else "all")

if __name__ == "__main__":
    sys.exit(produce())
