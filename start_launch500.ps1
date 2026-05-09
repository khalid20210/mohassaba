$ErrorActionPreference = 'Stop'

Set-Location "$PSScriptRoot"

function Stop-ExistingLaunchProcesses {
  $procs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and (
      $_.CommandLine -match 'run_production.py' -or $_.CommandLine -match 'run_rq_worker.py'
    )
  }
  foreach ($p in $procs) {
    try {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
      Write-Host "Stopped old process: PID=$($p.ProcessId)"
    } catch {
      Write-Host "Warning: could not stop PID=$($p.ProcessId)"
    }
  }
}

function Wait-ApiReady {
  param(
    [string]$Url = "http://127.0.0.1:5001/healthz",
    [int]$TimeoutSec = 30
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $res = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 3
      if ($res.StatusCode -eq 200) { return $true }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  return $false
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  throw "Virtual environment not found: .venv\Scripts\python.exe"
}

if (-not (Test-Path ".env.production")) {
  throw "Missing .env.production. Copy .env.launch500.example and adjust values."
}

Get-Content ".env.production" | ForEach-Object {
  if ($_ -match '^\s*#') { return }
  if ($_ -match '^\s*$') { return }
  $pair = $_ -split '=', 2
  if ($pair.Count -eq 2) {
    [Environment]::SetEnvironmentVariable($pair[0], $pair[1], 'Process')
  }
}

if (-not $env:SECRET_KEY -or $env:SECRET_KEY -match '^CHANGE_ME') {
  $newSecret = & ".\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(32))"
  (Get-Content ".env.production") -replace '^SECRET_KEY=.*$', "SECRET_KEY=$newSecret" | Set-Content ".env.production" -Encoding UTF8
  [Environment]::SetEnvironmentVariable('SECRET_KEY', $newSecret, 'Process')
  Write-Host "Generated secure SECRET_KEY and updated .env.production"
}

Write-Host "[1/3] Preflight check..."
& ".\.venv\Scripts\python.exe" preflight_launch500.py
if ($LASTEXITCODE -ne 0) { throw "Preflight failed. Fix environment before launch." }

Write-Host "[2/4] Stop old API/Worker processes if any..."
Stop-ExistingLaunchProcesses

Write-Host "[3/4] Start API server..."
$apiProc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "run_production.py" -PassThru

$healthPort = if ($env:PORT) { $env:PORT } else { "5001" }
if (-not (Wait-ApiReady -Url "http://127.0.0.1:$healthPort/healthz" -TimeoutSec 40)) {
  throw "API did not become healthy within timeout"
}

Write-Host "API is healthy. PID=$($apiProc.Id)"

Write-Host "[4/4] Start RQ worker..."
$workerProc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "run_rq_worker.py" -PassThru

Write-Host "Launch500 started: API + Worker | API PID=$($apiProc.Id) | Worker PID=$($workerProc.Id)"
