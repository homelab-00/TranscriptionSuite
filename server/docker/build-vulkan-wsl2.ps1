# Build the Vulkan-WSL2 sidecar image locally (GH-101 follow-up) — Windows
# PowerShell companion to build-vulkan-wsl2.sh, for users running Docker
# Desktop on Windows without Git Bash / WSL on the PATH.
#
# Tags: transcriptionsuite/whisper-cpp-vulkan-wsl2:latest
#
# Usage (from any PowerShell):
#   .\server\docker\build-vulkan-wsl2.ps1
#
# Pass -NoCache to force a clean rebuild (useful when the kisak PPA shape
# changes). All other arguments are forwarded to `docker buildx build`.

[CmdletBinding()]
param(
    [switch]$NoCache,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $PSCommandPath
$Dockerfile = Join-Path $ScriptDir 'whisper-cpp-vulkan-wsl2.Dockerfile'
$ImageTag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { 'transcriptionsuite/whisper-cpp-vulkan-wsl2:latest' }

if (-not (Test-Path -LiteralPath $Dockerfile)) {
    Write-Error "Dockerfile not found at $Dockerfile"
    exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error 'docker CLI not found in PATH. Install Docker Desktop, then retry.'
    exit 1
}

try {
    docker buildx version | Out-Null
} catch {
    Write-Error 'docker buildx is not available. Update Docker to a recent version (>= 20.10) and retry.'
    exit 1
}

Write-Host "[build-vulkan-wsl2] Building $ImageTag from $Dockerfile..."

$BuildArgs = @('buildx', 'build', '--load', '--tag', $ImageTag, '-f', $Dockerfile, $ScriptDir)
if ($NoCache) {
    $BuildArgs += '--no-cache'
}
if ($ExtraArgs) {
    $BuildArgs += $ExtraArgs
}

& docker @BuildArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker buildx build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "[build-vulkan-wsl2] Done. Verify with: docker images | findstr whisper-cpp-vulkan-wsl2"
Write-Host "[build-vulkan-wsl2] To use: open the dashboard, switch to 'GPU (Vulkan WSL2 - experimental)', and Start Server."
