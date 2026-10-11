from pathlib import Path

from mcbuild import palette
from mcbuild.sector_materials import SectorMaterials, _runtime_reject, apply_to_industrial_study


def test_external_block_registration_round_trip():
    block = palette.register_external_block('examplemod:test_block', (12, 34, 56))
    looked_up = palette.get_block('examplemod:test_block')
    assert looked_up.index == block.index
    assert looked_up.mc_id == 'examplemod:test_block'
    assert looked_up.rgb == (12, 34, 56)
    assert palette.get_block_by_index(block.index).mc_id == 'examplemod:test_block'


def test_external_state_preserves_namespace():
    palette.register_external_block('examplemod:panel', (90, 90, 90))
    block = palette.get_block('examplemod:panel[facing=north]')
    assert block.mc_id == 'examplemod:panel[facing=north]'


def test_apply_materials_replaces_study_palette():
    target = {}
    mats = SectorMaterials(
        dark_structure='minecraft:deepslate_tiles',
        structure='examplemod:plastic',
        wall='minecraft:smooth_stone',
        floor='examplemod:road',
        warm_accent='minecraft:cut_copper',
        warning='minecraft:yellow_concrete',
        light='examplemod:glow',
        dark_fill='minecraft:black_concrete',
        secondary_floor='minecraft:polished_andesite',
    )
    apply_to_industrial_study(mats, target)
    assert target['D'] == 'minecraft:deepslate_tiles'
    assert target['M'] == 'examplemod:road'
    assert target['L'] == 'examplemod:glow'


def test_runtime_rejects_coral_family_by_class_hierarchy():
    block = {
        'runtime': {
            'block_class_hierarchy': [
                'net.minecraft.world.level.block.BaseCoralPlantTypeBlock',
                'net.minecraft.world.level.block.Block',
            ]
        }
    }
    assert _runtime_reject(block)


def test_runtime_rejects_rail_family_by_class_hierarchy():
    block = {
        'runtime': {
            'block_class_hierarchy': [
                'net.minecraft.world.level.block.PoweredRailBlock',
                'net.minecraft.world.level.block.BaseRailBlock',
                'net.minecraft.world.level.block.Block',
            ]
        }
    }
    assert _runtime_reject(block)
