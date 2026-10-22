"""ComfyUI 服务管家：一键启动 / 停止 / 状态 / 日志。

三种模式：
  local    - 本机 spawn 子进程（Windows 开发 / Linux 同机部署）
  ssh      - 远程 Linux 机器上执行启动脚本（AutoDL / 自建服务器）
  external - 已经有人在跑，只做健康检查与代理（旧面板托管的情况）

两条关键约定（之前踩过的坑）：
  1. 进程句柄必须留在**同一个 launcher 实例**上，所以 get_launcher() 按模式缓存实例；
     每次请求都 new 一个的话，「一键启动」拉起的子进程当场就没人记得，「关闭」只会回一句
     「没有由本进程托管的 ComfyUI 在运行」，看起来就像按钮没反应。
  2. 启动/接管的 pid 落到 data/comfy-process.json，后端重启后还能认领回来；
     实在没有 pid（桌面版、命令行、旧面板启动的），关闭时按端口找监听进程兜底。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .comfy import ComfyClient, make_client
from .config import settings

LOG_PATH = Path(settings.paths["data"]) / "comfy.log"
STATE_NAME = "comfy-process.json"


class LaunchError(RuntimeError):
    pass


_START_MARK_RE = re.compile(r"^===== \d{4}-\d{2}-\d{2} .* start =====$", re.M)


def _tail(path: Path, lines: int = 200, only_last_run: bool = True) -> str:
    """读日志尾部；only_last_run=True 时只保留最后一次「===== … start =====」之后的内容。"""
    if not path.exists():
        return ""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, 2_000_000)   # 一次跑下来几 MB 也算够；太大的旧内容反正不要
            f.seek(size - block)
            data = f.read().decode("utf-8", "replace")
        if only_last_run:
            marks = list(_START_MARK_RE.finditer(data))
            if marks:
                data = data[marks[-1].end():]
        return "\n".join(data.splitlines()[-lines:]).strip("\n")
    except Exception as exc:
        return f"<读取日志失败：{exc}>"


# ---------------------------------------------------------------- 进程工具
def _state_path() -> Path:
    return Path(settings.paths["data"]) / STATE_NAME


def _read_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(data: dict) -> None:
    try:
        _state_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _clear_state() -> None:
    try:
        _state_path().unlink(missing_ok=True)
    except OSError:
        pass


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_created(pid: int) -> int | None:
    """进程创建时间（拿不到就 None）。用来防「pid 被系统复用后认错进程」。"""
    if pid <= 0:
        return None
    if os.name == "nt":
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            ok = _kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited),
                ctypes.byref(kernel), ctypes.byref(user),
            )
            if not ok:
                return None
            return (created.dwHighDateTime << 32) | created.dwLowDateTime
        finally:
            _kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[19])   # starttime（开机后的 tick 数）
    except Exception:
        return None


def _process_image(pid: int) -> str:
    """进程可执行文件路径；拿不到就返回空串。"""
    if pid <= 0:
        return ""
    if os.name == "nt":
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            _kernel32.CloseHandle(handle)
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if raw and raw[0]:
            return raw[0].decode("utf-8", "replace")
    except OSError:
        pass
    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5, check=False).stdout
        return out.strip()
    except Exception:
        return ""


def _looks_like_comfy(pid: int) -> bool:
    """避免误杀：只认 python / pythonw / comfy 这类进程名，认不出就不动它。"""
    image = _process_image(pid).lower()
    if not image:
        return False
    name = image.replace("\\", "/").rsplit("/", 1)[-1]
    return "python" in name or "comfy" in name


def _local_port() -> int:
    url = str(settings.get("comfy.local_url", "") or settings.base_url or "")
    if url:
        try:
            parsed = urlparse(url if "://" in url else f"http://{url}")
            if parsed.port:
                return int(parsed.port)
        except ValueError:
            pass
    args = [str(a) for a in (settings.get("comfy.local.args", []) or [])]
    for index, item in enumerate(args):
        if item == "--port" and index + 1 < len(args):
            try:
                return int(args[index + 1])
            except ValueError:
                continue
        if item.startswith("--port="):
            try:
                return int(item.split("=", 1)[1])
            except ValueError:
                continue
    return 8188


def _find_listening_pid(port: int) -> int | None:
    """按端口找监听进程：没有 pid 时最后的兜底。"""
    if port <= 0:
        return None
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=10, check=False,
                encoding="utf-8", errors="replace",
            ).stdout
        except Exception:
            return None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP":
                continue
            local, state, pid = parts[1], parts[3], parts[4]
            if state.upper() != "LISTENING":
                continue
            if local.rsplit(":", 1)[-1] != str(port):
                continue
            try:
                return int(pid)
            except ValueError:
                continue
        return None

    for cmd in (["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                ["ss", "-ltnpH", f"sport = :{port}"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False,
                                 encoding="utf-8", errors="replace").stdout
        except Exception:
            continue
        text = out.strip()
        if not text:
            continue
        if cmd[0] == "lsof":
            for token in text.split():
                if token.isdigit():
                    return int(token)
        else:
            for token in text.split():
                if token.startswith("pid="):
                    value = token[4:].split(",", 1)[0]
                    if value.isdigit():
                        return int(value)
    return None


def _kill_tree(pid: int) -> tuple[bool, str]:
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                capture_output=True, text=True, check=False,
                                encoding="utf-8", errors="replace")
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "").strip()[:200]
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True, ""
    except PermissionError as exc:
        return False, str(exc)
    for _ in range(20):
        if not _pid_alive(pid):
            return True, ""
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        return False, str(exc)
    return True, ""


# ---------------------------------------------------------------- 模式
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
        self.adopted_pid: int | None = None
        self.started_at: float = 0.0
        self._logfile = None
        self._restore_state()

    def _cfg(self, key: str, default: Any = None) -> Any:
        return settings.get(f"comfy.local.{key}", default)

    # ---------- 内部：pid 记账 ----------
    def _recorded_ok(self) -> bool:
        """记录的 pid 现在还指同一个进程吗（防 pid 被系统复用后认错人）。"""
        if not self.adopted_pid or not _pid_alive(self.adopted_pid):
            return False
        if not _looks_like_comfy(self.adopted_pid):
            return False
        state = _read_state()
        created = state.get("created")
        if isinstance(created, int):
            # 创建时间对不上 = pid 已被别的进程复用（比如面板自己的 uvicorn）
            return _process_created(self.adopted_pid) == created
        # 老版本记录没存创建时间：退回「端口上是不是它」
        return _find_listening_pid(_local_port()) == self.adopted_pid

    def _restore_state(self) -> None:
        state = _read_state()
        pid = state.get("pid")
        if not isinstance(pid, int):
            return
        self.adopted_pid = pid
        if not self._recorded_ok():
            self.adopted_pid = None
            _clear_state()
            return
        self.started_at = float(state.get("started_at") or 0.0)

    def _remember(self, pid: int, adopted: bool) -> None:
        self.adopted_pid = pid if adopted else None
        _write_state({
            "pid": pid,
            "adopted": adopted,
            "created": _process_created(pid),
            "started_at": self.started_at,
            "port": _local_port(),
            "workdir": str(self._cfg("workdir", "")),
        })

    def _forget(self) -> None:
        self.proc = None
        self.adopted_pid = None
        self.started_at = 0.0
        self._close_log()
        _clear_state()

    def _pid(self) -> int | None:
        """当前托管的 pid（优先本进程子进程，其次重启前记录的 pid）。"""
        if self.proc is not None:
            if self.proc.poll() is None:
                return self.proc.pid
            # 子进程自己退了（崩溃或在别处被关掉）：清掉 pid 记录，免得 pid 被系统复用时认错人
            self.proc = None
            self.started_at = 0.0
            self._close_log()
            _clear_state()
        if self.adopted_pid:
            if self._recorded_ok():
                return self.adopted_pid
            self.adopted_pid = None
            self.started_at = 0.0
            _clear_state()
        return None

    def _close_log(self) -> None:
        if self._logfile:
            try:
                self._logfile.close()
            except Exception:
                pass
            self._logfile = None

    # ---------- 动作 ----------
    async def start(self) -> dict:
        pid = self._pid()
        if pid:
            return {"ok": True, "message": f"ComfyUI 已在运行（pid={pid}，面板托管中）"}

        if (await self.status())["running"]:
            found = _find_listening_pid(_local_port())
            if found and _looks_like_comfy(found):
                self.started_at = time.time()
                self._remember(found, adopted=True)
                return {"ok": True, "message": f"ComfyUI 已在监听，已接管现成进程（pid={found}），现在可以一键关闭"}
            return {
                "ok": True,
                "message": "检测到 ComfyUI 已在监听，但没找到能接管的本地进程；关闭时请按提示手动处理",
            }

        workdir = Path(str(self._cfg("workdir", "")))
        if not workdir.exists():
            raise LaunchError(f"ComfyUI 目录不存在：{workdir}（改 config.yaml 的 comfy.local.workdir）")
        python = str(self._cfg("python", sys.executable))
        args = list(self._cfg("args", ["main.py"]))
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (self._cfg("env", {}) or {}).items()})

        log_path = Path(settings.paths["data"]) / "comfy.log"
        # 每次启动重写日志：面板里只看得到这一次的内容，也不会越滚越大
        self._logfile = log_path.open("wb")
        self._logfile.write(f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} start =====\n".encode())
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
        self._remember(self.proc.pid, adopted=False)
        return {"ok": True, "message": f"已启动 ComfyUI（pid={self.proc.pid}），首页加载需要一些时间"}

    async def stop(self) -> dict:
        pid = self._pid()
        note = ""
        if not pid:
            port = _local_port()
            found = _find_listening_pid(port)
            if found:
                if not _looks_like_comfy(found):
                    raise LaunchError(
                        f"端口 {port} 被进程 {found} 占用，但它看起来不是 ComfyUI，面板没有动它；"
                        "确认后可以在任务管理器里手动结束这个进程"
                    )
                pid = found
                note = "（这个进程不是面板启动的，按端口找到）"

        if not pid:
            self._forget()
            return {"ok": True, "message": "ComfyUI 已经没有在运行"}

        ok, detail = await asyncio.to_thread(_kill_tree, pid)
        self._forget()
        if not ok:
            raise LaunchError(f"结束进程 {pid} 失败：{detail or '权限不足'}，请在任务管理器里手动关闭")
        return {"ok": True, "message": f"已关闭 ComfyUI（pid={pid}）{note}"}

    async def status(self) -> dict:
        base = await super().status()
        pid = self._pid()
        base.update({
            "managed_pid": pid,
            "managed_uptime": round(time.time() - self.started_at) if pid and self.started_at else 0,
            "managed_adopted": bool(pid and self.adopted_pid == pid),
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


_LAUNCHERS: dict[str, BaseLauncher] = {}


def _make_launcher(mode: str) -> BaseLauncher:
    if mode == "mock":
        return MockLauncher()
    if mode == "ssh":
        return SshLauncher()
    if mode == "external":
        return ExternalLauncher()
    return LocalLauncher()


def get_launcher() -> BaseLauncher:
    """同一个模式下始终返回同一个实例，启动的进程句柄才不会丢。"""
    mode = settings.comfy_mode
    if mode not in {"local", "ssh", "external", "mock"}:
        mode = "local"
    launcher = _LAUNCHERS.get(mode)
    if launcher is None:
        launcher = _LAUNCHERS[mode] = _make_launcher(mode)
    return launcher


def reset_launcher() -> None:
    """测试用：丢掉缓存的实例。"""
    _LAUNCHERS.clear()
