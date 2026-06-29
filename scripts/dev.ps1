param(
    [string]$HostAddress = "127.0.0.1",
    [int]$ServerPort = $(if ($env:OCTOPUS_PORT) { [int]$env:OCTOPUS_PORT } else { 8000 }),
    [int]$UiPort = 5175
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$UiRoot = Join-Path $RepoRoot "ui"
$LogRoot = Join-Path $RepoRoot ".octopus\dev-logs"
$script:ManagedProcesses = @()
$script:CleaningUp = $false

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Get-ProcessCommandLine {
    param([int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return "<process exited>"
    }
    return $process.CommandLine
}

function Assert-PortAvailable {
    param(
        [int]$Port,
        [string]$Label
    )

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($null -eq $listeners) {
        return
    }

    $owners = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owner in $owners) {
        $commandLine = Get-ProcessCommandLine -ProcessId $owner
        Write-Host "Port $Port for $Label is already in use by PID $owner." -ForegroundColor Red
        Write-Host $commandLine
    }
    throw "Stop the process above or choose a different port before starting Octopus dev."
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId $child.ProcessId
    }

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-PortOwnerIfOctopus {
    param(
        [int]$Port,
        [string]$Label
    )

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($null -eq $listeners) {
        return
    }

    $owners = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owner in $owners) {
        $commandLine = Get-ProcessCommandLine -ProcessId $owner
        if ($commandLine -and $commandLine.Contains($RepoRoot)) {
            Write-Host "Stopping $Label port owner PID $owner..."
            Stop-ProcessTree -ProcessId $owner
        }
    }
}

function Stop-ManagedProcesses {
    if ($script:CleaningUp) {
        return
    }
    $script:CleaningUp = $true

    foreach ($entry in @($script:ManagedProcesses | Sort-Object { $_.Process.Id } -Descending)) {
        $child = $entry.Process
        if ($null -ne (Get-Process -Id $child.Id -ErrorAction SilentlyContinue)) {
            Write-Host "Stopping $($entry.Label) PID $($child.Id)..."
            Stop-ProcessTree -ProcessId $child.Id
        }
    }
    Stop-PortOwnerIfOctopus -Port $ServerPort -Label "Octopus server"
    Stop-PortOwnerIfOctopus -Port $UiPort -Label "Octopus UI"
}

function Start-ManagedProcess {
    param(
        [string]$Label,
        [string]$Command,
        [string]$WorkingDirectory
    )

    $safeLabel = $Label.ToLowerInvariant() -replace "[^a-z0-9]+", "-"
    $stdout = Join-Path $LogRoot "$safeLabel.out.log"
    $stderr = Join-Path $LogRoot "$safeLabel.err.log"

    Write-Host "Starting ${Label}: $Command"
    Write-Host "  stdout: $stdout"
    Write-Host "  stderr: $stderr"
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    $script:ManagedProcesses += [pscustomobject]@{
        Label = $Label
        Process = $process
        Stdout = $stdout
        Stderr = $stderr
    }
    return $process
}

Register-EngineEvent PowerShell.Exiting -Action {
    Stop-ManagedProcesses
} | Out-Null

trap [System.Management.Automation.PipelineStoppedException] {
    Stop-ManagedProcesses
    exit 130
}

Assert-PortAvailable -Port $ServerPort -Label "Octopus server"
Assert-PortAvailable -Port $UiPort -Label "Octopus UI"

if (-not $env:OCTOPUS_HOST) {
    $env:OCTOPUS_HOST = $HostAddress
}
if (-not $env:OCTOPUS_PORT) {
    $env:OCTOPUS_PORT = [string]$ServerPort
}
if (-not $env:OCTOPUS_HOME) {
    $env:OCTOPUS_HOME = Join-Path $RepoRoot ".octopus"
}
if (-not $env:OCTOPUS_AUTO_MIGRATE) {
    $env:OCTOPUS_AUTO_MIGRATE = "1"
}
if (-not $env:OCTOPUS_LOCAL_TRUSTED) {
    $env:OCTOPUS_LOCAL_TRUSTED = "1"
}

try {
    Start-ManagedProcess -Label "server" -Command ".\.venv\Scripts\python.exe -m server" -WorkingDirectory $RepoRoot | Out-Null
    Start-ManagedProcess -Label "UI" -Command "npm run dev -- --host $HostAddress --port $UiPort" -WorkingDirectory $UiRoot | Out-Null

    Write-Host ""
    Write-Host "Octopus server: http://$HostAddress`:$ServerPort"
    Write-Host "Octopus UI:     http://$HostAddress`:$UiPort"
    Write-Host "Press Ctrl+C to stop both processes."

    while ($true) {
        foreach ($entry in $script:ManagedProcesses) {
            $child = $entry.Process
            $running = Get-Process -Id $child.Id -ErrorAction SilentlyContinue
            if ($null -eq $running) {
                throw "Managed process $($entry.Label) PID $($child.Id) exited. Check $($entry.Stdout) and $($entry.Stderr)."
            }
        }
        Start-Sleep -Seconds 1
    }
}
finally {
    Stop-ManagedProcesses
}
