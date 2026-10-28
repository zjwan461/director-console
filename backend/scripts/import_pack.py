"""把用户提供的静帧素材导入素材库，并记录 asset_id 映射。"""

import json
import pathlib
import sys
import time

import httpx

B = "http://127.0.0.1:6006"
SRC = pathlib.Path(r"D:\temp\dabidou_src")
STATE = pathlib.Path(r"D:\workspaces\minimax\director-console\logs\dabidou_pack.json")

FILES = {
    # 锚点
    "anchor_liuyu": "009.png",
    "anchor_yilong": "010.png",
    "anchor_tuoba": "011.png",
    # 母版（备用参考）
    "master_liuyu_close": "001.png",
    "master_two_near": "002.png",
    "master_two_wide": "004.png",
    "master_three": "003.png",
    "master_liuyu_tuoba": "005.png",
    # 分镜静帧
    "a1": "020.png", "a2": "018.png", "a3": "014.png", "a4": "021.png",
    "b1": "025.png", "b2": "024.png",
    "c1": "017.png", "c2": "027.png", "c3": "023.png",
    "d1": "028.png", "d2": "012.png", "d3": "013.png",
}

client = httpx.Client(trust_env=False, timeout=180)


def upload(path: pathlib.Path) -> dict:
    for _ in range(4):
        try:
            with open(path, "rb") as fh:
                resp = client.post(B + "/api/assets/upload",
                                   files={"file": (path.name, fh, "image/png")},
                                   data={"kind": "image"})
            if resp.status_code < 500:
                return resp.json()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise RuntimeError(f"上传失败 {path.name}: {resp.status_code} {resp.text[:120]}")


def main() -> int:
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    for key, name in FILES.items():
        path = SRC / name
        if not path.exists():
            print("missing", name)
            continue
        if state.get(key, {}).get("asset_id"):
            print("skip", key)
            continue
        asset = upload(path)
        state[key] = {"asset_id": asset["id"], "path": asset["path"],
                      "url": f"/media/files/{asset['path']}"}
        print(f"{key}: {asset['id']}  {asset['path'].split('/')[-1]}")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", STATE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
