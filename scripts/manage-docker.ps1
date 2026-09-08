[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status", "prepare-embedding")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$EnvFile = Join-Path $ProjectRoot ".env.development"

function Assert-RequiredFiles {
    if (-not (Test-Path $EnvFile)) {
        throw "Missing environment file: $EnvFile"
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI not found in PATH"
    }
}

function Ensure-OllamaEmbeddingModel {
    Write-Host "Starting optional local Ollama embedding and pulling model..."
    & docker compose --env-file $EnvFile up -d ollama
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up ollama failed"
    }
    & docker compose --env-file $EnvFile exec -T ollama ollama pull bge-m3
    if ($LASTEXITCODE -ne 0) {
        throw "ollama pull bge-m3 failed"
    }
    Write-Host "Embedding model ready."
}

function Start-DockerInfra {
    Write-Host "Starting Docker infrastructure..."
    & docker compose --env-file $EnvFile up -d db
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed"
    }
    Write-Host "Docker infrastructure started."
}

function Stop-DockerInfra {
    Write-Host "Stopping Docker infrastructure..."
    & docker compose --env-file $EnvFile down --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "docker compose down returned a non-zero exit code"
    }
    Write-Host "Docker infrastructure stopped."
}

function Show-Status {
    Write-Host "Docker infrastructure:"
    try {
        & docker compose --env-file $EnvFile ps --format "table {{.Name}}\t{{.State}}\t{{.Ports}}"
    } catch {
        Write-Host "Docker compose status unavailable"
    }
}

Assert-RequiredFiles

switch ($Action) {
    "start" { Start-DockerInfra }
    "stop" { Stop-DockerInfra }
    "restart" {
        Stop-DockerInfra
        Start-DockerInfra
    }
    "prepare-embedding" { Ensure-OllamaEmbeddingModel }
    "status" { Show-Status }
}
