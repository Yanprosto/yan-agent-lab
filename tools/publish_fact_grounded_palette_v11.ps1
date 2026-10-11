param(
    [string]$Repo = "D:\YAN_AGENT_LAB",
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
Set-Location $Repo

uv run python tools\compile_fact_grounded_palette.py --repo "$Repo"
if ($LASTEXITCODE -ne 0) { throw "Palette compiler failed" }
uv run python tools\qa_fact_grounded_palette.py
if ($LASTEXITCODE -ne 0) { throw "Palette role QA failed" }

$paths = @(
  "docs/recon/generated/fact_grounded_palette.json",
  "docs/recon/generated/fact_grounded_palette.md"
)
git add -- $paths
$changes = git diff --cached --name-only
if (-not $changes) { Write-Host "No palette changes to commit."; exit 0 }
git commit -m "Refine fact-grounded palette roles"
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
if (-not $NoPush) {
  git push -u origin HEAD
  if ($LASTEXITCODE -ne 0) { throw "git push failed" }
}
Write-Host "Palette v1.1 committed."
