param(
    [string]$Instance = "C:\\Users\\yan\\AppData\\Roaming\\ElyPrismLauncher\\instances\\1.21.1(1)\\minecraft",
    [string]$LauncherRoot = "C:\\Users\\yan\\AppData\\Roaming\\ElyPrismLauncher",
    [string]$Out = "D:\\YAN_RECON"
)

$ErrorActionPreference = "Stop"
Set-Location "D:\\YAN_AGENT_LAB"

Write-Host "======================================================================"
Write-Host "YAN MINECRAFT LAB RECON"
Write-Host "======================================================================"
Write-Host "Instance: $Instance"
Write-Host "Output:   $Out"
Write-Host ""

uv run python tools\\recon_minecraft_lab.py --instance "$Instance" --launcher-root "$LauncherRoot" --out "$Out"

if ($LASTEXITCODE -ne 0) {
    throw "Recon failed with exit code $LASTEXITCODE"
}
