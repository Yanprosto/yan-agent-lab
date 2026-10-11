from mcbuild.server.delta import compute_block_delta
from build import load_models

def test_industrial_models_compile_to_live_delta():
    models = load_models()
    assert set(models) == {"vertical_foundry","industrial_canyon","terraced_megaforge"}
    for name, grid in models.items():
        assert len(grid) > 100_000, name
        assert all(isinstance(idx, int) for _, idx in grid.items()), name
        delta = compute_block_delta(None, grid)
        assert len(delta) == len(grid), name
        assert all(isinstance(row["block"], str) and row["block"] for row in delta), name
