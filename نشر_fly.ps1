# نشر_fly.ps1 — نشر جنان بيز على Fly.io (دبي) بخطوة واحدة
# الاستخدام: powershell -ExecutionPolicy Bypass -File نشر_fly.ps1

$ErrorActionPreference = 'Stop'
$env:Path += ";$env:USERPROFILE\.fly\bin"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Definition)

$APP_NAME = "jenan-biz"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   جنان بيز — النشر على Fly.io (خادم دبي)                ║" -ForegroundColor Cyan
Write-Host "  ║   رابطك: https://$APP_NAME.fly.dev                       ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. التحقق من flyctl ──────────────────────────────────────────────
if (-not (Get-Command flyctl -ErrorAction SilentlyContinue)) {
    Write-Host "  تثبيت flyctl..." -ForegroundColor Yellow
    iwr https://fly.io/install.ps1 -UseBasicParsing | iex
    $env:Path += ";$env:USERPROFILE\.fly\bin"
}
Write-Host "  ✓ flyctl جاهز" -ForegroundColor Green

# ── 2. تسجيل الدخول ─────────────────────────────────────────────────
Write-Host ""
Write-Host "  ▶ تسجيل الدخول..." -ForegroundColor Yellow
Write-Host "  (سيفتح المتصفح — سجّل بالإيميل أو Google أو GitHub)" -ForegroundColor Gray
flyctl auth login

# ── 3. إنشاء التطبيق (إذا لم يكن موجوداً) ──────────────────────────
Write-Host ""
Write-Host "  ▶ إنشاء التطبيق..." -ForegroundColor Yellow
$apps = flyctl apps list 2>$null
if ($apps -notmatch $APP_NAME) {
    flyctl apps create $APP_NAME 2>$null
    Write-Host "  ✓ تم إنشاء التطبيق: $APP_NAME" -ForegroundColor Green
} else {
    Write-Host "  ✓ التطبيق موجود بالفعل" -ForegroundColor Green
}

# ── 4. حجم التخزين للبيانات الدائمة ──────────────────────────────────
Write-Host ""
Write-Host "  ▶ إعداد التخزين الدائم..." -ForegroundColor Yellow
$vols = flyctl volumes list --app $APP_NAME 2>$null
if ($vols -notmatch "jenan_data") {
    flyctl volumes create jenan_data --app $APP_NAME --size 1 --region dxb --yes 2>$null
    Write-Host "  ✓ حجم التخزين جاهز (دبي)" -ForegroundColor Green
} else {
    Write-Host "  ✓ التخزين موجود" -ForegroundColor Green
}

# ── 5. المفتاح السري ─────────────────────────────────────────────────
Write-Host ""
Write-Host "  ▶ ضبط المفتاح السري..." -ForegroundColor Yellow
$sk = & ".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(32))"
flyctl secrets set "SECRET_KEY=$sk" --app $APP_NAME
Write-Host "  ✓ SECRET_KEY مضبوط بأمان" -ForegroundColor Green

# ── 6. النشر ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ▶ نشر التطبيق... (قد يستغرق 2-3 دقائق)" -ForegroundColor Yellow
flyctl deploy --app $APP_NAME --remote-only

# ── 7. النتيجة ────────────────────────────────────────────────────────
Write-Host ""
$url = "https://$APP_NAME.fly.dev"
Write-Host "  ╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║  ✅ تم النشر بنجاح!                                           ║" -ForegroundColor Green
Write-Host "  ║                                                               ║" -ForegroundColor Green
Write-Host "  ║  رابطك الدائم:                                                ║" -ForegroundColor Green
Write-Host "  ║  $url                              ║" -ForegroundColor White
Write-Host "  ║                                                               ║" -ForegroundColor Green
Write-Host "  ║  شارك هذا الرابط مع أي شخص ليستخدم البرنامج                  ║" -ForegroundColor Green
Write-Host "  ║  يمكنهم تثبيته كتطبيق من المتصفح (زر التثبيت)               ║" -ForegroundColor Green
Write-Host "  ╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

Set-Clipboard -Value $url
Write-Host "  📋 تم نسخ الرابط للحافظة" -ForegroundColor Cyan
Start-Process $url
Write-Host ""
Read-Host "  اضغط Enter للخروج"
