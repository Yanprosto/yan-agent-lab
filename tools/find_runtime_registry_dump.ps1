param(
    [string]$Instance = "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft"
)

$ErrorActionPreference = "Stop"

$candidates = @(
    (Join-Path $Instance "yan_recon"),
    (Join-Path (Split-Path $Instance -Parent) "yan_recon"),
    (Join-Path "D:\YAN_AGENT_LAB\mod" "yan_recon")
) | Where-Object { Test-Path -LiteralPath $_ }

$files = @()
foreach ($dir in $candidates) {
    $files += Get-ChildItem -LiteralPath $dir -File -Filter "runtime_registry_*.json"
}

$latest = $files | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) {
    throw "No runtime_registry_*.json found. Run /yanregistrydump in the test world first."
}

Write-Host "Latest runtime dump:"
Write-Host $latest.FullName
Write-Host ""
Write-Host "Size: $($latest.Length) bytes"
Write-Host "Modified: $($latest.LastWriteTime)"
