from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

MEKANISM_PATTERNS = {
    "core": re.compile(r"^Mekanism-1\.21\.1-.*\.jar$", re.I),
    "generators": re.compile(r"^MekanismGenerators-1\.21\.1-.*\.jar$", re.I),
    "tools": re.compile(r"^MekanismTools-1\.21\.1-.*\.jar$", re.I),
    "additions": re.compile(r"^MekanismAdditions-1\.21\.1-.*\.jar$", re.I),
}

TARGET_KEYWORDS = {
    "core": (
        "tileentity", "machine", "factory", "smelter", "crusher", "enrichment",
        "infuser", "transporter", "cable", "pipe", "tube", "network", "inventory",
        "energy", "chemical", "fluid", "config", "side", "ejector", "sorter",
        "recipe", "tier", "storage", "qio", "teleporter", "laser",
    ),
    "generators": (
        "generator", "turbine", "fission", "fusion", "reactor", "solar", "wind",
        "bio", "heat", "gas", "energy", "boiler", "rotary", "multiblock",
        "controller", "valve", "port", "tank",
    ),
    "tools": (
        "tool", "armor", "paxel", "pickaxe", "axe", "shovel", "hoe", "sword",
        "shield", "material", "tier", "module", "mekasuit",
    ),
    "additions": (
        "balloon", "glow", "plastic", "obsidian", "tnt", "baby", "walkie",
        "block", "item", "slab", "stairs", "fence", "light",
    ),
    "vanilla": (
        "block", "blocks", "blockstate", "blockentity", "item", "recipe", "loot",
        "tag", "registry", "furnace", "anvil", "hopper", "chest", "barrel",
        "crafting", "redstone", "rail", "piston", "light", "fluid", "material",
    ),
}

RESOURCE_PREFIXES = ("assets/", "data/", "META-INF/")


@dataclass
class JarSummary:
    label: str
    path: str
    size: int
    classes: int
    resources: int
    namespaces: list[str]
    recipes: int
    loot_tables: int
    block_tags: int
    item_tags: int
    blockstates: int
    block_models: int
    block_textures: int


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def ensure_um() -> str:
    found = shutil.which("um")
    if found:
        return found
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Neither 'um' nor 'uv' is on PATH. Install uv first.")
    print("[YAN] Universal Modder CLI not found; installing with uv tool...")
    p = run([uv, "tool", "install", "git+https://github.com/rehan-remade/universal-modder"], timeout=600)
    print(p.stdout)
    found = shutil.which("um")
    return found or "uvx"


def call_um(um: str, args: list[str], out_file: Path, timeout: int = 300) -> None:
    if um == "uvx":
        cmd = ["uvx", "--from", "git+https://github.com/rehan-remade/universal-modder", "um", *args]
    else:
        cmd = [um, *args]
    try:
        p = run(cmd, timeout=timeout)
        out_file.write_text(p.stdout, encoding="utf-8")
        print(f"[YAN] wrote {out_file}")
    except Exception as exc:
        out_file.write_text(f"FAILED: {exc}\n", encoding="utf-8")
        print(f"[YAN] Universal Modder call failed: {exc}")


def find_mekanism_jars(mods: Path) -> dict[str, Path]:
    files = [p for p in mods.glob("*.jar") if p.is_file()]
    found: dict[str, Path] = {}
    for label, pattern in MEKANISM_PATTERNS.items():
        matches = [p for p in files if pattern.match(p.name)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one {label} Mekanism jar, found: {[p.name for p in matches]}")
        found[label] = matches[0]
    return found


def is_vanilla_client_jar(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            return (
                "net/minecraft/world/level/block/Blocks.class" in names
                and "net/minecraft/world/item/Items.class" in names
            )
    except Exception:
        return False


def find_vanilla_jar(launcher_root: Path, instance: Path) -> Path:
    candidates: list[Path] = []
    for root in (instance, launcher_root):
        if not root.exists():
            continue
        for p in root.rglob("*.jar"):
            name = p.name.lower()
            if "1.21.1" in name or "client" in name or "minecraft" in name:
                candidates.append(p)

    candidates = sorted(
        set(candidates),
        key=lambda p: (("1.21.1" not in p.name), -p.stat().st_size),
    )
    for p in candidates:
        if is_vanilla_client_jar(p):
            return p
    raise RuntimeError(
        "Could not locate the vanilla 1.21.1 client jar automatically. "
        "Pass --vanilla-jar explicitly."
    )


def summarize_jar(label: str, jar: Path) -> tuple[JarSummary, list[str]]:
    with zipfile.ZipFile(jar) as zf:
        names = zf.namelist()

    classes = [n for n in names if n.endswith(".class")]
    resources = [n for n in names if not n.endswith(".class") and n.startswith(RESOURCE_PREFIXES)]
    namespaces = sorted({
        n.split("/", 2)[1]
        for n in names
        if (n.startswith("assets/") or n.startswith("data/")) and n.count("/") >= 2
    })

    summary = JarSummary(
        label=label,
        path=str(jar),
        size=jar.stat().st_size,
        classes=len(classes),
        resources=len(resources),
        namespaces=namespaces,
        recipes=sum("/recipe/" in n or "/recipes/" in n for n in names if n.endswith(".json")),
        loot_tables=sum("/loot_table/" in n or "/loot_tables/" in n for n in names if n.endswith(".json")),
        block_tags=sum("/tags/block/" in n or "/tags/blocks/" in n for n in names if n.endswith(".json")),
        item_tags=sum("/tags/item/" in n or "/tags/items/" in n for n in names if n.endswith(".json")),
        blockstates=sum("/blockstates/" in n for n in names if n.endswith(".json")),
        block_models=sum("/models/block/" in n for n in names if n.endswith(".json")),
        block_textures=sum("/textures/block/" in n for n in names if n.lower().endswith(".png")),
    )
    return summary, names


def class_name(entry: str) -> str:
    return entry[:-6].replace("/", ".")


def class_score(name: str, keywords: tuple[str, ...]) -> int:
    low = name.lower()
    score = sum(5 for kw in keywords if kw in low)
    if "$" not in name:
        score += 2
    if any(part in low for part in (".client.", ".datagen.", ".integration.", ".compat.")):
        score -= 4
    return score


def select_classes(names: list[str], label: str, limit: int) -> list[str]:
    keywords = TARGET_KEYWORDS[label]
    classes = [
        class_name(n)
        for n in names
        if n.endswith(".class") and not n.endswith("module-info.class")
    ]
    ranked = sorted(
        ((class_score(c, keywords), c) for c in classes),
        key=lambda x: (-x[0], x[1]),
    )
    return [c for score, c in ranked if score > 2][:limit]


def javap_dump(jar: Path, classes: list[str], out_dir: Path, javap: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    failed = 0
    failures = []

    for i, cls in enumerate(classes, 1):
        safe = cls.replace(".", "_").replace("$", "__")
        target = out_dir / f"{safe}.txt"
        try:
            p = run([javap, "-classpath", str(jar), "-p", "-c", "-s", cls], timeout=45)
            target.write_text(p.stdout, encoding="utf-8")
            if p.returncode == 0:
                ok += 1
            else:
                failed += 1
                failures.append({"class": cls, "returncode": p.returncode})
        except Exception as exc:
            failed += 1
            target.write_text(f"FAILED: {exc}\n", encoding="utf-8")
            failures.append({"class": cls, "error": repr(exc)})

        if i % 50 == 0:
            print(f"[YAN] javap {jar.name}: {i}/{len(classes)}")

    return {"requested": len(classes), "ok": ok, "failed": failed, "failures": failures}


def resource_index(names: list[str]) -> dict:
    suffix = Counter()
    roots = Counter()
    for n in names:
        if n.endswith("/"):
            continue
        suffix[Path(n).suffix.lower() or "<none>"] += 1
        roots[n.split("/", 1)[0]] += 1
    return {"extensions": dict(suffix.most_common()), "roots": dict(roots.most_common())}


def extract_semantic_resources(jar: Path, names: list[str], out_dir: Path) -> dict:
    wanted_markers = (
        "/recipe/", "/recipes/", "/tags/",
        "/loot_table/", "/loot_tables/",
        "/blockstates/", "/models/block/",
        "META-INF/neoforge.mods.toml", "META-INF/mods.toml",
    )
    copied = 0
    with zipfile.ZipFile(jar) as zf:
        for name in names:
            if not name.endswith((".json", ".toml")):
                continue
            if not any(marker in name for marker in wanted_markers):
                continue
            dest = out_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(zf.read(name))
                copied += 1
            except Exception:
                pass
    return {"copied": copied}


def write_summary(out: Path, manifest: dict) -> None:
    lines = [
        "# YAN Minecraft lab recon",
        "",
        f"Run: {manifest['run_id']}",
        "",
        "Scope: vanilla 1.21.1 + Mekanism Core/Generators/Tools/Additions.",
        "This is recon evidence, not a palette.",
        "",
        "| label | classes | blockstates | models | recipes | block tags | loot |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in manifest["jars"]:
        lines.append(
            f"| {row['label']} | {row['classes']} | {row['blockstates']} | "
            f"{row['block_models']} | {row['recipes']} | {row['block_tags']} | {row['loot_tables']} |"
        )
    lines += [
        "",
        "The previous verified Mekanism audit remains valid. This run extends it to the complete official Mekanism family and vanilla.",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--instance",
        type=Path,
        default=Path(r"C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft"),
    )
    ap.add_argument(
        "--launcher-root",
        type=Path,
        default=Path(r"C:\Users\yan\AppData\Roaming\ElyPrismLauncher"),
    )
    ap.add_argument("--vanilla-jar", type=Path)
    ap.add_argument("--out", type=Path, default=Path(r"D:\YAN_RECON"))
    ap.add_argument("--mekanism-class-limit", type=int, default=220)
    ap.add_argument("--vanilla-class-limit", type=int, default=320)
    args = ap.parse_args()

    mods = args.instance / "mods"
    if not mods.is_dir():
        raise SystemExit(f"mods folder not found: {mods}")

    javap = shutil.which("javap")
    if not javap:
        raise SystemExit("javap not found. Use JDK 21 / ensure JAVA_HOME\\bin is on PATH.")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = args.out / f"minecraft_lab_{run_id}"
    root.mkdir(parents=True, exist_ok=True)
    print(f"[YAN] output: {root}")

    um = ensure_um()
    um_dir = root / "universal_modder"
    um_dir.mkdir()
    call_um(um, ["scan", str(args.instance), "--json"], um_dir / "scan.json.txt", timeout=300)
    call_um(um, ["kb", "search", "minecraft mekanism"], um_dir / "kb_minecraft_mekanism.txt", timeout=180)
    call_um(um, ["kb", "search", "minecraft neoforge"], um_dir / "kb_minecraft_neoforge.txt", timeout=180)

    jars = find_mekanism_jars(mods)
    jars["vanilla"] = args.vanilla_jar or find_vanilla_jar(args.launcher_root, args.instance)

    manifest = {
        "run_id": run_id,
        "instance": str(args.instance),
        "mods_dir": str(mods),
        "launcher_root": str(args.launcher_root),
        "java": run(["java", "-version"]).stdout,
        "javap_executable": javap,
        "universal_modder": um,
        "jars": [],
        "javap": {},
        "resources": {},
    }

    for label, jar in jars.items():
        print(f"[YAN] indexing {label}: {jar.name}")
        summary, names = summarize_jar(label, jar)
        manifest["jars"].append(asdict(summary))

        jar_out = root / label
        jar_out.mkdir()
        (jar_out / "entries.txt").write_text("\n".join(names), encoding="utf-8")
        (jar_out / "resource_index.json").write_text(
            json.dumps(resource_index(names), indent=2),
            encoding="utf-8",
        )

        limit = args.vanilla_class_limit if label == "vanilla" else args.mekanism_class_limit
        chosen = select_classes(names, label, limit)
        (jar_out / "selected_classes.txt").write_text("\n".join(chosen), encoding="utf-8")
        manifest["javap"][label] = javap_dump(jar, chosen, jar_out / "javap", javap)

        semantic = jar_out / "semantic_resources"
        semantic.mkdir()
        manifest["resources"][label] = extract_semantic_resources(jar, names, semantic)

    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_summary(root / "README.md", manifest)
    archive = shutil.make_archive(str(root), "zip", root_dir=root)

    print("")
    print("=" * 80)
    print("YAN MINECRAFT LAB RECON COMPLETE")
    print("=" * 80)
    print(f"archive: {archive}")
    print("Upload that ZIP back into the chat.")


if __name__ == "__main__":
    main()
