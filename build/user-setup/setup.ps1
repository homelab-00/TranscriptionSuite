#Requires -Version 5.1
# TranscriptionSuite - First-Time Setup Script (Windows)
# Run this once to set up your environment before starting the server.
# After setup, all scripts and configs will be in Documents\TranscriptionSuite

$ErrorActionPreference = "Stop"

# ============================================================================
# Constants
# ============================================================================
$DockerImage = "bvcsfd/transcription-suite"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$GitHubRawUrl = "https://raw.githubusercontent.com/homelab-00/TranscriptionSuite/main"

# Config directory (matching client behavior for Windows)
$ConfigDir = Join-Path $env:USERPROFILE "Documents\TranscriptionSuite"

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

function Write-Warning($message) {
    Write-Host "Warning: " -ForegroundColor Yellow -NoNewline
    Write-Host $message
}

function Write-Info($message) {
    Write-Host "Info: " -ForegroundColor Cyan -NoNewline
    Write-Host $message
}

# ============================================================================
# Pre-flight Checks
# ============================================================================
Write-Status "Running pre-flight checks..."

# Check if Docker is installed
try {
    $null = Get-Command docker -ErrorAction Stop
} catch {
    Write-ErrorMsg "Docker is not installed."
    Write-Host ""
    Write-Host "Please install Docker Desktop from:"
    Write-Host "  https://docs.docker.com/desktop/install/windows-install/"
    exit 1
}

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

Write-Info "Docker is installed and running"

# ============================================================================
# Create Config Directory
# ============================================================================
Write-Status "Creating config directory: $ConfigDir"
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null

# ============================================================================
# Copy Config File
# ============================================================================
$SourceConfig = Join-Path $ProjectRoot "native_src\config.yaml"
$DestConfig = Join-Path $ConfigDir "config.yaml"

if (Test-Path $DestConfig) {
    Write-Warning "Config already exists at $DestConfig"
    $overwrite = Read-Host "Overwrite with default config? (y/N)"
    if ($overwrite -ne "y" -and $overwrite -ne "Y") {
        Write-Info "Keeping existing config"
    } else {
        if (Test-Path $SourceConfig) {
            Write-Status "Copying config from repository..."
            Copy-Item $SourceConfig $DestConfig -Force
        } else {
            Write-Status "Downloading config from GitHub..."
            Invoke-WebRequest -Uri "https://raw.githubusercontent.com/homelab-00/TranscriptionSuite/main/native_src/config.yaml" `
                -OutFile $DestConfig
        }
        Write-Info "Config file updated"
    }
} else {
    if (Test-Path $SourceConfig) {
        Write-Status "Copying config from repository..."
        Copy-Item $SourceConfig $DestConfig -Force
    } else {
        Write-Status "Downloading config from GitHub..."
        Invoke-WebRequest -Uri "https://raw.githubusercontent.com/homelab-00/TranscriptionSuite/main/native_src/config.yaml" `
            -OutFile $DestConfig
    }
    Write-Info "Config file created"
}

# ============================================================================
# Create .env File for Secrets
# ============================================================================
$EnvExample = Join-Path $ScriptDir ".env.example"
$EnvFile = Join-Path $ConfigDir ".env"

if (Test-Path $EnvFile) {
    Write-Info ".env file already exists (keeping existing secrets)"
} else {
    if (Test-Path $EnvExample) {
        Write-Status "Creating .env file for secrets..."
        Copy-Item $EnvExample $EnvFile
        Write-Info ".env file created at $EnvFile"
    } else {
        Write-Warning ".env.example not found - skipping .env creation"
    }
}

# ============================================================================
# Copy Docker Compose and Scripts to Config Directory
# ============================================================================
Write-Status "Setting up Docker files in config directory..."

# Copy docker-compose.yml
$DockerDir = Join-Path $ProjectRoot "docker"
$SourceCompose = Join-Path $DockerDir "docker-compose.yml"
$DestCompose = Join-Path $ConfigDir "docker-compose.yml"
if (Test-Path $SourceCompose) {
    Copy-Item $SourceCompose $DestCompose -Force
} else {
    Write-Status "Downloading docker-compose.yml from GitHub..."
    Invoke-WebRequest -Uri "$GitHubRawUrl/docker/docker-compose.yml" -OutFile $DestCompose
}

# Copy start/stop scripts
$Scripts = @("start-local.ps1", "start-remote.ps1", "stop.ps1")
foreach ($script in $Scripts) {
    $SourceScript = Join-Path $DockerDir $script
    $DestScript = Join-Path $ConfigDir $script
    if (Test-Path $SourceScript) {
        Copy-Item $SourceScript $DestScript -Force
    } else {
        Write-Status "Downloading $script from GitHub..."
        Invoke-WebRequest -Uri "$GitHubRawUrl/docker/$script" -OutFile $DestScript
    }
}

Write-Info "Docker files copied to $ConfigDir"

# ============================================================================
# Pull Docker Image
# ============================================================================
Write-Status "Pulling Docker image: ${DockerImage}:latest"
Write-Host "This may take a few minutes on first run..."
Write-Host ""

try {
    docker pull "${DockerImage}:latest"
    Write-Info "Docker image pulled successfully"
} catch {
    Write-Warning "Could not pull from Docker Hub (image may not be published yet)"
    Write-Info "You can build locally instead: cd docker; docker compose build"
}

# ============================================================================
# Success Message
# ============================================================================
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TranscriptionSuite Setup Complete!" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "All files are in: $ConfigDir"
Write-Host ""
Write-Host "  config.yaml        - Server settings"
Write-Host "  .env               - Secrets (HuggingFace token)"
Write-Host "  docker-compose.yml"
Write-Host "  start-local.ps1    - Start in HTTP mode"
Write-Host "  start-remote.ps1   - Start in HTTPS mode"
Write-Host "  stop.ps1           - Stop the server"
Write-Host ""
Write-Host "Next steps:"
Write-Host ""
Write-Host "  1. Edit the .env file to add your HuggingFace token:"
Write-Host "     notepad `"$EnvFile`""
Write-Host ""
Write-Host "  2. (Optional) For remote/TLS access, edit config.yaml:"
Write-Host "     notepad `"$DestConfig`""
Write-Host ""
Write-Host "     Set your Tailscale certificate paths:"
Write-Host "       host_cert_path: `"~/Documents/Tailscale/my-machine.crt`""
Write-Host "       host_key_path: `"~/Documents/Tailscale/my-machine.key`""
Write-Host ""
Write-Host "  3. Start the server:"
Write-Host "     cd `"$ConfigDir`""
Write-Host "     .\start-local.ps1    # HTTP on port 8000"
Write-Host "     .\start-remote.ps1   # HTTPS on port 8443"
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
