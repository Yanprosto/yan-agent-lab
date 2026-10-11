param(
    [string]$ModsDir = "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods",
    [string]$Version = "10.7.19.85"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projects = @(
    @{ Slug = "mekanism";            Prefix = "Mekanism-" },
    @{ Slug = "mekanism-generators"; Prefix = "MekanismGenerators-" },
    @{ Slug = "mekanism-tools";      Prefix = "MekanismTools-" },
    @{ Slug = "mekanism-additions";  Prefix = "MekanismAdditions-" }
)

if (-not (Test-Path -LiteralPath $ModsDir)) {
    throw "ModsDir not found: $ModsDir"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $ModsDir "_yan_mekanism_backup_$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

Write-Host "ModsDir: $ModsDir"
Write-Host "Target Mekanism version: $Version"
Write-Host "Backup: $backupDir"
Write-Host ""

# Backup every currently installed official Mekanism module before touching anything.
$existing = Get-ChildItem -LiteralPath $ModsDir -File |
    Where-Object {
        $_.Name -match '^Mekanism(?:Generators|Tools|Additions)?-.*\.jar$'
    }

foreach ($file in $existing) {
    Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $backupDir $file.Name) -Force
    Write-Host "BACKUP  $($file.Name)"
}

function Get-ModrinthVersion {
    param([string]$Slug, [string]$Version)

    $encodedGame = [uri]::EscapeDataString('["1.21.1"]')
    $encodedLoader = [uri]::EscapeDataString('["neoforge"]')
    $url = "https://api.modrinth.com/v2/project/$Slug/version?game_versions=$encodedGame&loaders=$encodedLoader"

    $versions = Invoke-RestMethod -Uri $url -Headers @{
        "User-Agent" = "YAN-Agent-Lab/1.0"
    }

    $match = $versions | Where-Object { $_.version_number -eq $Version } | Select-Object -First 1
    if (-not $match) {
        throw "Exact version $Version not found for $Slug"
    }
    return $match
}

function Get-PrimaryJar {
    param($VersionObject)

    $primary = $VersionObject.files | Where-Object {
        $_.primary -eq $true -and $_.filename -like "*.jar"
    } | Select-Object -First 1

    if (-not $primary) {
        $primary = $VersionObject.files | Where-Object {
            $_.filename -like "*.jar" -and $_.filename -notlike "*-api.jar"
        } | Select-Object -First 1
    }

    if (-not $primary) {
        throw "No usable jar found in Modrinth version response"
    }
    return $primary
}

$downloads = @()

foreach ($project in $projects) {
    Write-Host ""
    Write-Host "RESOLVE $($project.Slug) $Version"

    $versionObject = Get-ModrinthVersion -Slug $project.Slug -Version $Version
    $file = Get-PrimaryJar -VersionObject $versionObject

    $target = Join-Path $ModsDir $file.filename
    $temp = "$target.download"

    Invoke-WebRequest -Uri $file.url -OutFile $temp -Headers @{
        "User-Agent" = "YAN-Agent-Lab/1.0"
    }

    if ($file.hashes.sha512) {
        $actual = (Get-FileHash -LiteralPath $temp -Algorithm SHA512).Hash.ToLowerInvariant()
        $expected = ([string]$file.hashes.sha512).ToLowerInvariant()
        if ($actual -ne $expected) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
            throw "SHA512 mismatch for $($file.filename)"
        }
    }

    # Remove only old jars belonging to this exact official module.
    $prefix = $project.Prefix
    Get-ChildItem -LiteralPath $ModsDir -File |
        Where-Object {
            $_.Name.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) -and
            $_.Name -like "*.jar" -and
            $_.FullName -ne $temp
        } |
        ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Host "REMOVE  $($_.Name)"
        }

    Move-Item -LiteralPath $temp -Destination $target -Force
    Write-Host "INSTALL $($file.filename)"

    $downloads += [pscustomobject]@{
        Project = $project.Slug
        Version = $versionObject.version_number
        File    = $file.filename
        SHA512  = (Get-FileHash -LiteralPath $target -Algorithm SHA512).Hash
    }
}

Write-Host ""
Write-Host "======================================================================"
Write-Host "MEKANISM LAB READY"
Write-Host "======================================================================"
$downloads | Format-Table -AutoSize

Write-Host ""
Write-Host "Installed official Mekanism modules:"
Get-ChildItem -LiteralPath $ModsDir -File |
    Where-Object {
        $_.Name -match '^Mekanism(?:Generators|Tools|Additions)?-.*\.jar$'
    } |
    Sort-Object Name |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Next: launch the test instance once and make sure it reaches the main menu/world."
