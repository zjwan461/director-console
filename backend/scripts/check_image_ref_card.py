"""离线自检：新卡片的绑定/多图摘除是否正确（不提交 ComfyUI）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import presets  # noqa: E402


def show(title: str, workflow: dict, node: str = "4") -> None:
    print("=" * 70)
    print(title)
    inputs = (workflow.get(node) or {}).get("inputs") or {}
    for key in sorted(inputs):
        value = inputs[key]
        if isinstance(value, str) and len(value) > 40:
            value = value[:40] + "…"
        print(f"  {key} = {value!r}")


def main() -> int:
    card = presets.get_card("image.ref")
    if not card:
        print("卡片没加载到")
        return 1
    print("卡片:", card["id"], "|", card["name"], "| workflow:", card["workflow"])
    print("字段:", [(f["key"], f["type"], f.get("required")) for f in card["fields"]])

    base = presets.load_workflow(card["workflow"])
    print("工作流节点数:", len([v for v in base.values() if isinstance(v, dict) and v.get("class_type")]))

    # 1) 单图
    values = {"prompt": "把背景换成雪夜山门", "resolution": "1024", "seed": 7}
    media = {"image": "a.png"}
    binds = presets.build_bindings(card, values, media)
    wf = presets.apply_bindings(base, binds)
    wf = presets.drop_bindings(wf, presets.optional_drops(card, media))
    show("单图：image_2/3 应被摘掉", wf)
    assert "images.image_2" not in wf["4"]["inputs"], "单图时 image_2 没摘掉"
    assert wf["21"]["inputs"]["image"] == "a.png"

    # 2) 三图
    media = {"image": "a.png", "image2": "b.png", "image3": "c.png"}
    binds = presets.build_bindings(card, values, media)
    wf = presets.apply_bindings(base, binds)
    wf = presets.drop_bindings(wf, presets.optional_drops(card, media))
    show("三图：三个槽位都在", wf)
    assert wf["4"]["inputs"]["images.image_2"] == ["31", 0]
    assert wf["4"]["inputs"]["images.image_3"] == ["32", 0]
    assert wf["31"]["inputs"]["image"] == "b.png"
    assert wf["32"]["inputs"]["image"] == "c.png"

    # 3) 两图
    media = {"image": "a.png", "image2": "b.png"}
    binds = presets.build_bindings(card, values, media)
    wf = presets.apply_bindings(base, binds)
    wf = presets.drop_bindings(wf, presets.optional_drops(card, media))
    show("两图：只有 image_3 被摘掉", wf)
    assert "images.image_3" not in wf["4"]["inputs"]
    assert wf["4"]["inputs"]["images.image_2"] == ["31", 0]

    # 4) 模型名（等下载完应能对上）
    print("=" * 70)
    for node in ("22:1", "22:2", "22:3"):
        print(node, base[node]["class_type"], base[node]["inputs"])
    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
