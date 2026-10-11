param(
    [ValidateSet("vertical_foundry","industrial_canyon","terraced_megaforge")]
    [string]$Kind = "vertical_foundry",
    [string]$Repo = "D:\YAN_AGENT_LAB"
)

$ErrorActionPreference = "Stop"
Set-Location $Repo

$env:PYTHONPATH = "src;."
uv run python examples\industrial_sector_study\build_with_palette.py --kind "$Kind"
if ($LASTEXITCODE -ne 0) { throw "Mixed sector build failed" }
