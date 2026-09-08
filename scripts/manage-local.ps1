[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status",
    [ValidateSet("all", "knowledge-service", "backend", "frontend")]
    [string]$Service = "all"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile = Join-Path $ProjectRoot ".env.development"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\local-services"
$RuntimeLogs = Join-Path $RuntimeRoot "logs"
$CommonChildEnv = @{
    APP_ENV = "development"
    PYTHONUTF8 = "1"
    PYTHONIOENCODING = "utf-8"
}
$ServiceSpecs = @(
    [pscustomobject]@{ Name = "knowledge-service"; Port = 8010; Script = "scripts\knowledge_server.py"; Env = @{ KNOWLEDGE_SERVICE_RELOAD = "false"; LOG_LEVEL = "INFO" } },
    [pscustomobject]@{ Name = "backend"; Port = 8000; Script = "scripts\dev_server.py"; Env = @{ LOG_LEVEL = "INFO" } },
    [pscustomobject]@{ Name = "frontend"; Port = 5174; Script = "scripts\frontend_server.py"; Env = @{} }
)

function Assert-RequiredFiles {
    if (-not (Test-Path $EnvFile)) {
        throw "Missing environment file: $EnvFile"
    }
    if (-not (Test-Path $PythonExe)) {
        throw "Missing virtualenv Python: $PythonExe"
    }
}

function Ensure-RuntimeDirs {
    New-Item -ItemType Directory -Force -Path $RuntimeLogs | Out-Null
}

function Get-ListeningPids {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $pids = @()
    $lines = & netstat -ano -p tcp 2>$null
    foreach ($line in $lines) {
        if ($line -notmatch "LISTENING") {
            continue
        }

        $parts = (($line -replace "\s+", " ").Trim()).Split(" ")
        if ($parts.Count -lt 5) {
            continue
        }

        if ($parts[1].EndsWith(":$Port")) {
            $pids += [int]$parts[-1]
        }
    }

    return $pids | Sort-Object -Unique
}

function Test-PortListening {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    return [bool](Get-ListeningPids -Port $Port)
}

function Wait-ForPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -Port $Port) {
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "$Name did not become ready on port $Port within $TimeoutSeconds seconds"
}

function Get-PidFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return Join-Path $RuntimeRoot "$Name.pid"
}

function Warn-IfInfraMissing {
    if (-not (Test-PortListening -Port 5432)) {
        Write-Warning "Port 5432 is not listening. Start the Docker infrastructure first if the app needs PostgreSQL."
    }
}

function Get-SelectedSpecs {
    if ($Service -eq "all") {
        return $ServiceSpecs
    }
    return @($ServiceSpecs | Where-Object { $_.Name -eq $Service })
}

function Invoke-WithChildEnv {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Env,
        [Parameter(Mandatory = $true)]
        [scriptblock]$ScriptBlock
    )

    $previousValues = @{}
    foreach ($key in $Env.Keys) {
        $previousValues[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Env[$key], "Process")
    }

    try {
        & $ScriptBlock
    } finally {
        foreach ($key in $previousValues.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previousValues[$key], "Process")
        }
    }
}

function Normalize-ProcessPathEnvironment {
    $pathKeys = @([Environment]::GetEnvironmentVariables("Process").Keys | Where-Object { $_ -ieq "Path" })
    if ($pathKeys.Count -le 1) {
        return
    }

    $pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
    if (-not $pathValue) {
        $pathValue = [Environment]::GetEnvironmentVariable("PATH", "Process")
    }

    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
}

function Invoke-TreeKill {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    $previousEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & taskkill /F /T /PID $ProcessId 2>&1 | Out-Null
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousEAP
    }
}

function Stop-TrackedService {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $pidFile = Get-PidFile -Name $Name
    $trackedPid = $null

    # 1. 先停掉 tracked PID（从 pid 文件读到的进程）
    if (Test-Path $pidFile) {
        $rawPid = (Get-Content -Path $pidFile -Raw).Trim()
        if ($rawPid) {
            $trackedPid = [int]$rawPid
            $exit = Invoke-TreeKill -ProcessId $trackedPid
            if ($exit -eq 0) {
                Write-Host "Stopped $Name (PID $trackedPid)"
            } else {
                Write-Warning ("Failed to stop tracked PID {0} for {1}" -f $trackedPid, $Name)
            }
        }
    }

    # 2. 清理端口上残留的 listener（如 uvicorn reload 的 worker 子进程）
    $listenerPids = Get-ListeningPids -Port $Port
    if (-not $listenerPids) {
        Write-Host "$Name is not listening on port $Port"
    } else {
        foreach ($listenerPid in $listenerPids) {
            if ($null -ne $trackedPid -and $listenerPid -eq $trackedPid) {
                continue
            }
            $exit = Invoke-TreeKill -ProcessId $listenerPid
            if ($exit -eq 0) {
                Write-Host "Stopped $Name (PID $listenerPid)"
            } else {
                Write-Warning ("Failed to stop {0} PID {1}" -f $Name, $listenerPid)
            }
        }
    }

    # 3. 清理 pid 文件
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
}

function Start-PythonService {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Spec
    )

    Normalize-ProcessPathEnvironment

    $pidFile = Get-PidFile -Name $Spec.Name
    if (Test-PortListening -Port $Spec.Port) {
        Write-Host "$($Spec.Name) is already listening on port $($Spec.Port)"
        if (-not (Test-Path $pidFile)) {
            $pids = Get-ListeningPids -Port $Spec.Port
            if ($pids) {
                Set-Content -Path $pidFile -Value ($pids[0].ToString()) -Encoding ASCII
            }
        }
        return
    }

    $stdout = Join-Path $RuntimeLogs "$($Spec.Name).out.log"
    $stderr = Join-Path $RuntimeLogs "$($Spec.Name).err.log"
    $scriptPath = Join-Path $ProjectRoot $Spec.Script
    if (-not (Test-Path $scriptPath)) {
        throw "Missing service script: $scriptPath"
    }

    $childEnv = @{}
    foreach ($key in $CommonChildEnv.Keys) {
        $childEnv[$key] = $CommonChildEnv[$key]
    }
    foreach ($key in $Spec.Env.Keys) {
        $childEnv[$key] = $Spec.Env[$key]
    }

    Write-Host "Starting $($Spec.Name) on port $($Spec.Port)..."
    $proc = Invoke-WithChildEnv -Env $childEnv -ScriptBlock {
        Start-Process -FilePath $PythonExe `
            -ArgumentList @("-u", $scriptPath) `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -PassThru
    }

    Set-Content -Path $pidFile -Value $proc.Id -Encoding ASCII
    Write-Host "$($Spec.Name) started with PID $($proc.Id)"
}

function Show-Status {
    Write-Host "Local services:"
    foreach ($spec in (Get-SelectedSpecs)) {
        $pids = Get-ListeningPids -Port $spec.Port
        $pidFile = Get-PidFile -Name $spec.Name
        $trackedPid = if (Test-Path $pidFile) { (Get-Content -Path $pidFile -Raw).Trim() } else { "" }
        $state = if ($pids) { "listening" } else { "stopped" }
        $trackedDisplay = if ($trackedPid) { $trackedPid } else { "-" }
        Write-Host ("- {0,-18} port {1,-5} {2,-10} trackedPid={3}" -f $spec.Name, $spec.Port, $state, $trackedDisplay)
    }
}

function Start-All {
    Assert-RequiredFiles
    Ensure-RuntimeDirs
    Warn-IfInfraMissing

    foreach ($spec in (Get-SelectedSpecs)) {
        Start-PythonService -Spec $spec
        Wait-ForPort -Port $spec.Port -Name $spec.Name -TimeoutSeconds 120
    }

    Write-Host "Local services started."
}

function Stop-All {
    Ensure-RuntimeDirs

    foreach ($spec in ((Get-SelectedSpecs) | Sort-Object Port -Descending)) {
        Stop-TrackedService -Name $spec.Name -Port $spec.Port
    }

    Write-Host "Local services stopped."
}

Assert-RequiredFiles
Ensure-RuntimeDirs

switch ($Action) {
    "start" { Start-All }
    "stop" { Stop-All }
    "restart" {
        Stop-All
        Start-All
    }
    "status" { Show-Status }
}
