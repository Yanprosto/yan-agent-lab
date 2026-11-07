"""Run one YAN experiment on the headless lab server and report its verdict.

Usage:
    python tools/headless_lab/run.py splitter [--lab ~/mc-lab] [--timeout 900]

Starts the NeoForge lab server and the Python agent server if they are not
running, force-loads the lab area, issues `/yanlab <experiment> 0 -60 0` over
RCON and waits for the `[yan-agent] ... PASS|FAIL` line. Exit code 0 on PASS.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rcon_client  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
VERDICT = re.compile(r"\[yan-agent\] (.*\b(PASS|FAIL)\b.*|.*error: .*)")


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_for(predicate, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1)
    raise TimeoutError(f"timed out waiting for {what}")


def ensure_servers(lab: Path) -> Path:
    log = lab / "server.out"
    if not _port_open(25575):
        subprocess.Popen(
            ["bash", "run.sh", "nogui"],
            cwd=lab / "server",
            stdout=log.open("w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _wait_for(lambda: _port_open(25575), 300, "lab server RCON")
    if not _port_open(8765):
        env = {**os.environ, "YAN_RUNTIME_LOGS_ENABLED": os.environ.get("YAN_RUNTIME_LOGS_ENABLED", "0")}
        subprocess.Popen(
            ["uv", "run", "mcbuild-server"],
            cwd=REPO,
            env=env,
            stdout=(lab / "agent.out").open("w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _wait_for(lambda: _port_open(8765), 120, "agent server")
    return log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment", choices=["experiment", "mekanism", "splitter"])
    parser.add_argument("--lab", type=Path, default=Path(os.environ.get("YAN_LAB_DIR", "~/mc-lab")).expanduser())
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()

    log = ensure_servers(args.lab)
    offset = log.stat().st_size
    print(rcon_client.run(["forceload add -32 -32 63 63", f"yanlab {args.experiment} 0 -60 0"]))

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        with log.open(errors="replace") as handle:
            handle.seek(offset)
            for line in handle:
                match = VERDICT.search(line)
                if match:
                    print(match.group(0))
                    return 0 if match.group(2) == "PASS" else 1
        time.sleep(2)
    print(f"no verdict within {args.timeout:.0f}s", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
