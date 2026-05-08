$ErrorActionPreference = 'Stop'

Set-Location "$PSScriptRoot"

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

Write-Host "[2/3] Start API server..."
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "run_production.py" -NoNewWindow

Write-Host "[3/3] Start RQ worker..."
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "run_rq_worker.py" -NoNewWindow

Write-Host "Launch500 started: API + Worker"
