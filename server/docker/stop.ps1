#Requires -Version 5.1
# TranscriptionSuite - Stop Server
# Stops the Docker container

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $ScriptDir
docker compose stop

Write-Host ""
Write-Host "TranscriptionSuite server stopped." -ForegroundColor Green
Write-Host ""
Write-Host "To restart:"
Write-Host "  .\start-local.ps1    # HTTP mode"
Write-Host "  .\start-remote.ps1   # HTTPS mode"
