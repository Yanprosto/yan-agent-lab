param(
    [string]$Repo = "D:\YAN_AGENT_LAB",
    [string]$ModsDir = "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods"
)

$ErrorActionPreference = "Stop"

$modDir = Join-Path $Repo "mod"
if (-not (Test-Path -LiteralPath $modDir)) {
    throw "mod directory not found: $modDir"
}
if (-not (Test-Path -LiteralPath $ModsDir)) {
    throw "mods directory not found: $ModsDir"
}

Write-Host "======================================================================"
Write-Host "YAN RUNTIME REGISTRY BRIDGE BUILD"
Write-Host "======================================================================"
Write-Host "Repo:    $Repo"
Write-Host "ModsDir: $ModsDir"
Write-Host ""

Push-Location $modDir
try {
    & .\gradlew.bat clean build
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$libs = Join-Path $modDir "build\libs"
$jars = Get-ChildItem -LiteralPath $libs -File -Filter "*.jar" |
    Where-Object {
        $_.Name -notmatch 'sources|javadoc|dev-shadow'
    } |
    Sort-Object Length -Descending

if (-not $jars) {
    throw "No built jar found under $libs"
}

# The shaded/jarJar artifact is normally the largest deployable jar.
$artifact = $jars | Select-Object -First 1
Write-Host ""
Write-Host "Built artifact: $($artifact.FullName) ($($artifact.Length) bytes)"

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $ModsDir "_yan_mcbuild_backup_$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$old = Get-ChildItem -LiteralPath $ModsDir -File |
    Where-Object { $_.Name -match '^mcbuild[_-]live.*\.jar$' }

foreach ($file in $old) {
    Move-Item -LiteralPath $file.FullName -Destination (Join-Path $backupDir $file.Name) -Force
    Write-Host "BACKUP old bridge: $($file.Name)"
}

$target = Join-Path $ModsDir $artifact.Name
Copy-Item -LiteralPath $artifact.FullName -Destination $target -Force

Write-Host ""
Write-Host "======================================================================"
Write-Host "INSTALLED"
Write-Host "======================================================================"
Write-Host $target
Write-Host ""
Write-Host "Next:"
Write-Host "  1. Launch the test instance."
Write-Host "  2. Open/create a world."
Write-Host "  3. Run: /yanregistrydump"
Write-Host ""
Write-Host "The dump will be written to the instance working directory under:"
Write-Host "  yan_recon\runtime_registry_<UTC timestamp>.json"
