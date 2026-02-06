#Requires -Version 5.1
# TranscriptionSuite - Start Server in Remote Mode (HTTPS/TLS)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CommonScript = Join-Path $ScriptDir "start-common.ps1"

if (-not (Test-Path $CommonScript)) {
    Write-Host "Error: start-common.ps1 not found in $ScriptDir" -ForegroundColor Red
    exit 1
}

& $CommonScript -Mode remote @args
exit $LASTEXITCODE
