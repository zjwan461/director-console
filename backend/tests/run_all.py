"""跑全部回归测试，逐个文件独立进程，失败自动重试一次。

    cd backend/tests
    python run_all.py            # 全部
    python run_all.py corpus step2   # 只跑匹配的
"""
import subprocess
import sys
import time
from pathlib import Path

FILES = [
    "test_corpus.py",
    "test_step2.py",
    "test_agent_loop.py",
    "test_vision.py",
    "test_animate.py",
    "test_topic.py",
    "test_optimize.py",
    "test_cancel.py",
    "test_files_only.py",
    "test_motion_prompt.py",
    "test_audio.py",
    "test_audio2.py",
    "test_actions.py",
]

HERE = Path(__file__).resolve().parent


def run_one(name: str) -> tuple[bool, str]:
    started = time.time()
    proc = subprocess.run([sys.executable, name], cwd=str(HERE),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    cost = time.time() - started
    ok = proc.returncode == 0
    tail = ""
    for line in (proc.stdout or "").splitlines()[::-1]:
        if "FAIL" in line or "通过" in line or "全部" in line or "失败" in line:
            tail = line.strip()
            break
    return ok, f"{tail[:90]} ({cost:.0f}s)"


def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    files = [f for f in FILES if not wanted or any(w in f for w in wanted)]

    results = []
    for name in files:
        ok, note = run_one(name)
        if not ok:
            sys.stdout.buffer.write(f"[retry] {name}\n".encode("utf-8"))
            time.sleep(5)
            ok, note = run_one(name)
        sys.stdout.buffer.write(
            (f"[{'PASS' if ok else 'FAIL'}] {name}｜{note}\n").encode("utf-8", "replace"))
        results.append((name, ok))

    failed = [name for name, ok in results if not ok]
    print()
    print(f"共 {len(results)} 个文件，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
