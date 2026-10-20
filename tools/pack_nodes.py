#!/usr/bin/env python3
"""打包导演台 custom_nodes，并更新 content/node-pack.json。

用法:
    python tools/pack_nodes.py                      # 从 D:/ComfyUI（或 --comfy）打包
    python tools/pack_nodes.py --comfy /root/ComfyUI
    python tools/pack_nodes.py --dry-run            # 只统计，不写文件

产物:
    director-node-pack.zip（与仓库同级）
    content/node-pack.json 里的 sha256 / bytes / version 更新
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "content" / "node-pack.json"
ZIP_NAME = "director-node-pack.zip"
SKIP = {"ComfyUI-FeiHou-Toolbox"}  # 上游 video_combine_v2.py 是 0 字节
IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".github", "images", "examples", "*.md")


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy", type=pathlib.Path, default=pathlib.Path("D:/ComfyUI"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    packs = sorted(manifest.get("packs") or {})
    if not packs:
        print("content/node-pack.json 缺少 packs 列表", file=sys.stderr)
        return 1

    src_root = args.comfy / "custom_nodes"
    if not src_root.exists():
        print(f"找不到 {src_root}", file=sys.stderr)
        return 1

    tmp = ROOT / "logs" / "_pack"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    total = 0
    for name in packs:
        if name in SKIP:
            continue
        src = src_root / name
        if not src.is_dir():
            print(f"[warn] 缺少 {name}")
            continue
        shutil.copytree(src, tmp / "custom_nodes" / name, ignore=IGNORE)
        size = sum(f.stat().st_size for f in (tmp / "custom_nodes" / name).rglob("*") if f.is_file())
        total += size
        print(f"{name:45} {size / 1024 / 1024:6.1f} MB")

    print(f"合计 {total / 1024 / 1024:.1f} MB")
    if args.dry_run:
        shutil.rmtree(tmp, ignore_errors=True)
        print("dry-run，未写 zip")
        return 0

    out = ROOT / ZIP_NAME
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted((tmp / "custom_nodes").rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(tmp).as_posix())
    shutil.rmtree(tmp, ignore_errors=True)

    digest = sha256_of(out)
    manifest.update({
        "version": datetime.date.today().isoformat(),
        "file": out.name,
        "bytes": out.stat().st_size,
        "sha256": digest,
    })
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已生成 {out}（{out.stat().st_size / 1024 / 1024:.0f} MB）")
    print(f"sha256 {digest}")
    print("\n下一步：")
    print("  1. 上传到 GitHub Release（tag 例如 nodes-%s）" % manifest["version"])
    print("  2. 把下载地址填进 content/node-pack.json 的 urls（可多条，含加速前缀）")
    print("  3. 提交 manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
