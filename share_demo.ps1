# share_demo.ps1 - مشاركة جنان بيز عبر رابط عام
# يفتح الخادم ويولّد رابط CloudFlare يمكن إرساله لأي شخص
#
# الاستخدام: powershell -ExecutionPolicy Bypass -File share_demo.ps1

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Definition)

$Python     = ".venv\Scripts\python.exe"
$RunScript  = "run_production.py"
$Port       = 5001
$CloudFlare = (Get-Command cloudflared -ErrorAction SilentlyContinue)?.Source

Write-Host ""
Write-Host "  ╔═══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║        جنان بيز — مشاركة النسخة التجريبية        ║" -ForegroundColor Cyan
Write-Host "  ╚═══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. التحقق من المتطلبات ──────────────────────────────────────────
if (-not (Test-Path $Python)) {
    Write-Host "  ✗ خطأ: .venv غير موجود" -ForegroundColor Red
    Read-Host "اضغط Enter للخروج"; exit 1
}
if (-not $CloudFlare) {
    Write-Host "  ✗ خطأ: cloudflared غير مثبت" -ForegroundColor Red
    Read-Host "اضغط Enter للخروج"; exit 1
}

# ── 2. تشغيل الخادم ─────────────────────────────────────────────────
$env:FLASK_ENV    = "production"
$env:HOST         = "127.0.0.1"
$env:PORT         = $Port
$env:BEHIND_PROXY = "true"

Write-Host "  ▶ تشغيل الخادم..." -ForegroundColor Yellow
$serverProc = Start-Process -FilePath (Resolve-Path $Python) `
    -ArgumentList $RunScript `
    -WorkingDirectory (Get-Location).Path `
    -WindowStyle Hidden -PassThru

# انتظار حتى يبدأ الخادم (أقصى 20 ثانية)
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}

if (-not $ready) {
    Write-Host "  ✗ فشل تشغيل الخادم" -ForegroundColor Red
    $serverProc | Stop-Process -Force -ErrorAction SilentlyContinue
    Read-Host "اضغط Enter للخروج"; exit 1
}
Write-Host "  ✓ الخادم يعمل على المنفذ $Port" -ForegroundColor Green

# ── 3. إنشاء نفق CloudFlare ──────────────────────────────────────────
Write-Host "  ▶ إنشاء الرابط العام (CloudFlare)..." -ForegroundColor Yellow

$tunnelLog = Join-Path $env:TEMP "jenan_tunnel_$(Get-Date -Format 'HHmmss').log"
$tunnelProc = Start-Process -FilePath $CloudFlare `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" `
    -RedirectStandardError $tunnelLog `
    -WindowStyle Hidden -PassThru

# استخراج الرابط من مخرجات CloudFlare
$publicUrl = ""
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $tunnelLog) {
        $content = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($content -match 'https://[a-z0-9\-]+\.trycloudflare\.com') {
            $publicUrl = $Matches[0]
            break
        }
    }
}

if (-not $publicUrl) {
    Write-Host "  ✗ تعذّر الحصول على رابط عام" -ForegroundColor Red
} else {
    # ── 4. عرض الرابط ──────────────────────────────────────────────────
    Write-Host ""
    Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║  ✅ الرابط جاهز للمشاركة!                                    ║" -ForegroundColor Green
    Write-Host "  ║                                                               ║" -ForegroundColor Green
    Write-Host "  ║  $publicUrl" -ForegroundColor White
    Write-Host "  ║                                                               ║" -ForegroundColor Green
    Write-Host "  ║  أرسل هذا الرابط لأي شخص ليجرب البرنامج                      ║" -ForegroundColor Green
    Write-Host "  ║  يعمل من أي مكان في العالم بدون تثبيت                        ║" -ForegroundColor Green
    Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""

    # نسخ الرابط للحافظة
    Set-Clipboard -Value $publicUrl
    Write-Host "  📋 تم نسخ الرابط للحافظة تلقائياً" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  ⚠️  ملاحظة: الرابط مؤقت ويعمل طالما هذه النافذة مفتوحة" -ForegroundColor Yellow
    Write-Host "  ⚠️  أغلق هذه النافذة لإيقاف المشاركة" -ForegroundColor Yellow
    Write-Host ""

    # فتح الرابط محلياً للتحقق
    Start-Process $publicUrl
}

# ── 5. الانتظار حتى إغلاق المستخدم ──────────────────────────────────
Write-Host "  اضغط Ctrl+C أو أغلق النافذة لإيقاف الخادم والرابط" -ForegroundColor Gray
try {
    while ($true) {
        Start-Sleep -Seconds 5
        if ($serverProc.HasExited -or $tunnelProc.HasExited) { break }
        Write-Host "  ● مشاركة نشطة | $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor DarkGreen -NoNewline
        Write-Host "`r" -NoNewline
    }
} finally {
    Write-Host "`n  ■ إيقاف الخادم والرابط..." -ForegroundColor Gray
    $serverProc  | Stop-Process -Force -ErrorAction SilentlyContinue
    $tunnelProc  | Stop-Process -Force -ErrorAction SilentlyContinue
    Remove-Item $tunnelLog -ErrorAction SilentlyContinue
    Write-Host "  ✓ تم الإيقاف" -ForegroundColor Gray
}
