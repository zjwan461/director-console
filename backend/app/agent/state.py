"""线程状态：把「最近一个产物」升级成「产物列表 + 镜头引用」。

产物真实来源是 agent_artifacts 表；这里负责：
1. 给每个产物编号（#1、#2…，按时间正序）
2. 记录血缘（parent）与参数（params）——修订时要用
3. 把中文指代（第 2 张 / 刚才那个 / 雪地那张 / 第 2 镜）解析成具体对象

设计原则：编号在会话内稳定（按 created_at 排序），修订产物排在被修订者之后。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from . import store as agent_store

NUM_RE = re.compile(r"第\s*([0-9一二三四五六七八九十]+)\s*(张|个|条|版|幅|帧|镜|次)?")
ORD_WORDS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9, "十": 10}
RECENT_RE = re.compile(r"(刚才|刚刚|上一个?|上一版|上一条|最后那个|最后一张|最后一条)")
THIS_RE = re.compile(r"(这个|这张|这条|它)")
SHOT_RE = re.compile(r"第\s*([0-9一二三四五六七八九十]+)\s*镜")


def _parse_number(token: str) -> int:
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token in ORD_WORDS:
        return ORD_WORDS[token]
    if len(token) == 2 and token[0] == "十":
        return 10 + ORD_WORDS.get(token[1], 0)
    if len(token) == 2 and token[1] == "十":
        return ORD_WORDS.get(token[0], 0) * 10
    return 0


def _artifact_params(artifact: dict) -> dict:
    meta: dict = artifact.get("meta") or {}
    return dict(meta.get("params") or {})


def thread_artifacts(thread_id: str) -> list[dict]:
    """按时间正序编号的产物列表（只含有 url 的）。"""
    rows = agent_store.list_artifacts(thread_id, limit=60)
    items = [a for a in rows if a.get("url")]
    items.sort(key=lambda a: (float(a.get("created_at") or 0), int(a.get("seq") or 0)))
    result = []
    for index, art in enumerate(items, start=1):
        meta: dict = art.get("meta") or {}
        result.append({
            "ref": index,
            "kind": art.get("kind") or "",
            "url": art.get("url") or "",
            "ref_id": art.get("ref_id") or "",
            "id": art.get("id") or "",
            "params": _artifact_params(art),
            "parent": meta.get("parent_ref"),
            "note": meta.get("note") or "",
            "prompt": (meta.get("params") or {}).get("prompt") or meta.get("prompt") or "",
            "created_at": float(art.get("created_at") or 0),
        })
    return result


def thread_state(thread_id: str) -> dict:
    artifacts = thread_artifacts(thread_id)
    return {
        "artifacts": artifacts,
        "last_ref": artifacts[-1]["ref"] if artifacts else 0,
        "count": len(artifacts),
    }


def _shot_refs(project_id: str) -> list[dict]:
    from .. import store as project_store

    shots = project_store.list_shots(project_id) if project_id else []
    return [{"ref": f"S{index}", "index": index, "shot_id": s["id"],
             "title": s.get("title") or f"镜头 {index}",
             "prompt": s.get("prompt") or "", "cover": s.get("cover") or ""}
            for index, s in enumerate(shots, start=1)]


def resolve(text: str, thread_id: str, project_id: str = "") -> dict:
    """把一句话里的指代解析成目标。

    返回 {"target": ..., "how": "...", "ambiguous": [...]}
    target 为 None 表示没找到；ambiguous 非空表示需要反问。
    """
    state = thread_state(thread_id)
    artifacts = state["artifacts"]
    last_ref = state["last_ref"]

    shot_match = SHOT_RE.search(text)
    if shot_match:
        index = _parse_number(shot_match.group(1))
        shots = _shot_refs(project_id)
        if 1 <= index <= len(shots):
            return {"target": {"type": "shot", **shots[index - 1]}, "how": f"第 {index} 镜",
                    "ambiguous": []}
        return {"target": None, "how": f"第 {index} 镜", "ambiguous": [],
                "error": f"项目里只有 {len(shots)} 个镜头"}

    num_match = NUM_RE.search(text)
    if num_match:
        index = _parse_number(num_match.group(1))
        unit = num_match.group(2) or ""
        if 1 <= index <= len(artifacts):
            return {"target": {"type": "artifact", **artifacts[index - 1]},
                    "how": f"第 {index} {unit or '个'}产物", "ambiguous": []}
        if index:
            return {"target": None, "how": f"第 {index} 个产物", "ambiguous": [],
                    "error": f"这次会话只有 {len(artifacts)} 个产物"}

    if RECENT_RE.search(text) and last_ref:
        target = next((a for a in artifacts if a["ref"] == last_ref), None)
        if target:
            return {"target": {"type": "artifact", **target}, "how": "上一版", "ambiguous": []}

    if THIS_RE.search(text) and last_ref:
        target = next((a for a in artifacts if a["ref"] == last_ref), None)
        if target:
            return {"target": {"type": "artifact", **target}, "how": "这个", "ambiguous": []}

    # 描述式：「雪地里的白狐那张」
    scored = []
    for art in artifacts:
        haystack = f"{art['note']} {art['prompt']}"
        match = SequenceMatcher(None, text, haystack).find_longest_match(
            0, len(text), 0, len(haystack))
        if match.size >= 3:
            scored.append((match.size, art))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return {"target": {"type": "artifact", **scored[0][1]}, "how": "按描述匹配",
                "ambiguous": []}
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return {"target": None, "how": "按描述匹配",
                "ambiguous": [art for _, art in scored[:4]]}

    if last_ref:
        target = next((a for a in artifacts if a["ref"] == last_ref), None)
        if target:
            return {"target": {"type": "artifact", **target}, "how": "默认最近一个", "ambiguous": []}

    return {"target": None, "how": "", "ambiguous": [], "error": "这次会话里还没有产物"}


# --------------------------------------------------------------------------- #
# 修订补丁：把「再亮一点」「慢一些」「换竖屏」变成参数差异
# --------------------------------------------------------------------------- #
BRIGHT_UP = re.compile(r"(亮一点|更亮|提亮|亮些|曝光.*(高|加))")
BRIGHT_DOWN = re.compile(r"(暗一点|更暗|压暗|暗些)")
SLOW = re.compile(r"(慢一点|慢一些|放慢|慢点)")
FAST = re.compile(r"(快一点|快一些|加快|快点)")
PORTRAIT = re.compile(r"竖屏|竖版|9:16")
LANDSCAPE = re.compile(r"横屏|横版|16:9")
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*秒")
MP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mp|兆像素)", re.IGNORECASE)


def build_patch(text: str) -> dict[str, Any]:
    """从修订语句里抽出参数差异。"""
    patch: dict[str, Any] = {}
    suffixes: list[str] = []

    if BRIGHT_UP.search(text):
        suffixes.append("整体更明亮，曝光提高，高光柔和")
    if BRIGHT_DOWN.search(text):
        suffixes.append("整体压暗，低照度氛围，暗部保留细节")
    if SLOW.search(text):
        suffixes.append("动作放慢，镜头运镜更舒缓")
    if FAST.search(text):
        suffixes.append("动作加快，节奏更利落")
    if PORTRAIT.search(text):
        patch["aspect"] = "9:16"
    if LANDSCAPE.search(text):
        patch["aspect"] = "16:9"
    duration = DURATION_RE.search(text)
    if duration:
        patch["duration"] = float(duration.group(1))
    mp = MP_RE.search(text)
    if mp:
        patch["megapixels"] = float(mp.group(1))
    if suffixes:
        patch["prompt_suffix"] = "，".join(suffixes)
    return patch


def describe_patch(patch: dict, target: dict) -> str:
    """确认卡上的差异描述。"""
    bits: list[str] = []
    if patch.get("prompt_suffix"):
        bits.append(f"追加描述：{patch['prompt_suffix']}")
    if patch.get("aspect"):
        old = (target.get("params") or {}).get("aspect") or "—"
        bits.append(f"画幅 {old} → {patch['aspect']}")
    if patch.get("duration"):
        old = (target.get("params") or {}).get("duration")
        bits.append(f"时长 {old or '—'} → {patch['duration']} 秒")
    if patch.get("megapixels"):
        old = (target.get("params") or {}).get("megapixels")
        bits.append(f"清晰度 {old or '—'} → {patch['megapixels']} MP")
    return " · ".join(bits) or "没有识别出具体改动"
