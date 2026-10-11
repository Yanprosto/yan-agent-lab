param(
    [string]$Repo = "D:\YAN_AGENT_LAB",
    [string]$Instance = "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft",
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
Set-Location $Repo

uv run python tools\build_semantic_catalog.py --repo "$Repo" --instance "$Instance"
if ($LASTEXITCODE -ne 0) { throw "Semantic catalog build failed" }

$paths = @(
  "docs/recon/generated/semantic_block_catalog.json",
  "docs/recon/generated/semantic_block_catalog.md"
)
git add -- $paths
$changes = git diff --cached --name-only
if (-not $changes) { Write-Host "No semantic catalog changes to commit."; exit 0 }

git commit -m "Record unified vanilla and Mekanism semantic block catalog"
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

if (-not $NoPush) {
  git push -u origin HEAD
  if ($LASTEXITCODE -ne 0) { throw "git push failed" }
}

Write-Host "Semantic catalog committed. Raw runtime registry remains local."
