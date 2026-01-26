#Requires -Version 5.1
# TranscriptionSuite - Start Server in Local Mode (HTTP)
# Starts the server on http://localhost:8000
# This script can run from the server/docker/ folder OR from Documents\TranscriptionSuite

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
#   1. Development: Run from server/docker/ directory (finds config at ../server/)
#   2. End user: Run from Documents\TranscriptionSuite\ (finds config in same dir)
#
# Priority order for config.yaml:
#   1. ../server/config.yaml (development - when running from server/docker/ dir)
#   2. $ScriptDir/config.yaml (end user - when running from Documents\TranscriptionSuite\)
#   3. Documents\TranscriptionSuite\config.yaml (fallback)
#
# Priority order for .env:
#   1. ../server/.env (development - alongside dev config)
#   2. $ScriptDir/.env (end user running from Documents\TranscriptionSuite\)
#   3. Documents\TranscriptionSuite\.env (fallback)

# Find config.yaml
$ConfigFile = ""
$UserConfigDir = ""

# Check 1: Development location (../config.yaml relative to script dir)
$DevConfig = Join-Path (Split-Path $ScriptDir -Parent) "config.yaml"
if (Test-Path $DevConfig) {
    $ConfigFile = $DevConfig
    $UserConfigDir = Split-Path $ScriptDir -Parent
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

# Check 1: Development location (../.env - alongside dev config)
$DevEnv = Join-Path (Split-Path $ScriptDir -Parent) ".env"
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
# Check for Existing Container and Mode Conflicts
# ============================================================================
$ContainerName = "transcriptionsuite-container"

$containerExists = docker ps -a --format "{{.Names}}" 2>$null | Where-Object { $_ -eq $ContainerName }
if ($containerExists) {
    Write-Info "Container already exists, checking mode..."

    # Get current TLS_ENABLED value from running/stopped container
    $envOutput = docker inspect $ContainerName --format "{{range .Config.Env}}{{println .}}{{end}}" 2>$null
    $currentTLS = "false"
    if ($envOutput) {
        $match = $envOutput | Select-String "^TLS_ENABLED=(.+)"
        if ($match) {
            $currentTLS = $match.Matches.Groups[1].Value
        }
    }

    # We're starting in local mode (TLS disabled)
    if ($currentTLS -eq "true") {
        Write-Info "Mode conflict: container is in remote/TLS mode, but starting in local mode"
        Write-Info "Removing existing container..."
        Set-Location $ScriptDir
        docker compose down 2>&1 | Where-Object { $_ -notmatch "No resource found to remove" } | Out-Host
    } else {
        Write-Info "Container is already in local mode"
    }
}

# Check if image exists
$imageExists = docker images --format "{{.Repository}}:{{.Tag}}" 2>$null | Where-Object { $_ -eq "ghcr.io/homelab-00/transcriptionsuite-server:latest" }
if ($imageExists) {
    Write-Host "Info: " -ForegroundColor Cyan -NoNewline
    Write-Host "Using existing image: ghcr.io/homelab-00/transcriptionsuite-server:latest"
} else {
    Write-Info "Image will be built on first run"
}

# ============================================================================
# Start Container
# ============================================================================
Write-Status "Starting TranscriptionSuite server (local mode)..."

Set-Location $ScriptDir

# TLS_ENABLED defaults to false in docker-compose.yml
docker compose @EnvFileArg up -d 2>&1 | Where-Object { $_ -notmatch "WARN\[0000\] No services to build" } | Out-Host

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TranscriptionSuite Server Started (Local Mode)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Server URL:  http://localhost:8000"
Write-Host "  Web UI:      http://localhost:8000/record"
Write-Host "  Notebook:    http://localhost:8000/notebook"
Write-Host ""
Write-Host "  Note: On first run, an admin token will be printed in the logs."
Write-Host "        Wait ~10 seconds, then run:"
Write-Host "        docker compose logs | Select-String `"Admin Token:`""
Write-Host ""
Write-Host "  View logs:   docker compose logs -f"
Write-Host "  Stop:        .\stop.ps1"
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
