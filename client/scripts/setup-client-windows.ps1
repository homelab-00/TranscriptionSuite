# Setup script for TranscriptionSuite native client on Windows 11
# Run this script in PowerShell as Administrator

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ClientDir = Join-Path $ProjectRoot "client"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "TranscriptionSuite Native Client Setup (Windows)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# Check for Python
try {
    $PythonVersion = & python --version 2>&1
    if ($PythonVersion -match "Python (\d+)\.(\d+)") {
        $Major = [int]$Matches[1]
        $Minor = [int]$Matches[2]
        if ($Major -lt 3 -or ($Major -eq 3 -and $Minor -lt 11)) {
            Write-Host "Error: Python 3.11+ required, found $PythonVersion" -ForegroundColor Red
            exit 1
        }
        Write-Host "✓ $PythonVersion found" -ForegroundColor Green
    }
} catch {
    Write-Host "Error: Python not found. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# Create virtual environment
$VenvDir = Join-Path $ClientDir ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "→ Creating virtual environment..."
    & python -m venv $VenvDir
}

Write-Host "✓ Virtual environment at $VenvDir" -ForegroundColor Green

# Activate and install dependencies
$PipPath = Join-Path $VenvDir "Scripts\pip.exe"
$PythonPath = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "→ Installing dependencies..."

& $PipPath install --upgrade pip
& $PipPath install -e $ClientDir
& $PipPath install PyQt6 pyaudio aiohttp pyyaml numpy pyperclip

Write-Host "✓ Dependencies installed" -ForegroundColor Green

# Create config directory
$ConfigDir = Join-Path $env:APPDATA "TranscriptionSuite"
if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir | Out-Null
    Write-Host "✓ Created config directory: $ConfigDir" -ForegroundColor Green
}

# Copy example config
$ConfigFile = Join-Path $ConfigDir "client.yaml"
$ExampleConfig = Join-Path $ProjectRoot "config\client.yaml.example"
if (-not (Test-Path $ConfigFile) -and (Test-Path $ExampleConfig)) {
    Copy-Item $ExampleConfig $ConfigFile
    Write-Host "✓ Created default config: $ConfigFile" -ForegroundColor Green
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To run the client:"
Write-Host "  & '$PythonPath' -m client"
Write-Host ""
Write-Host "Or create a shortcut to:"
Write-Host "  $PythonPath -m client"
Write-Host "==================================================" -ForegroundColor Cyan
