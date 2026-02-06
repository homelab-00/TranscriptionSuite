#Requires -Version 5.1
# TranscriptionSuite - Start Server in Local Mode (HTTP)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CommonScript = Join-Path $ScriptDir "start-common.ps1"

if (-not (Test-Path $CommonScript)) {
    Write-Host "Error: start-common.ps1 not found in $ScriptDir" -ForegroundColor Red
    exit 1
}

& $CommonScript -Mode local @args
exit $LASTEXITCODE
