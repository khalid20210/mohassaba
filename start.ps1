# start.ps1 — تشغيل النظام اليومي (محلي)
# الاستخدام: .\.venv\Scripts\Activate.ps1؛ ثم: .\start.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "  جنان بيز — تشغيل النظام" -ForegroundColor Cyan
Write-Host "  ========================" -ForegroundColor Cyan
Write-Host ""

# [1] إيقاف أي خادم قديم على 5001
$old = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue
if ($old) {
    $oldPids = @($old | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($pidToStop in $oldPids) {
        Write-Host "  [1] إيقاف عملية قديمة على 5001 (PID=$pidToStop)..." -ForegroundColor Yellow
        Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "  [1] المنفذ 5001 متاح ✓" -ForegroundColor Green
}

# [2] متغيرات البيئة
$env:FLASK_ENV            = "production"
$env:DEBUG                = "false"
$env:HOST                 = "127.0.0.1"
$env:PORT                 = "5001"
$env:SESSION_COOKIE_SECURE = "false"     # للوضع المحلي فقط عبر HTTP
$env:WAITRESS_THREADS     = "16"
$env:BEHIND_PROXY         = "false"

if ($env:HOST -ne "127.0.0.1" -and $env:SESSION_COOKIE_SECURE -ne "true") {
    throw "SESSION_COOKIE_SECURE يجب أن يكون true عند التشغيل خارج localhost"
}

# جلب SECRET_KEY من .env.production إذا كان موجوداً
if (Test-Path ".env.production") {
    $sk = (Get-Content ".env.production" | Where-Object { $_ -match "^SECRET_KEY=" }) -replace "^SECRET_KEY=",""
    if ($sk) { $env:SECRET_KEY = $sk }
}

Write-Host "  [2] البيئة جاهزة ✓" -ForegroundColor Green

# [3] فحص سريع للقاعدة
$count = & ".venv\Scripts\python.exe" -c "import sqlite3; db=sqlite3.connect('database/accounting_dev.db'); print(db.execute('SELECT COUNT(*) FROM businesses WHERE is_active=1').fetchone()[0])"
Write-Host "  [3] قاعدة البيانات: $count منشأة نشطة ✓" -ForegroundColor Green

# [4] تشغيل Waitress
Write-Host ""
Write-Host "  [4] بدء تشغيل الخادم على http://127.0.0.1:5001" -ForegroundColor Cyan
Write-Host ""

& ".venv\Scripts\python.exe" run_production.py
