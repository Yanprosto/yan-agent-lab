"""Local modpack asset catalog and palette compiler.

Scans NeoForge/Fabric-style mod JAR assets without launching Minecraft. The catalog is
intended to be joined with a live registry dump later, but already provides a cheap
visual index over a large modpack.

No network calls. Heavy image work happens on the user's machine.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import json
import math
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable

from PIL import Image, ImageFilter, ImageStat


BLOCKSTATE_RE = re.compile(r"^assets/([^/]+)/blockstates/(.+)\.json$")
MODEL_RE = re.compile(r"^assets/([^/]+)/models/block/(.+)\.json$")
TEXTURE_RE = re.compile(r"^assets/([^/]+)/textures/block/(.+)\.png$")
BLOCK_TAG_RE = re.compile(r"^data/([^/]+)/tags/blocks/(.+)\.json$")

ROLE_TOKENS: dict[str, tuple[str, ...]] = {
    "light": ("lamp", "light", "lantern", "bulb", "glow", "illumin", "neon"),
    "glass": ("glass", "window", "pane", "screen"),
    "pipe": ("pipe", "tube", "duct", "conduit", "hose"),
    "cable": ("cable", "wire", "busbar", "connector"),
    "rail": ("rail", "track", "girder"),
    "storage": ("crate", "barrel", "chest", "tank", "silo", "container"),
    "machine": (
        "machine", "crusher", "smelter", "furnace", "infuser", "factory", "generator",
        "turbine", "boiler", "pump", "motor", "press", "mixer", "mill", "assembler",
    ),
    "structural": (
        "brick", "tile", "panel", "plating", "sheet", "block", "concrete", "steel",
        "iron", "metal", "stone", "deepslate", "wall", "pillar", "beam", "frame",
    ),
    "floor": ("floor", "plate", "tile", "grate", "catwalk"),
    "decor": ("vent", "grill", "trim", "warning", "hazard", "support", "scaffold"),
}

FUNCTIONAL_ROLES = {"machine", "pipe", "cable", "rail", "storage"}

# Safety is intentionally conservative. Visual similarity is never permission to use
# a block as bulk architecture.
FORBIDDEN_TOKENS = (
    "creative", "admin", "debug", "command", "barrier", "structure_block",
    "spawner", "portal", "bedrock",
)
FUNCTIONAL_TOKENS = (
    "furnace", "smelter", "crusher", "infuser", "factory", "machine", "generator",
    "turbine", "boiler", "pump", "controller", "terminal", "crafting", "workbench",
    "anvil", "chest", "barrel", "tank", "silo", "storage", "battery", "energy_cube",
    "press", "mixer", "mill", "assembler", "deployer", "basin", "vault",
)
PRESTIGE_TOKENS = (
    "netherite", "diamond", "emerald", "unobtainium", "allthemodium", "vibranium",
    "ultimate", "elite", "atomic", "antimatter", "refined_obsidian",
)
CHEAP_ARCH_TOKENS = (
    "brick", "tile", "panel", "plating", "sheet", "concrete", "stone", "deepslate",
    "wall", "pillar", "beam", "frame", "grate", "catwalk", "scaffold", "trim",
)

SAFETY_CLASSES = ("architecture", "functional", "prestige", "forbidden")


@dataclass
class SafetyProfile:
    safety_class: str
    architecture_allowed: bool
    mass_use_allowed: bool
    progression_tier: str
    economic_cost: float
    reasons: list[str]


@dataclass
class TextureFeatures:
    mean_rgb: tuple[int, int, int]
    mean_hsv: tuple[float, float, float]
    luminance: float
    contrast: float
    saturation: float
    edge_density: float
    opacity: float


@dataclass
class BlockRecord:
    block_id: str
    namespace: str
    path: str
    source_jar: str
    model_refs: list[str]
    texture_refs: list[str]
    tags: list[str]
    roles: list[str]
    features: TextureFeatures | None
    safety: SafetyProfile

    def to_dict(self) -> dict:
        out = asdict(self)
        return out


@dataclass
class PaletteSlot:
    block_id: str
    score: float
    roles: list[str]
    source_jar: str
    mean_rgb: tuple[int, int, int] | None
    safety_class: str
    economic_cost: float
    progression_tier: str


def _safe_json(raw: bytes) -> dict:
    try:
        obj = json.loads(raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _model_refs(blockstate: dict) -> list[str]:
    refs: list[str] = []

    def add(value) -> None:
        if isinstance(value, dict):
            model = value.get("model")
            if isinstance(model, str):
                refs.append(model)
        elif isinstance(value, list):
            for item in value:
                add(item)

    variants = blockstate.get("variants")
    if isinstance(variants, dict):
        for value in variants.values():
            add(value)

    multipart = blockstate.get("multipart")
    if isinstance(multipart, list):
        for part in multipart:
            if isinstance(part, dict):
                add(part.get("apply"))

    return sorted(set(refs))


def _texture_refs(model: dict) -> list[str]:
    textures = model.get("textures")
    if not isinstance(textures, dict):
        return []
    refs = []
    for value in textures.values():
        if isinstance(value, str) and not value.startswith("#"):
            refs.append(value)
    return sorted(set(refs))


def _texture_features(raw: bytes) -> TextureFeatures | None:
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return None

    # Keep the scan bounded even for unusually large HD textures.
    image.thumbnail((96, 96), Image.Resampling.LANCZOS)
    pixels = list(image.getdata())
    visible = [(r, g, b, a) for r, g, b, a in pixels if a >= 24]
    if not visible:
        return None

    r = mean(p[0] for p in visible)
    g = mean(p[1] for p in visible)
    b = mean(p[2] for p in visible)
    alpha = mean(p[3] for p in visible) / 255.0

    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    lum_values = [
        0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]
        for p in visible
    ]
    lum = mean(lum_values) / 255.0
    variance = mean((x / 255.0 - lum) ** 2 for x in lum_values)
    contrast = math.sqrt(variance)

    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    edge_density = float(edge_stat.mean[0]) / 255.0

    return TextureFeatures(
        mean_rgb=(round(r), round(g), round(b)),
        mean_hsv=(round(h, 4), round(s, 4), round(v, 4)),
        luminance=round(lum, 4),
        contrast=round(contrast, 4),
        saturation=round(s, 4),
        edge_density=round(edge_density, 4),
        opacity=round(alpha, 4),
    )


def _roles(block_id: str, tags: Iterable[str]) -> list[str]:
    haystack = (block_id + " " + " ".join(tags)).lower()
    roles = [
        role
        for role, tokens in ROLE_TOKENS.items()
        if any(token in haystack for token in tokens)
    ]
    return sorted(set(roles or ["other"]))


def _contains_any(haystack: str, tokens: Iterable[str]) -> list[str]:
    return sorted({token for token in tokens if token in haystack})


def _safety_profile(block_id: str, roles: Iterable[str], tags: Iterable[str]) -> SafetyProfile:
    """Classify whether a block may be used by bulk architectural generation.

    This is a fail-closed static pass. Runtime registry/BlockEntity information can only
    make a block *more* restricted later, never less restricted automatically.
    """

    text = (block_id + " " + " ".join(tags) + " " + " ".join(roles)).lower()
    reasons: list[str] = []

    forbidden_hits = _contains_any(text, FORBIDDEN_TOKENS)
    if forbidden_hits:
        return SafetyProfile(
            safety_class="forbidden",
            architecture_allowed=False,
            mass_use_allowed=False,
            progression_tier="forbidden",
            economic_cost=1_000_000.0,
            reasons=[f"forbidden token: {token}" for token in forbidden_hits],
        )

    functional_hits = _contains_any(text, FUNCTIONAL_TOKENS)
    role_hits = sorted(set(roles) & FUNCTIONAL_ROLES)
    if functional_hits or role_hits:
        reasons.extend(f"functional token: {token}" for token in functional_hits)
        reasons.extend(f"functional role: {role}" for role in role_hits)
        return SafetyProfile(
            safety_class="functional",
            architecture_allowed=False,
            mass_use_allowed=False,
            progression_tier="planner_only",
            economic_cost=250.0,
            reasons=reasons,
        )

    prestige_hits = _contains_any(text, PRESTIGE_TOKENS)
    if prestige_hits:
        # Resource/alloy blocks are not forbidden: a later planner may spend a very
        # small prestige budget on them, but ordinary detail/grammar passes cannot.
        tier = "late_game"
        cost = 900.0
        if "diamond" in prestige_hits or "emerald" in prestige_hits:
            tier, cost = "rare", 120.0
        if "netherite" in prestige_hits:
            tier, cost = "very_rare", 900.0
        return SafetyProfile(
            safety_class="prestige",
            architecture_allowed=False,
            mass_use_allowed=False,
            progression_tier=tier,
            economic_cost=cost,
            reasons=[f"prestige token: {token}" for token in prestige_hits],
        )

    cheap_hits = _contains_any(text, CHEAP_ARCH_TOKENS)
    # Unknown decorative blocks are allowed into candidate review but get a higher
    # estimated cost. Explicit construction vocabulary gets the cheapest budget.
    if cheap_hits:
        return SafetyProfile(
            safety_class="architecture",
            architecture_allowed=True,
            mass_use_allowed=True,
            progression_tier="common",
            economic_cost=1.0,
            reasons=[f"architectural token: {token}" for token in cheap_hits],
        )

    return SafetyProfile(
        safety_class="architecture",
        architecture_allowed=True,
        mass_use_allowed=False,
        progression_tier="unclassified",
        economic_cost=8.0,
        reasons=["no dangerous signal; unclassified architecture candidate"],
    )


def _normalize_ref(ref: str, default_namespace: str, kind: str) -> str:
    if ":" in ref:
        namespace, path = ref.split(":", 1)
    else:
        namespace, path = default_namespace, ref
    if kind == "model":
        return f"assets/{namespace}/models/{path}.json"
    return f"assets/{namespace}/textures/{path}.png"


def scan_mod_jars(mods_dir: Path) -> list[BlockRecord]:
    jars = sorted(mods_dir.glob("*.jar"))
    records: list[BlockRecord] = []

    for jar in jars:
        try:
            zf = zipfile.ZipFile(jar)
        except zipfile.BadZipFile:
            continue

        with zf:
            names = set(zf.namelist())
            blockstates: dict[tuple[str, str], dict] = {}
            models: dict[str, dict] = {}
            tags_by_block: dict[str, set[str]] = {}

            for name in names:
                m = BLOCKSTATE_RE.match(name)
                if m:
                    ns, path = m.groups()
                    blockstates[(ns, path)] = _safe_json(zf.read(name))
                    continue

                m = MODEL_RE.match(name)
                if m:
                    models[name] = _safe_json(zf.read(name))
                    continue

                m = BLOCK_TAG_RE.match(name)
                if m:
                    tag_ns, tag_path = m.groups()
                    payload = _safe_json(zf.read(name))
                    values = payload.get("values")
                    if isinstance(values, list):
                        tag_id = f"{tag_ns}:{tag_path}"
                        for value in values:
                            if isinstance(value, str) and not value.startswith("#"):
                                tags_by_block.setdefault(value, set()).add(tag_id)

            for (namespace, path), state in blockstates.items():
                block_id = f"{namespace}:{path}"
                model_refs = _model_refs(state)
                texture_refs: list[str] = []
                feature_samples: list[TextureFeatures] = []

                for model_ref in model_refs:
                    model_path = _normalize_ref(model_ref, namespace, "model")
                    model = models.get(model_path)
                    if not model:
                        # Models may live in another JAR or inherit from another namespace.
                        continue
                    for texture_ref in _texture_refs(model):
                        texture_refs.append(texture_ref)
                        texture_path = _normalize_ref(texture_ref, namespace, "texture")
                        if texture_path in names:
                            features = _texture_features(zf.read(texture_path))
                            if features:
                                feature_samples.append(features)

                # Strong fallback for ordinary cube blocks.
                same_name_texture = f"assets/{namespace}/textures/block/{path}.png"
                if not feature_samples and same_name_texture in names:
                    features = _texture_features(zf.read(same_name_texture))
                    if features:
                        feature_samples.append(features)
                        texture_refs.append(f"{namespace}:block/{path}")

                merged = merge_features(feature_samples)
                tags = sorted(tags_by_block.get(block_id, set()))
                records.append(
                    BlockRecord(
                        block_id=block_id,
                        namespace=namespace,
                        path=path,
                        source_jar=jar.name,
                        model_refs=model_refs,
                        texture_refs=sorted(set(texture_refs)),
                        tags=tags,
                        roles=_roles(block_id, tags),
                        features=merged,
                        safety=_safety_profile(block_id, _roles(block_id, tags), tags),
                    )
                )

    # Different JARs can expose duplicate assets. Prefer the last unique block id in
    # deterministic jar order so the catalog stays stable.
    dedup: dict[str, BlockRecord] = {}
    for record in records:
        dedup[record.block_id] = record
    return sorted(dedup.values(), key=lambda r: r.block_id)


def merge_features(samples: list[TextureFeatures]) -> TextureFeatures | None:
    if not samples:
        return None

    return TextureFeatures(
        mean_rgb=tuple(round(mean(s.mean_rgb[i] for s in samples)) for i in range(3)),
        mean_hsv=tuple(round(mean(s.mean_hsv[i] for s in samples), 4) for i in range(3)),
        luminance=round(mean(s.luminance for s in samples), 4),
        contrast=round(mean(s.contrast for s in samples), 4),
        saturation=round(mean(s.saturation for s in samples), 4),
        edge_density=round(mean(s.edge_density for s in samples), 4),
        opacity=round(mean(s.opacity for s in samples), 4),
    )


def _feature_distance(a: TextureFeatures, b: TextureFeatures) -> float:
    # Perceptual-ish cheap metric. Hue wraps; saturation is downweighted for dark blocks.
    ah, ass, av = a.mean_hsv
    bh, bss, bv = b.mean_hsv
    hue = min(abs(ah - bh), 1.0 - abs(ah - bh))
    return (
        hue * 1.6
        + abs(ass - bss) * 0.8
        + abs(av - bv) * 1.2
        + abs(a.contrast - b.contrast) * 0.7
        + abs(a.edge_density - b.edge_density) * 0.45
    )


def _anchor_profile(records: list[BlockRecord], anchor_mods: set[str], anchor_blocks: set[str]) -> TextureFeatures | None:
    samples = [
        r.features
        for r in records
        if r.features is not None and (r.namespace in anchor_mods or r.block_id in anchor_blocks)
    ]
    return merge_features([s for s in samples if s is not None])


def compile_sector_palette(
    records: list[BlockRecord],
    *,
    anchor_mods: Iterable[str] = (),
    anchor_blocks: Iterable[str] = (),
    per_role: int = 12,
) -> dict:
    anchor_mod_set = {x.lower() for x in anchor_mods}
    anchor_block_set = {x.lower() for x in anchor_blocks}
    profile = _anchor_profile(records, anchor_mod_set, anchor_block_set)

    slots: dict[str, list[PaletteSlot]] = {}
    wanted_roles = ("structural", "floor", "decor", "light", "glass", "pipe", "cable", "rail", "storage", "machine")

    for role in wanted_roles:
        candidates: list[PaletteSlot] = []
        for record in records:
            if role not in record.roles or record.features is None:
                continue

            score = 50.0
            if profile is not None:
                score += max(0.0, 40.0 - _feature_distance(record.features, profile) * 28.0)

            # Reward modded blocks so vanilla doesn't dominate a huge modpack.
            if record.namespace != "minecraft":
                score += 6.0

            architecture_role = role in {"structural", "floor", "decor", "light", "glass"}

            # Hard safety gate: visual compatibility never overrides permission.
            if architecture_role and not record.safety.architecture_allowed:
                continue
            if role in {"structural", "floor", "decor"} and not record.safety.mass_use_allowed:
                # Unknown blocks may still appear in catalog/review, but not in the
                # automatically-repeatable bulk palette.
                continue

            # For architecture, prefer opaque, cheap, reusable blocks.
            if architecture_role:
                score += record.features.opacity * 5.0
                score -= min(35.0, math.log10(max(1.0, record.safety.economic_cost)) * 12.0)

            # Functional anchors should remain available even if visually odd.
            if record.namespace in anchor_mod_set or record.block_id in anchor_block_set:
                score += 12.0

            candidates.append(
                PaletteSlot(
                    block_id=record.block_id,
                    score=round(score, 3),
                    roles=record.roles,
                    source_jar=record.source_jar,
                    mean_rgb=record.features.mean_rgb,
                    safety_class=record.safety.safety_class,
                    economic_cost=record.safety.economic_cost,
                    progression_tier=record.safety.progression_tier,
                )
            )

        candidates.sort(key=lambda c: (-c.score, c.block_id))
        slots[role] = candidates[:per_role]

    return {
        "schema_version": 2,
        "safety_policy": {
            "architecture_slots": "hard-gated to architecture_allowed",
            "bulk_slots": "hard-gated to mass_use_allowed",
            "functional_blocks": "planner_only",
            "prestige_blocks": "budgeted_explicit_use_only",
            "forbidden_blocks": "never_auto_place",
        },
        "anchor_mods": sorted(anchor_mod_set),
        "anchor_blocks": sorted(anchor_block_set),
        "anchor_profile": asdict(profile) if profile else None,
        "slots": {
            role: [asdict(item) for item in items]
            for role, items in slots.items()
        },
    }


def catalog_fingerprint(records: list[BlockRecord]) -> str:
    payload = "\n".join(r.block_id for r in records).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
