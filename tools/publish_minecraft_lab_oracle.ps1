param(
    [string]$Repo = "D:\YAN_AGENT_LAB",
    [string]$ReconRoot = "D:\YAN_RECON",
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
Set-Location $Repo
uv run python tools\distill_minecraft_lab_recon.py --repo "$Repo" --recon-root "$ReconRoot"
if ($LASTEXITCODE -ne 0) { throw "Distiller failed" }
$paths = @("docs/recon/generated/minecraft_lab_oracle.json","docs/recon/generated/minecraft_lab_oracle.md")
git add -- $paths
$changes = git diff --cached --name-only
if (-not $changes) { Write-Host "No oracle changes to commit."; exit 0 }
git commit -m "Record compact Minecraft and Mekanism recon oracle"
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
if (-not $NoPush) { git push -u origin HEAD; if ($LASTEXITCODE -ne 0) { throw "git push failed" } }
Write-Host "Compact oracle committed. Raw D:\YAN_RECON remains local."
