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
        if parsed.path == "/userdata":
            if not self._authorized():
                return
            return self._json([{"path": "workflows/demo.json", "name": "demo.json", "type": "file"}])
        if parsed.path.startswith("/userdata/"):
            if not self._authorized():
                return
            workflow = {
                "nodes": [
                    {
                        "type": "UNETLoader",
                        "properties": {
                            "models": [
                                {
                                    "name": "minimax/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                                    "url": "https://huggingface.co/Comfy-Org/MiniMax-H3_ComfyUI/resolve/main/split_files/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                                    "directory": "diffusion_models",
                                },
                                {
                                    "name": "minimax_h3_audio_vae_fp32.safetensors",
                                    "url": "https://huggingface.co/Comfy-Org/MiniMax-H3_ComfyUI/resolve/main/split_files/vae/minimax_h3_audio_vae_fp32.safetensors",
                                    "directory": "vae",
                                }
                            ]
                        },
                    }
                ]
            }
            body = json.dumps(workflow).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/object_info":
            if not self._authorized():
                return
            def opts(values):
                return [values, {}]
            return self._json({
                "UNETLoader": {"input": {"required": {"unet_name": opts([
                    "minimax/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                    "minimax/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                ])}}},
                "CLIPLoader": {"input": {"required": {"clip_name": opts([
                    "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
                ])}}},
                "VAELoader": {"input": {"required": {"vae_name": opts([
                    "minimax_h3_video_vae_int8_convrot.safetensors",
                ])}}},
                "LoraLoaderModelOnly": {"input": {"required": {"lora_name": opts([
                    "minimax/H3_Combat_V2.safetensors",
                ])}}},
                "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": opts(["sdxl.safetensors"])}}},
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
            workflow = entry.get("workflow") or {}
            is_text_job = any(
                isinstance(node, dict) and node.get("class_type") == "ZealmanLLM_Generate"
                for node in workflow.values()
            )
            if is_text_job:
                outputs = {
                    "13": {
                        "text": [
                            "subject_definitions:\n<Subject 1> 是 <Picture 1> 中的主角。\n\n"
                            "summary:\n[reference generation] 这是一段由 stub 返回的示例分镜词。\n\n"
                            "detailed_description:\n[Shot 1] 中景，主角走向镜头，冷调日光，Static Shot。\n"
                        ]
                    }
                }
            elif any(
                isinstance(node, dict) and node.get("class_type") == "SaveImage"
                for node in workflow.values()
            ):
                outputs = {"58": {"images": [{"filename": "stub_image.png", "subfolder": "", "type": "output"}]}}
            else:
                outputs = {"9": {"gifs": [{"filename": "stub_output.mp4", "subfolder": "", "type": "output"}]}}
            return self._json({
                pid: {
                    "prompt": entry.get("workflow", []),
                    "status": {"completed": True, "status_str": "success", "messages": []},
                    "outputs": outputs,
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
