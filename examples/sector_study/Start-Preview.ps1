$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\..')
Write-Host 'YAN: sector preview. Stop mcbuild-server-dev in its console (Ctrl+C) first.'
Write-Host 'No mod rebuild. Open a creative test world, then /tp @s ~ 180 ~'
Write-Host 'In Minecraft: /build yan-sector-preview'
uv run python examples/sector_study/live_preview.py
if ($LASTEXITCODE -ne 0) { throw 'Preview server stopped with an error. Check the output above.' }
