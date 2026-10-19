"""ComfyUI 服务管家：一键启动 / 停止 / 状态 / 日志。

三种模式：
  local    - 本机 spawn 子进程（Windows 开发 / Linux 同机部署）
  ssh      - 远程 Linux 机器上执行启动脚本（AutoDL / 自建服务器）
  external - 已经有人在跑，只做健康检查与代理（旧面板托管的情况）
"""
from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .comfy import ComfyClient, make_client
from .config import settings

LOG_PATH = Path(settings.paths["data"]) / "comfy.log"


class LaunchError(RuntimeError):
    pass


def _tail(path: Path, lines: int = 200) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, 200_000)
            f.seek(size - block)
            data = f.read().decode("utf-8", "replace")
        return "\n".join(data.splitlines()[-lines:])
    except Exception as exc:
        return f"<读取日志失败：{exc}>"


class BaseLauncher:
    mode = "base"
    managed = False

    async def start(self) -> dict:
        raise LaunchError(
            "当前是云端/外部模式，面板不负责启动进程；如果 ComfyUI 没开，请到云平台控制台启动，"
            "或把连接方式改成「本机 / SSH」由面板托管"
        )

    async def stop(self) -> dict:
        raise LaunchError("当前是云端/外部模式，面板不会关闭对方的服务")

    async def status(self) -> dict:
        client = make_client()
        health = await client.health()
        return {
            "mode": self.mode,
            "managed": self.managed,
            "base_url": settings.base_url,
            "running": bool(health.get("ok")),
            "health": health,
        }

    async def logs(self, lines: int = 200) -> str:
        return ""


class MockLauncher(BaseLauncher):
    mode = "mock"
    managed = False

    async def start(self) -> dict:
        return {"ok": True, "message": "模拟模式：假装已启动"}

    async def stop(self) -> dict:
        return {"ok": True, "message": "模拟模式：假装已停止"}

    async def status(self) -> dict:
        return {
            "mode": "mock",
            "managed": False,
            "base_url": "mock://",
            "running": True,
            "health": {"ok": True, "mock": True, "devices": [{"name": "MOCK GPU"}]},
        }


class LocalLauncher(BaseLauncher):
    mode = "local"
    managed = True

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self._logfile = None
        self.started_at: float = 0

    def _cfg(self, key: str, default: Any = None) -> Any:
        return settings.get(f"comfy.local.{key}", default)

    async def start(self) -> dict:
        if self.proc and self.proc.poll() is None:
            return {"ok": True, "message": "ComfyUI 已在运行（本进程托管）"}
        if (await self.status())["running"]:
            return {"ok": True, "message": "检测到 ComfyUI 已在监听，直接接管"}

        workdir = Path(str(self._cfg("workdir", "")))
        if not workdir.exists():
            raise LaunchError(f"ComfyUI 目录不存在：{workdir}（改 config.yaml 的 comfy.local.workdir）")
        python = str(self._cfg("python", sys.executable))
        args = list(self._cfg("args", ["main.py"]))
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (self._cfg("env", {}) or {}).items()})

        log_path = Path(settings.paths["data"]) / "comfy.log"
        self._logfile = log_path.open("ab")
        self._logfile.write(f"\n\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} start =====\n".encode())
        self._logfile.flush()

        kwargs: dict[str, Any] = {
            "cwd": str(workdir),
            "stdout": self._logfile,
            "stderr": subprocess.STDOUT,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True

        self.proc = subprocess.Popen([python, *args], **kwargs)  # noqa: S603
        self.started_at = time.time()
        return {"ok": True, "message": f"已启动 ComfyUI（pid={self.proc.pid}），首页加载需要一些时间"}

    async def stop(self) -> dict:
        stopped = False
        if self.proc and self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    capture_output=True, text=True, check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                    for _ in range(20):
                        if self.proc.poll() is not None:
                            break
                        time.sleep(0.25)
                    if self.proc.poll() is None:
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            stopped = True
            self.proc = None
        if self._logfile:
            self._logfile.close()
            self._logfile = None
        if not stopped:
            return {"ok": True, "message": "没有由本进程托管的 ComfyUI 在运行"}
        return {"ok": True, "message": "已停止 ComfyUI"}

    async def status(self) -> dict:
        base = await super().status()
        pid = self.proc.pid if self.proc and self.proc.poll() is None else None
        base.update({
            "managed_pid": pid,
            "managed_uptime": round(time.time() - self.started_at) if pid and self.started_at else 0,
            "workdir": str(self._cfg("workdir", "")),
        })
        return base

    async def logs(self, lines: int = 200) -> str:
        path = Path(settings.paths["data"]) / "comfy.log"
        return _tail(path, lines)


class SshLauncher(BaseLauncher):
    mode = "ssh"
    managed = True

    def _ssh_target(self) -> str:
        host = str(settings.get("comfy.ssh.host", ""))
        if not host:
            raise LaunchError("没有配置 comfy.ssh.host")
        user = settings.get("comfy.ssh.user", "")
        return f"{user}@{host}" if user else host

    async def _run(self, command: str, timeout: float = 120) -> tuple[int, str]:
        target = self._ssh_target()
        port = str(settings.get("comfy.ssh.port", 22))
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-p", port, target, command]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise LaunchError("SSH 命令超时")
        return proc.returncode or 0, (out or b"").decode("utf-8", "replace")

    async def start(self) -> dict:
        if (await self.status())["running"]:
            return {"ok": True, "message": "远程 ComfyUI 已在运行"}
        code, out = await self._run(str(settings.get("comfy.ssh.start", "bash /root/ComfyUI/start.sh")))
        return {"ok": code == 0, "message": out.strip() or ("已发送启动命令" if code == 0 else "启动失败")}

    async def stop(self) -> dict:
        code, out = await self._run(str(settings.get("comfy.ssh.stop", "pkill -f 'python.*main.py'")))
        return {"ok": code == 0, "message": out.strip() or "已发送停止命令"}

    async def status(self) -> dict:
        base = await super().status()
        base["ssh_target"] = str(settings.get("comfy.ssh.host", ""))
        return base

    async def logs(self, lines: int = 200) -> str:
        cmd = str(settings.get("comfy.ssh.log", ""))
        if not cmd:
            return ""
        code, out = await self._run(cmd, timeout=30)
        return "\n".join(out.splitlines()[-lines:])


class ExternalLauncher(BaseLauncher):
    mode = "external"
    managed = False


def get_launcher() -> BaseLauncher:
    mode = settings.comfy_mode
    if mode == "mock":
        return MockLauncher()
    if mode == "ssh":
        return SshLauncher()
    if mode == "external":
        return ExternalLauncher()
    return LocalLauncher()
