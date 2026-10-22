"""下载内置 BGM 素材（CC BY 4.0，Kevin MacLeod）。

用法：
    python scripts/fetch_music.py                        # 直连
    python scripts/fetch_music.py --proxy http://ip:port  # 走代理

下载到 data/uploads/music/ 并注册进资产库（需要后端能连数据库，可离线执行）。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import urllib.parse
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MUSIC_DIR = DATA / "uploads" / "music"
IDENT = "KevinMacLeod_2019-04_Discography"

TRACKS = [
    ("轻快", "Monkeys Spinning Monkeys", "Kevin MacLeod/Royalty Free/Kevin MacLeod - 00 - Monkeys Spinning Monkeys.mp3"),
    ("轻快", "Happy Alley", "Kevin MacLeod/Somewhere Sunny/Kevin MacLeod - 03 - Happy Alley.mp3"),
    ("轻快", "Life of Riley", "Kevin MacLeod/Royalty Free/Kevin MacLeod - 00 - Life of Riley.mp3"),
    ("搞笑", "Sneaky Snitch", "Kevin MacLeod/Mystery/Kevin MacLeod - 11 - Sneaky Snitch.mp3"),
    ("搞笑", "Fluffing a Duck", "Kevin MacLeod/Oddities/Kevin MacLeod - 05 - Fluffing a Duck.mp3"),
    ("燃", "Volatile Reaction", "Kevin MacLeod/Action Cuts/Kevin MacLeod - 26 - Volatile Reaction.mp3"),
    ("燃", "Five Armies", "Kevin MacLeod/The Descent/Kevin MacLeod - 12 - Five Armies.mp3"),
    ("史诗", "Achilles", "Kevin MacLeod/Royalty Free/Kevin MacLeod - 00 - Achilles.mp3"),
    ("治愈", "Continue Life", "Kevin MacLeod/Healing/Kevin MacLeod - 04 - Continue Life.mp3"),
    ("治愈", "Gymnopedie No 1", "Kevin MacLeod/Royalty Free/Kevin MacLeod - 00 - Gymnopedie No 1.mp3"),
    ("治愈", "Carefree", "Kevin MacLeod/Calming/Kevin MacLeod - 04 - Carefree.mp3"),
    ("电子", "Digital Lemonade", "Kevin MacLeod/Royalty Free/Kevin MacLeod - 00 - Digital Lemonade.mp3"),
    ("电子", "Pamgaea", "Kevin MacLeod/Light Electronic/Kevin MacLeod - 08 - Pamgaea.mp3"),
    ("悬念", "Ominous", "Kevin MacLeod/Mystery/Kevin MacLeod - 06 - Ominous.mp3"),
]


def download(proxy: str, skip_existing: bool = True) -> int:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(trust_env=False, proxy=proxy or None, timeout=180,
                          follow_redirects=True, verify=False)
    count = 0
    for mood, title, path in TRACKS:
        safe = re.sub(r'[\\/:*?"<>|]', "", title).strip()
        target = MUSIC_DIR / f"{mood}_{safe}.mp3"
        if skip_existing and target.exists() and target.stat().st_size > 200_000:
            print(f"skip  {target.name}")
            count += 1
            continue
        url = f"https://archive.org/download/{IDENT}/" + urllib.parse.quote(path)
        try:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with target.open("wb") as fh:
                    for chunk in resp.iter_bytes(65536):
                        fh.write(chunk)
            print(f"ok    {target.name}  {target.stat().st_size / 1048576:.1f}MB")
            count += 1
        except Exception as exc:
            print(f"fail  {title}: {type(exc).__name__} {str(exc)[:80]}")
    return count


def register() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app import ffmpeg, store  # noqa: PLC0415

    known = {a["path"] for a in store.list_assets("audio", 500)}
    added = 0
    for path in sorted(MUSIC_DIR.glob("*.mp3")):
        rel = path.relative_to(DATA).as_posix()
        if rel in known:
            continue
        try:
            duration = asyncio.run(ffmpeg.duration_of(path))
        except Exception:
            duration = 0.0
        mood, _, title = path.stem.partition("_")
        store.add_asset("audio", rel, size=path.stat().st_size, meta={
            "origin_name": path.name,
            "mood": mood,
            "title": title,
            "license": "CC BY 4.0",
            "artist": "Kevin MacLeod",
            "source": "incompetech.com",
            "duration": round(duration, 2),
        })
        print(f"add   {path.name}  {duration:.1f}s")
        added += 1
    return added


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default="", help="例如 http://10.0.0.1:8080")
    parser.add_argument("--no-register", action="store_true", help="只下载，不写数据库")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = parser.parse_args()

    got = download(args.proxy, skip_existing=not args.force)
    print(f"\n下载完成：{got}/{len(TRACKS)}")
    if not args.no_register:
        print(f"注册进资产库：{register()} 条")


if __name__ == "__main__":
    main()
