"""Development autoreloader for mcbuild-server.

Runs the regular websocket server in a child Python process, watches src/mcbuild/**/*.py
for mtime changes, and restarts only the Python server when code changes.

This intentionally avoids touching Minecraft/NeoForge; Java changes still require a JAR
rebuild + Minecraft restart.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def _snapshot(root: Path) -> dict[Path, int]:
    result: dict[Path, int] = {}
    for path in root.rglob("*.py"):
        try:
            result[path] = path.stat().st_mtime_ns
        except FileNotFoundError:
            pass
    return result


def _changed(before: dict[Path, int], after: dict[Path, int]) -> list[Path]:
    keys = set(before) | set(after)
    return sorted(path for path in keys if before.get(path) != after.get(path))


def _start_child(host: str, port: int) -> subprocess.Popen[str]:
    cmd = [
        sys.executable,
        "-m",
        "mcbuild.server.ws_server",
        "--host",
        host,
        "--port",
        str(port),
    ]
    print(f"[yan-dev] starting: {' '.join(cmd)}", flush=True)
    return subprocess.Popen(cmd, text=True)


def _stop_child(child: subprocess.Popen[str], timeout: float = 5.0) -> None:
    if child.poll() is not None:
        return
    print("[yan-dev] stopping mcbuild-server...", flush=True)
    if os.name == "nt":
        child.terminate()
    else:
        child.send_signal(signal.SIGTERM)
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print("[yan-dev] graceful stop timed out; killing process.", flush=True)
        child.kill()
        child.wait(timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-reloading development wrapper for mcbuild-server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[3]
    watch_root = project_root / "src" / "mcbuild"
    if not watch_root.exists():
        raise SystemExit(f"watch root not found: {watch_root}")

    print(f"[yan-dev] watching {watch_root}", flush=True)
    print("[yan-dev] Python edits will restart mcbuild-server automatically.", flush=True)
    print("[yan-dev] Java/JAR edits still require rebuilding the mod and restarting Minecraft.", flush=True)

    snapshot = _snapshot(watch_root)
    child = _start_child(args.host, args.port)

    try:
        while True:
            time.sleep(max(0.1, args.interval))

            if child.poll() is not None:
                code = child.returncode
                print(f"[yan-dev] mcbuild-server exited with code {code}; restarting...", flush=True)
                time.sleep(0.5)
                child = _start_child(args.host, args.port)

            current = _snapshot(watch_root)
            changes = _changed(snapshot, current)
            if not changes:
                continue

            snapshot = current
            shown = ", ".join(str(path.relative_to(project_root)) for path in changes[:8])
            if len(changes) > 8:
                shown += f", ... (+{len(changes) - 8})"
            print(f"[yan-dev] change detected: {shown}", flush=True)

            _stop_child(child)
            # Give Windows a brief moment to release 127.0.0.1:8765 before rebinding.
            time.sleep(0.35)
            child = _start_child(args.host, args.port)

    except KeyboardInterrupt:
        print("\n[yan-dev] stopping autoreloader.", flush=True)
    finally:
        _stop_child(child)


if __name__ == "__main__":
    main()
