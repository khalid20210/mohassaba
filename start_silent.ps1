$ErrorActionPreference = 'Stop'

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $appDir '.venv\Scripts\python.exe'
$script = Join-Path $appDir 'run_production.py'
$url = 'http://127.0.0.1:5001'

if (-not (Test-Path $python)) {
    throw "Python executable not found: $python"
}
if (-not (Test-Path $script)) {
    throw "Run script not found: $script"
}

# Start server in background
Start-Process -FilePath $python -ArgumentList "`"$script`"" -WorkingDirectory $appDir -WindowStyle Hidden

# Wait until server is reachable (max 20s)
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

# Open browser
if ($ready) {
    Start-Process $url
}
