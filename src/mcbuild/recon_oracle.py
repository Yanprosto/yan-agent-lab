"""Runtime access to the compact generated Minecraft/Mekanism recon oracle."""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

_ORACLE = Path(__file__).resolve().parents[2] / "docs" / "recon" / "generated" / "minecraft_lab_oracle.json"

@lru_cache(maxsize=1)
def load_minecraft_lab_oracle() -> dict:
    if not _ORACLE.exists():
        raise FileNotFoundError(f"Compact recon oracle not generated: {_ORACLE}")
    return json.loads(_ORACLE.read_text(encoding="utf-8"))

def system(label: str) -> dict:
    return load_minecraft_lab_oracle()["systems"][label]

def capability_hits(label: str, capability: str) -> dict:
    return system(label)["capability_index"][capability]
