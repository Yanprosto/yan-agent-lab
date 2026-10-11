param(
    [string]$Repo = "D:\YAN_AGENT_LAB",
    [string]$LauncherRoot = "C:\Users\yan\AppData\Roaming\ElyPrismLauncher",
    [string]$ModsDir = "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods",
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
Set-Location $Repo

uv run python tools\build_visual_catalog.py --repo "$Repo" --launcher-root "$LauncherRoot" --mods-dir "$ModsDir"
if ($LASTEXITCODE -ne 0) { throw "Visual catalog build failed" }

$paths = @(
  "docs/recon/generated/visual_block_catalog.json",
  "docs/recon/generated/visual_block_catalog.md"
)
git add -- $paths
$changes = git diff --cached --name-only
if (-not $changes) { Write-Host "No visual catalog changes to commit."; exit 0 }

git commit -m "Record vanilla and Mekanism visual block catalog"
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

if (-not $NoPush) {
  git push -u origin HEAD
  if ($LASTEXITCODE -ne 0) { throw "git push failed" }
}

Write-Host "Visual catalog committed."
