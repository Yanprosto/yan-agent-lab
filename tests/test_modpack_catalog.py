from __future__ import annotations

import io
import json
import zipfile

from PIL import Image

from mcbuild.modpack_catalog import compile_sector_palette, scan_mod_jars


def _png(rgb):
    image = Image.new("RGBA", (16, 16), (*rgb, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_scan_synthetic_mod_and_compile_palette(tmp_path):
    mods = tmp_path / "mods"
    mods.mkdir()
    jar = mods / "examplemod.jar"

    with zipfile.ZipFile(jar, "w") as zf:
        zf.writestr(
            "assets/example/blockstates/steel_panel.json",
            json.dumps({"variants": {"": {"model": "example:block/steel_panel"}}}),
        )
        zf.writestr(
            "assets/example/models/block/steel_panel.json",
            json.dumps({"parent": "minecraft:block/cube_all", "textures": {"all": "example:block/steel_panel"}}),
        )
        zf.writestr("assets/example/textures/block/steel_panel.png", _png((90, 100, 110)))

        zf.writestr(
            "assets/example/blockstates/industrial_lamp.json",
            json.dumps({"variants": {"": {"model": "example:block/industrial_lamp"}}}),
        )
        zf.writestr(
            "assets/example/models/block/industrial_lamp.json",
            json.dumps({"textures": {"all": "example:block/industrial_lamp"}}),
        )
        zf.writestr("assets/example/textures/block/industrial_lamp.png", _png((220, 190, 90)))

        zf.writestr(
            "data/c/tags/blocks/steel_blocks.json",
            json.dumps({"values": ["example:steel_panel"]}),
        )

    records = scan_mod_jars(mods)
    by_id = {record.block_id: record for record in records}

    assert "example:steel_panel" in by_id
    assert "structural" in by_id["example:steel_panel"].roles
    assert by_id["example:steel_panel"].features is not None
    assert by_id["example:steel_panel"].features.mean_rgb == (90, 100, 110)

    assert "example:industrial_lamp" in by_id
    assert "light" in by_id["example:industrial_lamp"].roles

    palette = compile_sector_palette(records, anchor_mods=["example"], per_role=5)
    structural = [row["block_id"] for row in palette["slots"]["structural"]]
    lights = [row["block_id"] for row in palette["slots"]["light"]]

    assert "example:steel_panel" in structural
    assert "example:industrial_lamp" in lights
