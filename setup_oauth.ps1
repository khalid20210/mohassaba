# setup_oauth.ps1 — إعداد تسجيل الدخول بجوجل ومايكروسوفت
# الاستخدام: powershell -ExecutionPolicy Bypass -File setup_oauth.ps1

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Definition)
$EnvFile = Join-Path (Get-Location) ".env"

function Add-EnvVar {
    param([string]$Key, [string]$Value)
    $content = Get-Content $EnvFile -ErrorAction SilentlyContinue
    if ($content -match "^$Key=") {
        $content = $content -replace "^$Key=.*", "$Key=$Value"
    } else {
        $content += "$Key=$Value"
    }
    $content | Set-Content $EnvFile -Encoding UTF8
}

Write-Host ""
Write-Host "  ╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   إعداد تسجيل الدخول بجوجل ومايكروسوفت وآبل              ║" -ForegroundColor Cyan
Write-Host "  ╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── تحديد الرابط الأساسي ─────────────────────────────────────────────
$envContent = Get-Content $EnvFile -ErrorAction SilentlyContinue
$existingBase = ($envContent | Select-String "^PUBLIC_BASE_URL=(.+)").Matches.Groups[1].Value
if (-not $existingBase) {
    Write-Host "  ما هو رابط تطبيقك؟" -ForegroundColor Yellow
    Write-Host "  1) محلي فقط (http://127.0.0.1:5001)"
    Write-Host "  2) سحابي  (https://jenan-biz.fly.dev)"
    Write-Host "  3) أدخل رابطاً مخصصاً"
    $bc = Read-Host "  اختر"
    switch ($bc) {
        "1" { $BASE_URL = "http://127.0.0.1:5001" }
        "2" { $BASE_URL = "https://jenan-biz.fly.dev" }
        default { $BASE_URL = Read-Host "  أدخل الرابط الكامل" }
    }
} else {
    $BASE_URL = $existingBase
}

Add-EnvVar "PUBLIC_BASE_URL" $BASE_URL
Write-Host "  ✓ PUBLIC_BASE_URL = $BASE_URL" -ForegroundColor Green

$GOOGLE_CB    = "$BASE_URL/auth/social/google/callback"
$MICROSOFT_CB = "$BASE_URL/auth/social/microsoft/callback"
$APPLE_CB     = "$BASE_URL/auth/social/apple/callback"

Write-Host ""
Write-Host "  روابط الـ Callback التي ستحتاجها:" -ForegroundColor Cyan
Write-Host "  Google:    $GOOGLE_CB" -ForegroundColor Gray
Write-Host "  Microsoft: $MICROSOFT_CB" -ForegroundColor Gray
Write-Host "  Apple:     $APPLE_CB" -ForegroundColor Gray
Write-Host ""

# ══════════════════════════════════════════════════════════
#  GOOGLE
# ══════════════════════════════════════════════════════════
Write-Host "  ┌─── Google OAuth ────────────────────────────────────────┐" -ForegroundColor Green
Write-Host "  │ 1. سيفتح Google Cloud Console                           │" -ForegroundColor Green
Write-Host "  │ 2. اختر أو أنشئ مشروعاً                                 │" -ForegroundColor Green
Write-Host "  │ 3. APIs & Services → Credentials → Create Credentials   │" -ForegroundColor Green
Write-Host "  │ 4. OAuth 2.0 Client ID → Web application               │" -ForegroundColor Green
Write-Host "  │ 5. في Authorized redirect URIs أضف:                      │" -ForegroundColor Green
Write-Host "  │    $GOOGLE_CB" -ForegroundColor White
Write-Host "  │    http://localhost:5001/auth/social/google/callback     │" -ForegroundColor White
Write-Host "  └─────────────────────────────────────────────────────────┘" -ForegroundColor Green
Write-Host ""
$openG = Read-Host "  افتح Google Console الآن؟ (y/n)"
if ($openG -eq "y") {
    Start-Process "https://console.cloud.google.com/apis/credentials"
    Write-Host "  (انتظر حتى تُنشئ المشروع والـ Client ID)" -ForegroundColor Gray
    Read-Host "  اضغط Enter بعد إنشاء الـ Client ID"
}

$gClientId  = Read-Host "  Client ID الخاص بجوجل"
$gClientSec = Read-Host "  Client Secret الخاص بجوجل"

if ($gClientId -and $gClientSec) {
    Add-EnvVar "GOOGLE_OAUTH_CLIENT_ID"     $gClientId
    Add-EnvVar "GOOGLE_OAUTH_CLIENT_SECRET" $gClientSec
    Write-Host "  ✓ Google OAuth مضبوط" -ForegroundColor Green
}

Write-Host ""

# ══════════════════════════════════════════════════════════
#  MICROSOFT
# ══════════════════════════════════════════════════════════
Write-Host "  ┌─── Microsoft OAuth ─────────────────────────────────────┐" -ForegroundColor Blue
Write-Host "  │ 1. سيفتح Azure Portal                                   │" -ForegroundColor Blue
Write-Host "  │ 2. Microsoft Entra ID → App registrations → New         │" -ForegroundColor Blue
Write-Host "  │ 3. Supported account types: Any Azure AD directory      │" -ForegroundColor Blue
Write-Host "  │ 4. Redirect URI (Web):                                  │" -ForegroundColor Blue
Write-Host "  │    $MICROSOFT_CB" -ForegroundColor White
Write-Host "  │ 5. Certificates & secrets → New client secret           │" -ForegroundColor Blue
Write-Host "  └─────────────────────────────────────────────────────────┘" -ForegroundColor Blue
Write-Host ""
$openM = Read-Host "  افتح Azure Portal الآن؟ (y/n)"
if ($openM -eq "y") {
    Start-Process "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
    Read-Host "  اضغط Enter بعد إنشاء التطبيق والـ Secret"
}

$mClientId  = Read-Host "  Application (Client) ID"
$mClientSec = Read-Host "  Client Secret Value"

if ($mClientId -and $mClientSec) {
    Add-EnvVar "MICROSOFT_OAUTH_CLIENT_ID"     $mClientId
    Add-EnvVar "MICROSOFT_OAUTH_CLIENT_SECRET" $mClientSec
    Add-EnvVar "MICROSOFT_OAUTH_TENANT"        "common"
    Write-Host "  ✓ Microsoft OAuth مضبوط" -ForegroundColor Green
}

Write-Host ""

# ══════════════════════════════════════════════════════════
#  النتيجة النهائية
# ══════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  ═══ ملخص الإعداد ═══" -ForegroundColor Cyan
$finalContent = Get-Content $EnvFile
$providers = @{
    "Google"    = "GOOGLE_OAUTH_CLIENT_ID"
    "Microsoft" = "MICROSOFT_OAUTH_CLIENT_ID"
    "Apple"     = "APPLE_OAUTH_CLIENT_ID"
}
foreach ($name in $providers.Keys) {
    $key = $providers[$name]
    $val = ($finalContent | Select-String "^$key=(.+)").Matches.Groups[1].Value
    $status = if ($val) { "✓ مفعّل" } else { "✗ غير مضبوط" }
    Write-Host "  $name $status" -ForegroundColor $(if ($val) { "Green" } else { "Red" })
}

Write-Host ""
Write-Host "  لتطبيق التغييرات: أعد تشغيل الخادم" -ForegroundColor Yellow

# إعادة تشغيل الخادم إذا كان يعمل
$running = Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -eq "" }
if ($running) {
    $restart = Read-Host "  يبدو أن الخادم يعمل. تريد إعادة تشغيله الآن؟ (y/n)"
    if ($restart -eq "y") {
        $running | Stop-Process -Force
        Start-Sleep -Seconds 1
        Start-Process ".venv\Scripts\pythonw.exe" -ArgumentList "launcher.py" -WorkingDirectory (Get-Location).Path
        Write-Host "  ✓ تم إعادة التشغيل" -ForegroundColor Green
    }
}

Write-Host ""
Read-Host "  اضغط Enter للخروج"
