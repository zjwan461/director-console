"""导演台测试用的小工具：建临时项目、发消息、等运行结束。

只依赖 httpx，默认连 http://127.0.0.1:6006，可用环境变量 DSH_PANEL 覆盖。
"""
import json
import os
import sqlite3
import time

import httpx

B = os.environ.get("DSH_PANEL", "http://127.0.0.1:6006").rstrip("/")
DB = os.environ.get(
    "DSH_DB", os.path.join(os.path.dirname(__file__), "..", "..", "data", "director.db"))
c = httpx.Client(trust_env=False, timeout=120)


def new_project(name="QA 临时项目"):
    return c.post(B + "/api/projects", json={"name": name}).json()["id"]


def drop_project(pid):
    try:
        c.delete(B + f"/api/projects/{pid}")
    except Exception:
        pass


def new_thread(pid, title="QA"):
    return c.post(B + "/api/agent/threads", json={"project_id": pid, "title": title}).json()


def latest_run(thread_id):
    db = sqlite3.connect(os.path.abspath(DB))
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT * FROM agent_runs WHERE thread_id=? ORDER BY started_at DESC LIMIT 1",
        (thread_id,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "status": row["status"], "node": row["node"],
            "pending": json.loads(row["pending_json"] or "{}"), "error": row["error"]}


def ask(thread_id, text, timeout=90):
    c.post(B + f"/api/agent/threads/{thread_id}/messages", json={"text": text})
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.4)
        run = latest_run(thread_id)
        if run and run["status"] in ("waiting_confirm", "done", "failed", "canceled",
                                     "interrupted"):
            time.sleep(0.3)
            return latest_run(thread_id)
    return latest_run(thread_id)


def send(thread_id, text, timeout=90):
    """按 run_id 精确跟踪，返回 (run, assistant 回复)。"""
    before = len(messages(thread_id))
    res = c.post(B + f"/api/agent/threads/{thread_id}/messages", json={"text": text}).json()
    run_id = res.get("run_id") or ""
    run, release = {"status": "", "pending": {}}, time.time() + timeout
    while time.time() < release:
        time.sleep(0.4)
        got = c.get(B + f"/api/agent/runs/{run_id}").json() if run_id else {}
        if got and got.get("status") in ("waiting_confirm", "done", "failed", "canceled"):
            run = got
            break
    reply = ""
    for _ in range(12):
        msgs = messages(thread_id)
        if len(msgs) > before and msgs[-1]["role"] == "assistant":
            reply = msgs[-1]["content"]
            break
        time.sleep(0.3)
    return run, reply


def confirm(run_id, approved=True, params=None):
    body = {"approved": approved}
    if params:
        body["params"] = params
    return c.post(B + f"/api/agent/runs/{run_id}/confirm", json=body)


def messages(thread_id):
    return c.get(B + f"/api/agent/threads/{thread_id}/messages").json()["items"]


def artifacts(thread_id):
    return c.get(B + f"/api/agent/threads/{thread_id}").json()["artifacts"]


def make_shot(pid, title="QA 镜头", preset="h3.t2v", prompt="雪地里的黑猫"):
    return c.post(B + "/api/shots", json={
        "project_id": pid, "title": title, "preset_id": preset, "prompt": prompt}).json()


def edit_state(pid):
    return c.get(B + f"/api/projects/{pid}/edit-state").json()


def save_edit_state(pid, state):
    return c.put(B + f"/api/projects/{pid}/edit-state", json=state)


def add_artifacts(thread_id, items):
    """直接写产物，避免为了造数据真去跑 GPU。"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.agent import store as agent_store  # noqa: E402

    run = agent_store.create_run(thread_id)
    created = []
    for index, item in enumerate(items, start=1):
        created.append(agent_store.add_artifact(
            run["id"], thread_id, item.get("kind", "image"),
            item.get("ref_id", f"job_qa{index}"),
            item.get("url", f"/media/files/qa{index}.png"),
            {"status": "succeeded", "params": item.get("params", {}),
             "note": item.get("note", "")}))
    return created
