#Requires -Version 5.1
# TranscriptionSuite - Start Server in Remote Mode (HTTPS/TLS)
# Starts the server on https://localhost:8443
# Requires TLS certificates configured in config.yaml
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
$ConfigDirToMount = ""

# Check 1: Development location (../native_src/config.yaml relative to script dir)
$DevConfig = Join-Path (Split-Path $ScriptDir -Parent) "native_src\config.yaml"
if (Test-Path $DevConfig) {
    $ConfigFile = $DevConfig
    $ConfigDirToMount = Join-Path (Split-Path $ScriptDir -Parent) "native_src"
    Write-Info "Using development config: $ConfigFile"
}
# Check 2: Script directory (end user running from Documents\TranscriptionSuite\)
elseif (Test-Path (Join-Path $ScriptDir "config.yaml")) {
    $ConfigFile = Join-Path $ScriptDir "config.yaml"
    $ConfigDirToMount = $ScriptDir
    Write-Info "Using config: $ConfigFile"
}
# Check 3: Standard user config location (fallback)
elseif (Test-Path "$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml") {
    $ConfigFile = "$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml"
    $ConfigDirToMount = "$env:USERPROFILE\Documents\TranscriptionSuite"
    Write-Info "Using user config: $ConfigFile"
}
else {
    Write-ErrorMsg "No config.yaml found"
    Write-Host ""
    Write-Host "Checked locations:"
    Write-Host "  1. $DevConfig (development)"
    Write-Host "  2. $(Join-Path $ScriptDir 'config.yaml') (script directory)"
    Write-Host "  3. $env:USERPROFILE\Documents\TranscriptionSuite\config.yaml (user config)"
    Write-Host ""
    Write-Host "For end users: Run setup.ps1 first to create the config file."
    Write-Host "For development: config.yaml should be in native_src\ directory."
    exit 1
}

# Find .env file (harmonized with config.yaml search order - optional for remote mode)
$EnvFile = ""

# Check 1: Development location (../native_src/.env - alongside dev config)
$DevEnv = Join-Path (Split-Path $ScriptDir -Parent) "native_src\.env"
if (Test-Path $DevEnv) {
    $EnvFile = $DevEnv
}
# Check 2: Script directory (end user running from Documents\TranscriptionSuite\)
elseif (Test-Path (Join-Path $ScriptDir ".env")) {
    $EnvFile = Join-Path $ScriptDir ".env"
}
# Check 3: Standard user config location (fallback)
elseif (Test-Path "$env:USERPROFILE\Documents\TranscriptionSuite\.env") {
    $EnvFile = "$env:USERPROFILE\Documents\TranscriptionSuite\.env"
}

# ============================================================================
# Parse TLS Paths from Config
# ============================================================================
# Read config file and parse host_cert_path and host_key_path
$configContent = Get-Content $ConfigFile -Raw

# Extract paths using regex
$certMatch = [regex]::Match($configContent, 'host_cert_path:\s*[''"]?([^''"#\r\n]+)[''"]?')
$keyMatch = [regex]::Match($configContent, 'host_key_path:\s*[''"]?([^''"#\r\n]+)[''"]?')

$HostCertPath = if ($certMatch.Success) { $certMatch.Groups[1].Value.Trim() } else { "" }
$HostKeyPath = if ($keyMatch.Success) { $keyMatch.Groups[1].Value.Trim() } else { "" }

# Expand ~ to user profile
$HostCertPath = $HostCertPath -replace '^~[/\\]?', "$env:USERPROFILE\"
$HostKeyPath = $HostKeyPath -replace '^~[/\\]?', "$env:USERPROFILE\"

# Normalize path separators
$HostCertPath = $HostCertPath -replace '/', '\'
$HostKeyPath = $HostKeyPath -replace '/', '\'

# ============================================================================
# Validate TLS Configuration
# ============================================================================
if ([string]::IsNullOrWhiteSpace($HostCertPath)) {
    Write-ErrorMsg "remote_server.tls.host_cert_path is not set in config.yaml"
    Write-Host ""
    Write-Host "Please edit $ConfigFile and set the TLS certificate paths:"
    Write-Host ""
    Write-Host "  remote_server:"
    Write-Host "    tls:"
    Write-Host "      host_cert_path: `"~/Documents/Tailscale/my-machine.crt`""
    Write-Host "      host_key_path: `"~/Documents/Tailscale/my-machine.key`""
    Write-Host ""
    Write-Host "See README_DEV.md for Tailscale certificate generation instructions."
    exit 1
}

if ([string]::IsNullOrWhiteSpace($HostKeyPath)) {
    Write-ErrorMsg "remote_server.tls.host_key_path is not set in config.yaml"
    Write-Host ""
    Write-Host "Please edit $ConfigFile and set the TLS key path."
    exit 1
}

if (-not (Test-Path $HostCertPath)) {
    Write-ErrorMsg "Certificate file not found: $HostCertPath"
    Write-Host ""
    Write-Host "Please ensure the certificate file exists."
    Write-Host "For Tailscale, generate certificates with:"
    Write-Host "  tailscale cert <your-machine>.tail<xxxx>.ts.net"
    exit 1
}

if (-not (Test-Path $HostKeyPath)) {
    Write-ErrorMsg "Key file not found: $HostKeyPath"
    Write-Host ""
    Write-Host "Please ensure the key file exists."
    exit 1
}

Write-Info "Certificate: $HostCertPath"
Write-Info "Key: $HostKeyPath"

# Log .env file status
$EnvFileArg = @()
if ($EnvFile -ne "" -and (Test-Path $EnvFile)) {
    Write-Info "Using secrets from: $EnvFile"
    $EnvFileArg = @("--env-file", $EnvFile)
} else {
    Write-Info "No .env file found (diarization may not work without HF token)"
}

# ============================================================================
# Start Container with TLS
# ============================================================================
Write-Status "Starting TranscriptionSuite server (remote/TLS mode)..."

Set-Location $ScriptDir

# Set environment variables for docker-compose
$env:TLS_ENABLED = "true"
$env:TLS_CERT_PATH = $HostCertPath
$env:TLS_KEY_PATH = $HostKeyPath
$env:USER_CONFIG_DIR = $ConfigDirToMount

docker compose @EnvFileArg up -d

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TranscriptionSuite Server Started (Remote/TLS Mode)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  HTTPS URL:   https://localhost:8443"
Write-Host "  Web UI:      https://localhost:8443/record"
Write-Host "  Notebook:    https://localhost:8443/notebook"
Write-Host ""
Write-Host "  Certificate: $HostCertPath"
Write-Host ""
Write-Host "  Note: On first run, an admin token will be printed in the logs."
Write-Host "        Save this token for authentication."
Write-Host ""
Write-Host "  View logs:   docker compose logs -f"
Write-Host "  Stop:        .\stop.ps1"
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
