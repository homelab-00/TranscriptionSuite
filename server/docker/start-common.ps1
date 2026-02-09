#Requires -Version 5.1
# TranscriptionSuite - Shared startup logic for local/remote server modes.
# Usage: .\start-common.ps1 -Mode local|remote

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("local", "remote")]
    [string]$Mode
)

$ErrorActionPreference = "Stop"

# ============================================================================
# Constants
# ============================================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DockerImage = "ghcr.io/homelab-00/transcriptionsuite-server:latest"
$ContainerName = "transcriptionsuite-container"
$HfDiarizationTermsUrl = "https://huggingface.co/pyannote/speaker-diarization-community-1"
$script:PromptTimeOffsetSeconds = 0

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

function Add-PromptElapsedSeconds {
    param(
        [long]$StartedAtEpochSeconds
    )

    $endedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($StartedAtEpochSeconds -le 0 -or $endedAt -lt $StartedAtEpochSeconds) {
        return
    }

    $script:PromptTimeOffsetSeconds += ($endedAt - $StartedAtEpochSeconds)
}

function Convert-ToPositiveIntOrDefault {
    param(
        [string]$RawValue,
        [int]$DefaultValue
    )

    if ([string]::IsNullOrWhiteSpace($RawValue)) {
        return $DefaultValue
    }

    $parsed = 0
    if (-not [int]::TryParse($RawValue.Trim(), [ref]$parsed)) {
        return $DefaultValue
    }

    if ($parsed -le 0) {
        return $DefaultValue
    }

    return $parsed
}

function Resolve-BootstrapTimeoutSeconds {
    param(
        [string]$EnvFilePath
    )

    $raw = $env:BOOTSTRAP_TIMEOUT_SECONDS
    if ([string]::IsNullOrWhiteSpace($raw) -and -not [string]::IsNullOrWhiteSpace($EnvFilePath)) {
        $raw = Get-EnvValue -EnvFilePath $EnvFilePath -Key "BOOTSTRAP_TIMEOUT_SECONDS"
    }

    return Convert-ToPositiveIntOrDefault -RawValue $raw -DefaultValue 1800
}

function Set-BootstrapTimeoutForPromptDelay {
    param(
        [string]$EnvFilePath
    )

    $baseTimeout = Resolve-BootstrapTimeoutSeconds -EnvFilePath $EnvFilePath
    $effectiveTimeout = $baseTimeout + $script:PromptTimeOffsetSeconds
    $env:BOOTSTRAP_TIMEOUT_SECONDS = "$effectiveTimeout"

    if ($script:PromptTimeOffsetSeconds -gt 0) {
        Write-Info "Extending BOOTSTRAP_TIMEOUT_SECONDS by prompt wait ($($script:PromptTimeOffsetSeconds)s): ${baseTimeout}s -> ${effectiveTimeout}s"
    }
}

function Get-ResolvedConfig {
    $devConfig = Join-Path (Split-Path $ScriptDir -Parent) "config.yaml"

    if (Test-Path $devConfig) {
        Write-Info "Using development config: $devConfig"
        return [PSCustomObject]@{
            ConfigFile = $devConfig
            ConfigDir = (Split-Path $ScriptDir -Parent)
        }
    }

    $scriptConfig = Join-Path $ScriptDir "config.yaml"
    if (Test-Path $scriptConfig) {
        Write-Info "Using config: $scriptConfig"
        return [PSCustomObject]@{
            ConfigFile = $scriptConfig
            ConfigDir = $ScriptDir
        }
    }

    $userConfig = "$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml"
    if (Test-Path $userConfig) {
        Write-Info "Using user config: $userConfig"
        return [PSCustomObject]@{
            ConfigFile = $userConfig
            ConfigDir = "$env:USERPROFILE\Documents\TranscriptionSuite"
        }
    }

    if ($Mode -eq "remote") {
        Write-ErrorMsg "No config.yaml found"
        Write-Host ""
        Write-Host "Checked locations:"
        Write-Host "  1. $devConfig (development)"
        Write-Host "  2. $(Join-Path $ScriptDir 'config.yaml') (script directory)"
        Write-Host "  3. $env:USERPROFILE\Documents\TranscriptionSuite\config.yaml (user config)"
        Write-Host ""
        Write-Host "For end users: Run setup.ps1 first to create the config file."
        Write-Host "For development: config.yaml should be in server\ directory."
        exit 1
    }

    Write-Info "No config.yaml found (using container defaults)"
    return [PSCustomObject]@{
        ConfigFile = ""
        ConfigDir = ""
    }
}

function Get-ResolvedEnvFile {
    $devEnv = Join-Path (Split-Path $ScriptDir -Parent) ".env"
    if (Test-Path $devEnv) {
        return $devEnv
    }

    $scriptEnv = Join-Path $ScriptDir ".env"
    if (Test-Path $scriptEnv) {
        return $scriptEnv
    }

    $userEnv = "$env:USERPROFILE\Documents\TranscriptionSuite\.env"
    if (Test-Path $userEnv) {
        return $userEnv
    }

    return ""
}

function Get-EnvValue {
    param(
        [string]$EnvFilePath,
        [string]$Key
    )

    if (-not (Test-Path $EnvFilePath)) {
        return ""
    }

    foreach ($line in Get-Content $EnvFilePath) {
        if ($line -match "^\s*#") {
            continue
        }
        if ($line -match "^$Key=(.*)$") {
            return $matches[1].Trim()
        }
    }

    return ""
}

function Set-EnvValue {
    param(
        [string]$EnvFilePath,
        [string]$Key,
        [string]$Value
    )

    if (-not (Test-Path $EnvFilePath)) {
        New-Item -ItemType File -Path $EnvFilePath -Force | Out-Null
    }

    $lines = Get-Content $EnvFilePath -ErrorAction SilentlyContinue
    if (-not $lines) {
        $lines = @()
    }

    $updated = $false
    $result = @()
    foreach ($line in $lines) {
        if ($line -match "^$Key=") {
            if (-not $updated) {
                $result += "$Key=$Value"
                $updated = $true
            }
        } else {
            $result += $line
        }
    }

    if (-not $updated) {
        $result += "$Key=$Value"
    }

    Set-Content -Path $EnvFilePath -Value $result
}

function Test-IsInteractive {
    try {
        return [Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected
    } catch {
        return $false
    }
}

function Initialize-HFTokenDecision {
    param(
        [string]$EnvFilePath
    )

    if ([string]::IsNullOrWhiteSpace($EnvFilePath)) {
        $EnvFilePath = Join-Path $ScriptDir ".env"
        Write-Info "No .env file found, creating: $EnvFilePath"
    } else {
        Write-Info "Using secrets from: $EnvFilePath"
    }

    if (-not (Test-Path $EnvFilePath)) {
        New-Item -ItemType File -Path $EnvFilePath -Force | Out-Null
    }

    $token = Get-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN"
    $decision = (Get-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN_DECISION").ToLowerInvariant()

    if ([string]::IsNullOrWhiteSpace($decision) -or @("unset", "provided", "skipped") -notcontains $decision) {
        $decision = if ([string]::IsNullOrWhiteSpace($token)) { "unset" } else { "provided" }
        Set-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN_DECISION" -Value $decision
    }

    if (-not [string]::IsNullOrWhiteSpace($token) -and $decision -ne "provided") {
        $decision = "provided"
        Set-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN_DECISION" -Value "provided"
    }

    if ([string]::IsNullOrWhiteSpace($token) -and $decision -eq "unset") {
        if (Test-IsInteractive) {
            Write-Info "Optional setup: HuggingFace token enables speaker diarization."
            Write-Info "Model terms must be accepted first: $HfDiarizationTermsUrl"
            Write-Info "You can skip now and add it later in .env."
            $promptStartedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $promptToken = Read-Host "Enter HuggingFace token (leave empty to skip)"
            Add-PromptElapsedSeconds -StartedAtEpochSeconds $promptStartedAt

            if (-not [string]::IsNullOrWhiteSpace($promptToken)) {
                Set-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN" -Value $promptToken.Trim()
                Set-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN_DECISION" -Value "provided"
                Write-Info "HuggingFace token saved."
            } else {
                Set-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN_DECISION" -Value "skipped"
                Write-Info "Diarization token setup skipped for now."
            }
        } else {
            Set-EnvValue -EnvFilePath $EnvFilePath -Key "HUGGINGFACE_TOKEN_DECISION" -Value "skipped"
            Write-Info "Non-interactive startup detected. Marked diarization token setup as skipped."
        }
    }

    return $EnvFilePath
}

function Update-ComposeUVCacheMode {
    param(
        [string]$ComposeFilePath,
        [ValidateSet("enabled", "skipped")]
        [string]$Decision
    )

    if (-not (Test-Path $ComposeFilePath)) {
        return
    }

    $cacheDir = if ($Decision -eq "enabled") { "/runtime-cache" } else { "/tmp/uv-cache" }
    $content = Get-Content -Path $ComposeFilePath -Raw

    $content = [regex]::Replace(
        $content,
        '(?m)^(\s*-\s*BOOTSTRAP_CACHE_DIR=).*$',
        "`$1$cacheDir"
    )

    if ($Decision -eq "enabled") {
        if (-not [regex]::IsMatch($content, '(?m)^\s*-\s*uv-cache:/runtime-cache\b')) {
            $runtimeMountRegex = [regex]::new('(?m)^(\s*-\s*(runtime-deps|runtime-cache):/runtime\b.*)$')
            $content = $runtimeMountRegex.Replace(
                $content,
                "`$1`n      - uv-cache:/runtime-cache  # Persistent uv cache for delta dependency updates",
                1
            )
        }

        if (-not [regex]::IsMatch($content, '(?m)^  uv-cache:\s*$')) {
            $runtimeNameRegex = [regex]::new('(?m)^(\s*name:\s*transcriptionsuite-runtime\s*)$')
            $content = $runtimeNameRegex.Replace(
                $content,
                "`$1`n  uv-cache:`n    name: transcriptionsuite-uv-cache",
                1
            )
        }
    } else {
        $content = [regex]::Replace(
            $content,
            '(?m)^\s*-\s*uv-cache:/runtime-cache\b.*\r?\n?',
            ''
        )
        $content = [regex]::Replace(
            $content,
            '(?ms)^  uv-cache:\s*\r?\n(?:    .*\r?\n)*',
            ''
        )
    }

    Set-Content -Path $ComposeFilePath -Value $content
}

function Initialize-UVCacheDecision {
    param(
        [string]$EnvFilePath,
        [string]$ComposeFilePath
    )

    $decision = (Get-EnvValue -EnvFilePath $EnvFilePath -Key "UV_CACHE_VOLUME_DECISION").ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($decision) -or @("unset", "enabled", "skipped") -notcontains $decision) {
        $decision = "unset"
        Set-EnvValue -EnvFilePath $EnvFilePath -Key "UV_CACHE_VOLUME_DECISION" -Value $decision
    }

    if ($decision -eq "unset") {
        $cacheVolumeExists = docker volume ls --format "{{.Name}}" 2>$null | Where-Object { $_ -eq "transcriptionsuite-uv-cache" }
        if ($cacheVolumeExists) {
            $decision = "enabled"
            Set-EnvValue -EnvFilePath $EnvFilePath -Key "UV_CACHE_VOLUME_DECISION" -Value $decision
            Write-Info "Detected existing UV cache volume. Persistent cache auto-enabled."
        } elseif (Test-IsInteractive) {
            Write-Info "Optional setup: persistent UV cache speeds future updates."
            Write-Info "Disk usage may grow to ~8GB."
            Write-Info "Skipping keeps server functionality unchanged but can slow future updates."
            $promptStartedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            while ($true) {
                $choice = (Read-Host "Enable UV cache volume? [Y]es / [n]o / [c]ancel").Trim().ToLowerInvariant()
                if ([string]::IsNullOrWhiteSpace($choice) -or @("y", "yes") -contains $choice) {
                    $decision = "enabled"
                    break
                }
                if (@("n", "no") -contains $choice) {
                    $decision = "skipped"
                    break
                }
                if (@("c", "cancel") -contains $choice) {
                    Add-PromptElapsedSeconds -StartedAtEpochSeconds $promptStartedAt
                    Write-Info "Startup cancelled."
                    return $false
                }
                Write-Info "Please answer yes, no, or cancel."
            }
            Add-PromptElapsedSeconds -StartedAtEpochSeconds $promptStartedAt
            Set-EnvValue -EnvFilePath $EnvFilePath -Key "UV_CACHE_VOLUME_DECISION" -Value $decision
        } else {
            $decision = "skipped"
            Set-EnvValue -EnvFilePath $EnvFilePath -Key "UV_CACHE_VOLUME_DECISION" -Value $decision
            Write-Info "Non-interactive startup detected. UV cache setup marked as skipped."
        }
    }

    if ($decision -eq "enabled") {
        $cacheVolumeExists = docker volume ls --format "{{.Name}}" 2>$null | Where-Object { $_ -eq "transcriptionsuite-uv-cache" }
        if (-not $cacheVolumeExists) {
            Write-Info "UV cache volume missing; cold cache expected. Volume will be recreated on start."
        }
    }

    $cacheDir = if ($decision -eq "enabled") { "/runtime-cache" } else { "/tmp/uv-cache" }
    Set-EnvValue -EnvFilePath $EnvFilePath -Key "BOOTSTRAP_CACHE_DIR" -Value $cacheDir
    Update-ComposeUVCacheMode -ComposeFilePath $ComposeFilePath -Decision $decision
    return $true
}

# ============================================================================
# Pre-flight Checks
# ============================================================================
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

$ComposeFile = Join-Path $ScriptDir "docker-compose.yml"
if (-not (Test-Path $ComposeFile)) {
    Write-ErrorMsg "docker-compose.yml not found in $ScriptDir"
    Write-Host ""
    Write-Host "Run setup.ps1 first to set up TranscriptionSuite."
    exit 1
}

# ============================================================================
# Resolve Config/.env
# ============================================================================
$config = Get-ResolvedConfig
$ConfigFile = $config.ConfigFile
$ConfigDirToMount = $config.ConfigDir
$env:USER_CONFIG_DIR = $ConfigDirToMount

$EnvFile = Get-ResolvedEnvFile
$EnvFile = Initialize-HFTokenDecision -EnvFilePath $EnvFile
if (-not (Initialize-UVCacheDecision -EnvFilePath $EnvFile -ComposeFilePath $ComposeFile)) {
    exit 0
}
Set-BootstrapTimeoutForPromptDelay -EnvFilePath $EnvFile
$EnvFileArg = @("--env-file", $EnvFile)

$HostCertPath = ""
$HostKeyPath = ""

# ============================================================================
# Remote-mode TLS setup
# ============================================================================
if ($Mode -eq "remote") {
    $configContent = Get-Content $ConfigFile -Raw

    $certMatch = [regex]::Match($configContent, 'host_cert_path:\s*[''\"]?([^''"#\r\n]+)[''\"]?')
    $keyMatch = [regex]::Match($configContent, 'host_key_path:\s*[''\"]?([^''"#\r\n]+)[''\"]?')

    $HostCertPath = if ($certMatch.Success) { $certMatch.Groups[1].Value.Trim() } else { "" }
    $HostKeyPath = if ($keyMatch.Success) { $keyMatch.Groups[1].Value.Trim() } else { "" }

    $HostCertPath = $HostCertPath -replace '^~[/\\]?', "$env:USERPROFILE\"
    $HostKeyPath = $HostKeyPath -replace '^~[/\\]?', "$env:USERPROFILE\"

    $HostCertPath = $HostCertPath -replace '/', '\\'
    $HostKeyPath = $HostKeyPath -replace '/', '\\'

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
}

# ============================================================================
# Check for Existing Container and Mode Conflicts
# ============================================================================
$containerExists = docker ps -a --format "{{.Names}}" 2>$null | Where-Object { $_ -eq $ContainerName }
if ($containerExists) {
    Write-Info "Container already exists, checking mode..."

    $envOutput = docker inspect $ContainerName --format "{{range .Config.Env}}{{println .}}{{end}}" 2>$null
    $currentTLS = "false"
    if ($envOutput) {
        $match = $envOutput | Select-String "^TLS_ENABLED=(.+)"
        if ($match) {
            $currentTLS = $match.Matches.Groups[1].Value
        }
    }

    $needsRecreate = ($Mode -eq "local" -and $currentTLS -eq "true") -or ($Mode -eq "remote" -and $currentTLS -ne "true")
    if ($needsRecreate) {
        if ($Mode -eq "local") {
            Write-Info "Mode conflict: container is in remote/TLS mode, but starting in local mode"
        } else {
            Write-Info "Mode conflict: container is in local mode, but starting in remote/TLS mode"
        }
        Write-Info "Removing existing container..."
        Set-Location $ScriptDir
        docker compose down 2>&1 | Where-Object { $_ -notmatch "No resource found to remove" } | Out-Host
    } else {
        Write-Info "Container is already in $Mode mode"
    }
}

# Check if image exists
$imageExists = docker images --format "{{.Repository}}:{{.Tag}}" 2>$null | Where-Object { $_ -eq $DockerImage }
if ($imageExists) {
    Write-Info "Using existing image: $DockerImage"
} else {
    Write-Info "Image will be built on first run"
}

# ============================================================================
# Start Container
# ============================================================================
if ($Mode -eq "remote") {
    Write-Status "Starting TranscriptionSuite server (remote/TLS mode)..."
    $env:TLS_ENABLED = "true"
    $env:TLS_CERT_PATH = $HostCertPath
    $env:TLS_KEY_PATH = $HostKeyPath
} else {
    Write-Status "Starting TranscriptionSuite server (local mode)..."
    $env:TLS_ENABLED = "false"
    Remove-Item Env:TLS_CERT_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:TLS_KEY_PATH -ErrorAction SilentlyContinue
}

Set-Location $ScriptDir

$composeOutput = docker compose @EnvFileArg up -d 2>&1
if ($LASTEXITCODE -ne 0) {
    $composeOutput | Out-Host
    exit $LASTEXITCODE
}

$composeOutput | Where-Object { $_ -notmatch "WARN\[0000\] No services to build" } | Out-Host

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
if ($Mode -eq "remote") {
    Write-Host "  TranscriptionSuite Server Started (Remote/TLS Mode)" -ForegroundColor Cyan
} else {
    Write-Host "  TranscriptionSuite Server Started (Local Mode)" -ForegroundColor Cyan
}
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

if ($Mode -eq "remote") {
    Write-Host "  HTTPS URL:   https://localhost:8443"
    Write-Host "  Web UI:      https://localhost:8443/record"
    Write-Host "  Notebook:    https://localhost:8443/notebook"
    Write-Host ""
    Write-Host "  Certificate: $HostCertPath"
    Write-Host "  Key:         $HostKeyPath"
} else {
    Write-Host "  Server URL:  http://localhost:8000"
    Write-Host "  Web UI:      http://localhost:8000/record"
    Write-Host "  Notebook:    http://localhost:8000/notebook"
}

Write-Host ""
Write-Host "  Note: On first run, an admin token will be generated."
Write-Host "        Wait ~10 seconds, then run:"
Write-Host "        docker compose logs | Select-String `"Admin Token:`""
Write-Host ""
Write-Host "  View logs:   docker compose logs -f"
Write-Host "  Stop:        .\stop.ps1"
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
