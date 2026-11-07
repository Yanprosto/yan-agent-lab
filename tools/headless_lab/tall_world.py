"""Tall-world check on the headless lab (Dynamic Height mod).

Boots a fresh lab world with chosen height limits, measures it, builds a tower over the
whole height, runs Mekanism machine probes at chosen heights, restarts the server and
checks that the extreme blocks persisted.

    python tools/headless_lab/tall_world.py --level tall4k --min-y -128 --max-y 3967 \
        --probe "mekanism:crusher|300 3000 300" --probe "mekanism:energized_smelter|340 -100 300"

Needs ``dynamicheight-*.jar`` in the lab server's mods folder (Modrinth project
``dynamic-height``, NeoForge 1.21.1). Facts found with this tool (docs/recon/TALL_WORLD_SPIKE.md):
the mod reads ``data/dynamic_height_minecraft_overworld.config`` (not ``.json``, as its page says),
clamps ``maxY`` to 32752 (highest block 32751) and ``minY`` to -128.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

import rcon_client

REPO = Path(__file__).resolve().parents[2]
LAB = Path(os.environ.get("YAN_LAB_DIR", "~/mc-lab")).expanduser()
SERVER = LAB / "server"
LOG = LAB / "server.out"
AREA = (-64, -64, 79, 79)  # 9 x 9 chunks measured in every world


def rcon(*commands: str) -> str:
    return rcon_client.run(list(commands))


def last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith(">")]
    return lines[-1] if lines else ""


def java_pid() -> int | None:
    out = subprocess.run(["pgrep", "-f", "neoforge/21.1.255/unix_args"], capture_output=True, text=True)
    pids = [int(p) for p in out.stdout.split()]
    return pids[-1] if pids else None


def rss_mb() -> int | None:
    pid = java_pid()
    if pid is None:
        return None
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return round(int(out) / 1024) if out else None


def start(level: str, timeout: float = 400) -> dict[str, float | bool]:
    props = (SERVER / "server.properties").read_text()
    (SERVER / "server.properties").write_text(re.sub(r"^level-name=.*$", f"level-name={level}", props, flags=re.M))
    began = time.monotonic()
    subprocess.Popen(
        ["bash", "run.sh", "nogui"], cwd=SERVER, stdout=LOG.open("w"), stderr=subprocess.STDOUT, start_new_session=True
    )
    while time.monotonic() - began < timeout:
        text = LOG.read_text(errors="replace") if LOG.exists() else ""
        done = re.search(r"Done \(([\d.]+)s\)", text)
        if done:
            return {"wall_s": round(time.monotonic() - began, 1), "server_s": float(done.group(1)), "crash": False}
        if "Crash report" in text or "Failed to start" in text:
            return {"wall_s": round(time.monotonic() - began, 1), "crash": True}
        time.sleep(1)
    return {"wall_s": timeout, "crash": True}


def stop() -> None:
    with contextlib.suppress(OSError):
        rcon("stop")
    for _ in range(60):
        if java_pid() is None:
            return
        time.sleep(1)


def write_height(level: str, min_y: int, max_y: int) -> None:
    path = SERVER / level / "data" / "dynamic_height_minecraft_overworld.config"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": "dynamicheight-worldheight-v1", "minY": min_y, "maxY": max_y}))


def world_mb(level: str) -> float:
    return round(sum(f.stat().st_size for f in (SERVER / level).rglob("*") if f.is_file()) / 1048576, 1)


def measure(y_probe: int = 0, timeout: float = 600) -> dict[str, object]:
    x0, z0, x1, z1 = AREA
    began = time.monotonic()
    rcon(f"forceload add {x0} {z0} {x1} {z1}")
    loaded = False
    while time.monotonic() - began < timeout and not loaded:
        loaded = (
            rcon(f"execute if loaded {x1} {y_probe} {z1}", f"execute if loaded {x0} {y_probe} {z0}").count(
                "Test passed"
            )
            == 2
        )
        time.sleep(0.5)
    load_s = round(time.monotonic() - began, 1)
    time.sleep(10)
    tick = re.search(r"Average time per tick: ([\d.]+)ms", rcon("tick query"))
    return {
        "chunks_loaded": loaded,
        "load_s": load_s,
        "avg_tick_ms": float(tick.group(1)) if tick else None,
        "rss_mb": rss_mb(),
    }


def build_tower(min_y: int, max_y: int) -> int:
    """Hollow 8x8 stone-brick tower over the whole height; ``fill`` is limited to 32768 blocks."""
    y, fills = min_y + 4, 0
    while y <= max_y - 4:
        top = min(y + 511, max_y - 4)
        rcon(f"fill 4 {y} 4 11 {top} 11 minecraft:stone_bricks hollow")
        fills += 1
        y = top + 1
    return fills


def run_probe(machine: str, pos: str, timeout: int = 500) -> str:
    env = {**os.environ, "YAN_LAB_DIR": str(LAB), "YAN_RUNTIME_LOGS_ENABLED": "0"}
    done = subprocess.run(
        ["uv", "run", "python", "tools/headless_lab/run.py", "machine", "--spec", machine, "--pos", pos]
        + ["--timeout", str(timeout)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout + 60,
    )
    lines = [line for line in done.stdout.splitlines() if "yan-agent" in line]
    return lines[-1][:300] if lines else (done.stdout + done.stderr)[-300:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", required=True)
    parser.add_argument("--min-y", type=int, required=True)
    parser.add_argument("--max-y", type=int, required=True)
    parser.add_argument("--probe", action="append", default=[], help="'<machine id>|<x y z>'")
    args = parser.parse_args()

    write_height(args.level, args.min_y, args.max_y)
    print("start", start(args.level))
    config = (SERVER / args.level / "data" / "dynamic_height_minecraft_overworld.config").read_text()
    print("effective config:", json.loads(config))
    rcon("forceload add 0 0 15 15")
    time.sleep(3)
    print("measure", json.dumps(measure()))

    def placeable(y: int) -> bool:
        return "Changed" in rcon(f"setblock 3 {y} 3 minecraft:iron_block")

    low, high = args.min_y, args.max_y + 40000
    while high - low > 1:
        mid = (low + high) // 2
        low, high = (mid, high) if placeable(mid) else (low, mid)
    top = low
    below = placeable(args.min_y - 1)
    print(f"highest placeable y: {top}; one below min placeable: {below}")

    began = time.monotonic()
    print("tower fills:", build_tower(args.min_y, top), f"in {time.monotonic() - began:.1f}s")
    rcon(f"setblock 1 {top} 1 minecraft:gold_block", f"fill 4 {top - 99} 4 11 {top} 11 minecraft:stone_bricks hollow")
    began = time.monotonic()
    rcon("save-all flush")
    print(f"save: {time.monotonic() - began:.1f}s, world {world_mb(args.level)} MB, rss {rss_mb()} MB")
    for item in args.probe:
        machine, pos = item.split("|")
        print(f"probe {machine} at {pos}:", run_probe(machine, pos))
    stop()

    print("restart", start(args.level))
    rcon("forceload add 0 0 15 15")
    time.sleep(4)
    mid = (top + args.min_y) // 2
    checks = {
        f"gold block y={top}": f"execute if block 1 {top} 1 minecraft:gold_block",
        f"tower wall y={top}": f"execute if block 4 {top} 4 minecraft:stone_bricks",
        f"tower wall y={mid}": f"execute if block 4 {mid} 4 minecraft:stone_bricks",
        f"bedrock y={args.min_y}": f"execute if block 0 {args.min_y} 0 minecraft:bedrock",
    }
    for label, command in checks.items():
        print("after restart:", label, "->", last_line(rcon(command)))
    stop()


if __name__ == "__main__":
    main()
