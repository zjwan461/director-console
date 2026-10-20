"""服务管家冒烟测试：一键启动 → 状态 → 关闭，以及「后端重启后仍能关闭」。

    python tools/check_launcher.py

只在自己的临时目录里起一个假的 ComfyUI 进程（sleep），不会碰真实的 8188 端口。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import launcher as L  # noqa: E402
from app.config import settings  # noqa: E402

PORT = 18999
DUMMY = "import time\nprint('dummy comfy', flush=True)\ntime.sleep(600)\n"


def ok(flag: bool, label: str) -> None:
    print(("PASS  " if flag else "FAIL  ") + label, flush=True)
    if not flag:
        raise SystemExit(1)


async def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="dsh-launcher-"))
    (workdir / "dummy.py").write_text(DUMMY, encoding="utf-8")
    data_dir = Path(tempfile.mkdtemp(prefix="dsh-launcher-data-"))

    settings.raw["paths"]["data"] = str(data_dir)
    settings.raw["comfy"]["mode"] = "local"
    settings.raw["comfy"]["base_url"] = f"http://127.0.0.1:{PORT}"
    settings.raw["comfy"]["local_url"] = f"http://127.0.0.1:{PORT}"
    settings.raw["comfy"].setdefault("local", {}).update({
        "workdir": str(workdir),
        "python": sys.executable,
        "args": ["dummy.py"],
        "env": {},
    })

    # 0) 过期记录（进程早没了）不能让人误以为「托管中」，而且要自动清掉
    stale = data_dir / L.STATE_NAME
    stale.write_text(json.dumps({"pid": 2147483632, "adopted": False, "started_at": 0}), encoding="utf-8")
    L.reset_launcher()
    status = await L.get_launcher().status()
    ok(status.get("managed_pid") is None, "过期的 pid 记录不会被当成在运行")
    ok(not stale.exists(), "过期记录已自动清理")

    # 1) 启动：同一个实例必须记得 pid（以前每次请求都新建实例，这里就是 None）
    L.reset_launcher()
    started = await L.get_launcher().start()
    ok(bool(started.get("ok")), f"启动：{started.get('message')}")

    status = await L.get_launcher().status()
    ok(bool(status.get("managed_pid")), f"同实例状态里有 pid：{status.get('managed_pid')}")

    # 2) 模拟后端重启：丢掉缓存实例，凭 data/comfy-process.json 认领回来
    L.reset_launcher()
    status = await L.get_launcher().status()
    ok(bool(status.get("managed_pid")), f"重启后仍认得 pid：{status.get('managed_pid')}")

    stopped = await L.get_launcher().stop()
    ok(bool(stopped.get("ok")), f"关闭：{stopped.get('message')}")
    await asyncio.sleep(0.5)
    status = await L.get_launcher().status()
    ok(not status.get("managed_pid"), "关闭后 pid 已清空")

    # 3) 外部启动的 ComfyUI（没有 pid 记录、也没有 state 文件）：按端口兜底
    L.reset_launcher()
    (data_dir / L.STATE_NAME).unlink(missing_ok=True)
    external = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if L._find_listening_pid(PORT):
                break
            time.sleep(0.1)
        ok(bool(L._find_listening_pid(PORT)), f"外部进程在监听 {PORT}")
        stopped = await L.get_launcher().stop()
        ok(bool(stopped.get("ok")), f"按端口关闭：{stopped.get('message')}")
        await asyncio.sleep(0.5)
        ok(external.poll() is not None, "外部进程确实退出了")
    finally:
        if external.poll() is None:
            external.kill()

    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
