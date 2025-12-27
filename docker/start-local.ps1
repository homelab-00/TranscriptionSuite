#Requires -Version 5.1
# TranscriptionSuite - Start Server in Local Mode (HTTP)
# Starts the server on http://localhost:8000
# This script can run from the docker/ folder OR from Documents\TranscriptionSuite

$ErrorActionPreference = "Stop"

# ============================================================================
# Constants
# ============================================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ============================================================================
# Helper Functions
# ============================================================================
function Write-Status($message) {
    Write-Host "==> " -ForegroundColor Green -NoNewline
    Write-Host $message
}

function Write-ErrorMsg($message) {
    Write-Host "Error: " -ForegroundColor Red -NoNewline
    Write-Host $message
}

function Write-Info($message) {
    Write-Host "Info: " -ForegroundColor Cyan -NoNewline
    Write-Host $message
}

# ============================================================================
# Pre-flight Checks
# ============================================================================

# Check if Docker daemon is running
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Docker not running"
    }
} catch {
    Write-ErrorMsg "Docker daemon is not running."
    Write-Host ""
    Write-Host "Please start Docker Desktop."
    exit 1
}

# Check docker-compose.yml exists in script directory
$ComposeFile = Join-Path $ScriptDir "docker-compose.yml"
if (-not (Test-Path $ComposeFile)) {
    Write-ErrorMsg "docker-compose.yml not found in $ScriptDir"
    Write-Host ""
    Write-Host "Run setup.ps1 first to set up TranscriptionSuite."
    exit 1
}

# ============================================================================
# Find Config and .env Files
# ============================================================================
# This script works in two scenarios:
#   1. Development: Run from docker/ directory (finds config at ../native_src/)
#   2. End user: Run from Documents\TranscriptionSuite\ (finds config in same dir)
#
# Priority order for config.yaml:
#   1. ../native_src/config.yaml (development - when running from docker/ dir)
#   2. $ScriptDir/config.yaml (end user - when running from Documents\TranscriptionSuite\)
#   3. Documents\TranscriptionSuite\config.yaml (fallback)
#
# Priority order for .env:
#   1. ../native_src/.env (development - alongside dev config)
#   2. $ScriptDir/.env (end user running from Documents\TranscriptionSuite\)
#   3. Documents\TranscriptionSuite\.env (fallback)

# Find config.yaml
$ConfigFile = ""
$UserConfigDir = ""

# Check 1: Development location (../native_src/config.yaml relative to script dir)
$DevConfig = Join-Path (Split-Path $ScriptDir -Parent) "native_src\config.yaml"
if (Test-Path $DevConfig) {
    $ConfigFile = $DevConfig
    $UserConfigDir = Join-Path (Split-Path $ScriptDir -Parent) "native_src"
    Write-Info "Using development config: $ConfigFile"
}
# Check 2: Script directory (end user running from Documents\TranscriptionSuite\)
elseif (Test-Path (Join-Path $ScriptDir "config.yaml")) {
    $ConfigFile = Join-Path $ScriptDir "config.yaml"
    $UserConfigDir = $ScriptDir
    Write-Info "Using config: $ConfigFile"
}
# Check 3: Standard user config location (fallback)
elseif (Test-Path "$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml") {
    $ConfigFile = "$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml"
    $UserConfigDir = "$env:USERPROFILE\Documents\TranscriptionSuite"
    Write-Info "Using user config: $ConfigFile"
}
else {
    Write-Info "No config.yaml found (using container defaults)"
    $UserConfigDir = ""
}

# Export USER_CONFIG_DIR for docker-compose
$env:USER_CONFIG_DIR = $UserConfigDir

# Find .env file (harmonized with config.yaml search order)
$EnvFile = ""
$EnvFileArg = @()

# Check 1: Development location (../native_src/.env - alongside dev config)
$DevEnv = Join-Path (Split-Path $ScriptDir -Parent) "native_src\.env"
if (Test-Path $DevEnv) {
    $EnvFile = $DevEnv
    Write-Info "Using secrets from: $EnvFile"
    $EnvFileArg = @("--env-file", $EnvFile)
}
# Check 2: Script directory (end user running from Documents\TranscriptionSuite\)
elseif (Test-Path (Join-Path $ScriptDir ".env")) {
    $EnvFile = Join-Path $ScriptDir ".env"
    Write-Info "Using secrets from: $EnvFile"
    $EnvFileArg = @("--env-file", $EnvFile)
}
# Check 3: Standard user config location (fallback)
elseif (Test-Path "$env:USERPROFILE\Documents\TranscriptionSuite\.env") {
    $EnvFile = "$env:USERPROFILE\Documents\TranscriptionSuite\.env"
    Write-Info "Using secrets from: $EnvFile"
    $EnvFileArg = @("--env-file", $EnvFile)
}
else {
    Write-Info "No .env file found (diarization may not work without HF token)"
}

# ============================================================================
# Start Container
# ============================================================================
Write-Status "Starting TranscriptionSuite server (local mode)..."

Set-Location $ScriptDir

# TLS_ENABLED defaults to false in docker-compose.yml
docker compose @EnvFileArg up -d

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TranscriptionSuite Server Started (Local Mode)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Server URL:  http://localhost:8000"
Write-Host "  Web UI:      http://localhost:8000/record"
Write-Host "  Notebook:    http://localhost:8000/notebook"
Write-Host ""
Write-Host "  View logs:   docker compose logs -f"
Write-Host "  Stop:        .\stop.ps1"
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
