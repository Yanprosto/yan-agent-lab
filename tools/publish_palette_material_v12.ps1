param(
    [string]$Repo = "D:\YAN_AGENT_LAB",
    [string]$Instance = "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft",
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
Set-Location $Repo

Write-Host "======================================================================"
Write-Host "YAN PALETTE MATERIAL V1.2"
Write-Host "======================================================================"
Write-Host "Rebuilding semantic catalog from newest runtime registry..."

uv run python tools\build_semantic_catalog.py --repo "$Repo" --instance "$Instance"
if ($LASTEXITCODE -ne 0) { throw "Semantic catalog build failed" }

Write-Host ""
Write-Host "Recompiling fact-grounded palette..."
uv run python tools\compile_fact_grounded_palette.py --repo "$Repo"
if ($LASTEXITCODE -ne 0) { throw "Palette compiler failed" }

Write-Host ""
Write-Host "Running role QA..."
uv run python tools\qa_fact_grounded_palette.py
if ($LASTEXITCODE -ne 0) { throw "Palette role QA failed" }

$paths = @(
  "docs/recon/generated/semantic_block_catalog.json",
  "docs/recon/generated/semantic_block_catalog.md",
  "docs/recon/generated/fact_grounded_palette.json",
  "docs/recon/generated/fact_grounded_palette.md"
)

git add -- $paths
$changes = git diff --cached --name-only
if (-not $changes) { Write-Host "No generated changes to commit."; exit 0 }

git commit -m "Refine palette with runtime material classes"
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

if (-not $NoPush) {
  git push -u origin HEAD
  if ($LASTEXITCODE -ne 0) { throw "git push failed" }
}

Write-Host "Palette v1.2 committed."
