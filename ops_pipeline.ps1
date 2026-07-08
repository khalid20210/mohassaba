param(
    [string]$BaseUrl = "http://127.0.0.1:5001",
    [double]$MaxHealthP95Ms = 70.0,
    [double]$MaxReadyP95Ms = 170.0,
    [switch]$ExecuteDeploy,
    [switch]$SkipBuild,
    [switch]$SkipStabilize,
    [switch]$SkipSimulate,
    [switch]$SkipAudit,
    [switch]$SkipOptimize,
    [switch]$SkipMonitor,
    [int]$SimulateRetries = 2
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Require-Python {
    if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
        throw "Python venv not found at .venv\\Scripts\\python.exe"
    }
}

function Run-Stage {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Action
    Write-Host "[OK] $Name" -ForegroundColor Green
}

function Read-Json {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Missing report: $Path"
    }
    return Get-Content $Path -Raw | ConvertFrom-Json
}

function Invoke-PythonChecked {
    param([string[]]$PyArgs)
    & ".\.venv\Scripts\python.exe" @PyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: python $($PyArgs -join ' ')"
    }
}

Require-Python

$reportsDir = Join-Path $PSScriptRoot "exports"
if (-not (Test-Path $reportsDir)) {
    New-Item -Path $reportsDir -ItemType Directory | Out-Null
}

$baselinePath = Join-Path $reportsDir "pipeline_baseline.json"
$simulatePath = Join-Path $reportsDir "pipeline_simulation.json"
$auditPath = Join-Path $reportsDir "pipeline_audit_summary.json"
$optimizePath = Join-Path $reportsDir "pipeline_optimize_notes.json"

if (-not $SkipBuild) {
    Run-Stage -Name "Build" -Action {
        Invoke-PythonChecked -PyArgs @("-m", "compileall", "app.py", "modules") | Out-Null
    }
}

if (-not $SkipStabilize) {
    Run-Stage -Name "Stabilize" -Action {
        Invoke-PythonChecked -PyArgs @(
            ".\ops_baseline_check.py",
            "--base-url", $BaseUrl,
            "--health-requests", "120",
            "--health-workers", "20",
            "--ready-requests", "80",
            "--ready-workers", "10",
            "--max-health-p95-ms", "$MaxHealthP95Ms",
            "--max-ready-p95-ms", "$MaxReadyP95Ms",
            "--require-zero-stuck",
            "--output", $baselinePath
        )
    }
}

if (-not $SkipSimulate) {
    Run-Stage -Name "Simulate" -Action {
        $ok = $false
        for ($attempt = 1; $attempt -le ($SimulateRetries + 1); $attempt++) {
            Write-Host "Simulate attempt $attempt/$($SimulateRetries + 1)" -ForegroundColor Yellow
            & ".\.venv\Scripts\python.exe" @(
                ".\ops_realistic_run.py",
                "--base-url", $BaseUrl,
                "--min-success-rate", "99.0",
                "--max-failed-requests", "2",
                "--max-timeout-errors", "1",
                "--output", $simulatePath
            )
            if ($LASTEXITCODE -eq 0) {
                $ok = $true
                break
            }
        }
        if (-not $ok) {
            throw "Simulate failed after retries"
        }
    }
}

$baseline = $null
$simulation = $null

if (-not $SkipAudit) {
    Run-Stage -Name "Audit" -Action {
        $baseline = Read-Json -Path $baselinePath
        $simulation = Read-Json -Path $simulatePath

        $summary = [ordered]@{
            timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            base_url = $BaseUrl
            baseline_pass = [bool]$baseline.verdict.pass
            simulation_pass = [bool]$simulation.verdict.pass
            baseline_ready_p95_ms = [double]$baseline.load_probe."/readyz".latency_ms.p95
            baseline_health_p95_ms = [double]$baseline.load_probe."/healthz".latency_ms.p95
            baseline_max_ready_p95_threshold_ms = [double]$MaxReadyP95Ms
            baseline_max_health_p95_threshold_ms = [double]$MaxHealthP95Ms
            simulation_success_rate = [double]$simulation.simulation.success_rate
            simulation_failed_requests = [int]$simulation.simulation.total_failed
            stuck_state = $baseline.stuck_state
        }

        $summary | ConvertTo-Json -Depth 8 | Set-Content -Path $auditPath -Encoding UTF8
        $summary | ConvertTo-Json -Depth 8

        if (-not $summary.baseline_pass -or -not $summary.simulation_pass) {
            throw "Audit failed: baseline or simulation did not pass thresholds"
        }
    }
}

if (-not $SkipOptimize) {
    Run-Stage -Name "Optimize" -Action {
        if (-not $baseline) { $baseline = Read-Json -Path $baselinePath }

        $readyP95 = [double]$baseline.load_probe."/readyz".latency_ms.p95
        $healthP95 = [double]$baseline.load_probe."/healthz".latency_ms.p95

        $notes = [ordered]@{
            timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            observed = [ordered]@{
                ready_p95_ms = $readyP95
                health_p95_ms = $healthP95
            }
            actions = @(
                "Keep readyz cache TTL between 5-10 seconds for burst traffic",
                "Keep dashboard polling at >=10 seconds",
                "Keep health checks separate from heavy authenticated endpoints"
            )
            status = "applied-by-policy"
        }

        $notes | ConvertTo-Json -Depth 8 | Set-Content -Path $optimizePath -Encoding UTF8
    }
}

Run-Stage -Name "Deploy" -Action {
    if ($ExecuteDeploy) {
        Write-Host "Starting production entry script in current terminal..." -ForegroundColor Yellow
        & ".\start.ps1"
    } else {
        Write-Host "Safe mode: deploy step is gated." -ForegroundColor Yellow
        Write-Host "To deploy explicitly run: .\\ops_pipeline.ps1 -ExecuteDeploy" -ForegroundColor Yellow
    }
}

if (-not $SkipMonitor) {
    Run-Stage -Name "Monitor" -Action {
        $health = Invoke-RestMethod -Uri "$BaseUrl/healthz" -Method Get -TimeoutSec 8
        $ready = Invoke-RestMethod -Uri "$BaseUrl/readyz" -Method Get -TimeoutSec 8
        $monitor = [ordered]@{
            timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            base_url = $BaseUrl
            healthz_status = $health.status
            readyz_status = $ready.status
            readyz_ping_ms = $ready.ping_ms
        }
        $monitor | ConvertTo-Json -Depth 8
    }
}

Write-Host "`nPipeline completed successfully." -ForegroundColor Green
Write-Host "Reports:" -ForegroundColor Cyan
Write-Host " - $baselinePath"
Write-Host " - $simulatePath"
Write-Host " - $auditPath"
Write-Host " - $optimizePath"
