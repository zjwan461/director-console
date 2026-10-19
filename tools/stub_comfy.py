"""最小的 ComfyUI 假服务：用来验证「云端/远程 ComfyUI」链路。

启动：
    python tools/stub_comfy.py --port 8199
    python tools/stub_comfy.py --port 8199 --token secret   # 需要 Bearer secret

它只实现导演台用到的接口：/system_stats /prompt /history /view /upload/image /free /interrupt /queue。
输出是一段占位文本，不是真视频。
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

JOBS: dict[str, dict] = {}
TOKEN = ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[stub] {self.address_string()} {fmt % args}")

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        if self.headers.get("Authorization") in {f"Bearer {TOKEN}", TOKEN}:
            return True
        self._json({"error": "unauthorized"}, 401)
        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/system_stats":
            if not self._authorized():
                return
            return self._json({
                "system": {"os": "linux", "comfyui_version": "0.3.99-stub", "python_version": "3.11"},
                "devices": [{
                    "name": "STUB GPU 24G",
                    "type": "cuda",
                    "vram_total": 24 * 1024 ** 3,
                    "vram_free": 21 * 1024 ** 3,
                }],
            })
        if parsed.path == "/queue":
            if not self._authorized():
                return
            return self._json({"queue_running": [], "queue_pending": []})
        if parsed.path.startswith("/history/"):
            if not self._authorized():
                return
            pid = parsed.path.rsplit("/", 1)[-1]
            entry = JOBS.get(pid)
            if not entry:
                return self._json({})
            if time.time() - entry["t"] < 2:
                return self._json({})
            return self._json({
                pid: {
                    "prompt": entry.get("workflow", []),
                    "status": {"completed": True, "status_str": "success", "messages": []},
                    "outputs": {"9": {"gifs": [{"filename": "stub_output.mp4", "subfolder": "", "type": "output"}]}},
                }
            })
        if parsed.path == "/view":
            if not self._authorized():
                return
            qs = parse_qs(parsed.query)
            name = qs.get("filename", ["stub_output.mp4"])[0]
            payload = f"STUB COMFY OUTPUT: {name}\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return self._json({"error": "not found", "path": parsed.path}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        if parsed.path == "/prompt":
            if not self._authorized():
                return
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            pid = uuid.uuid4().hex
            JOBS[pid] = {"t": time.time(), "workflow": payload.get("prompt", {})}
            return self._json({"prompt_id": pid, "number": len(JOBS), "node_errors": {}})
        if parsed.path == "/upload/image":
            if not self._authorized():
                return
            return self._json({"name": "stub_upload.png", "subfolder": "", "type": "input"})
        if parsed.path in {"/free", "/interrupt"}:
            if not self._authorized():
                return
            return self._json({})
        return self._json({"error": "not found"}, 404)


def main() -> None:
    global TOKEN
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8199)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    TOKEN = args.token
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"stub ComfyUI on http://{args.host}:{args.port} (token={'set' if TOKEN else 'none'})")
    server.serve_forever()


if __name__ == "__main__":
    main()
