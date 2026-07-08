# deploy_cloud.ps1 - نشر جنان بيز على السحابة
# يدعم: Render.com | Fly.io
# الاستخدام: powershell -ExecutionPolicy Bypass -File deploy_cloud.ps1

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Definition)

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║        جنان بيز — نشر على السحابة                   ║" -ForegroundColor Cyan
Write-Host "  ║    وصول من أي مكان في العالم | بدون جهازك            ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  اختر المنصة:" -ForegroundColor Yellow
Write-Host "  1) Render.com  — سهل | مجاني | سنغافورة (أقرب للسعودية)" -ForegroundColor White
Write-Host "  2) Fly.io      — أسرع | مجاني | دبي (الأقرب للسعودية)"   -ForegroundColor White
Write-Host "  3) Docker محلي — على الشبكة المحلية فقط"                  -ForegroundColor Gray
Write-Host ""

$choice = Read-Host "  اختر (1/2/3)"

switch ($choice) {

    "1" {
        # ─── Render.com ─────────────────────────────────────────────────
        Write-Host ""
        Write-Host "  ═══ نشر على Render.com ═══" -ForegroundColor Green
        Write-Host ""
        Write-Host "  الخطوات (تستغرق 3 دقائق):" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  1. افتح: https://render.com" -ForegroundColor White
        Write-Host "  2. انقر: Get Started for Free" -ForegroundColor White
        Write-Host "  3. سجّل دخول بـ GitHub" -ForegroundColor White
        Write-Host "  4. انقر: New + → Web Service" -ForegroundColor White
        Write-Host "  5. اختر المستودع: khalid20210/mohassaba" -ForegroundColor Yellow
        Write-Host "     (أو الفرع: feat/production-readiness-perf)" -ForegroundColor Yellow
        Write-Host "  6. الإعدادات التلقائية من render.yaml ✓" -ForegroundColor Green
        Write-Host "  7. انقر: Create Web Service" -ForegroundColor White
        Write-Host ""
        Write-Host "  ✅ ستحصل على رابط مثل:" -ForegroundColor Green
        Write-Host "     https://jenan-biz.onrender.com" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  ⚠️  ملاحظات Render.com المجاني:" -ForegroundColor Yellow
        Write-Host "     - ينام بعد 15 دقيقة عدم استخدام (يستيقظ في 30 ثانية)" -ForegroundColor Gray
        Write-Host "     - البيانات مؤقتة (تُحذف عند إعادة النشر)" -ForegroundColor Gray
        Write-Host "     - للبيانات الدائمة: أضف Persistent Disk ($7/شهر)" -ForegroundColor Gray
        Write-Host ""
        Start-Process "https://render.com/deploy?repo=https://github.com/khalid20210/mohassaba"
    }

    "2" {
        # ─── Fly.io ─────────────────────────────────────────────────────
        Write-Host ""
        Write-Host "  ═══ نشر على Fly.io (دبي) ═══" -ForegroundColor Green
        Write-Host ""

        $flyCmd = Get-Command flyctl -ErrorAction SilentlyContinue
        if (-not $flyCmd) {
            Write-Host "  تثبيت flyctl..." -ForegroundColor Yellow
            Invoke-WebRequest "https://fly.io/install.ps1" -UseBasicParsing | Invoke-Expression
            $flyCmd = Get-Command flyctl -ErrorAction SilentlyContinue
        }

        if (-not $flyCmd) {
            Write-Host "  ✗ تعذّر تثبيت flyctl تلقائياً" -ForegroundColor Red
            Write-Host "  ثبّت يدوياً من: https://fly.io/docs/hands-on/install-flyctl/" -ForegroundColor Yellow
            Start-Process "https://fly.io/docs/hands-on/install-flyctl/"
        } else {
            Write-Host "  1. تسجيل الدخول..." -ForegroundColor Yellow
            & flyctl auth login

            Write-Host "  2. إنشاء التطبيق..." -ForegroundColor Yellow
            & flyctl apps create jenan-biz --org personal 2>$null

            Write-Host "  3. إنشاء حجم التخزين للبيانات..." -ForegroundColor Yellow
            & flyctl volumes create jenan_data --app jenan-biz --size 1 --region dxb 2>$null

            Write-Host "  4. ضبط متغيرات البيئة..." -ForegroundColor Yellow
            $sk = & ".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(32))"
            & flyctl secrets set SECRET_KEY=$sk --app jenan-biz

            Write-Host "  5. النشر..." -ForegroundColor Yellow
            & flyctl deploy --app jenan-biz

            Write-Host ""
            Write-Host "  ✅ تم النشر! رابطك:" -ForegroundColor Green
            Write-Host "     https://jenan-biz.fly.dev" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  ⭐ مميزات Fly.io:" -ForegroundColor Green
            Write-Host "     - خادم في دبي (ping منخفض للسعودية)" -ForegroundColor Gray
            Write-Host "     - بيانات دائمة على القرص" -ForegroundColor Gray
            Write-Host "     - يعمل 24/7 بدون انقطاع" -ForegroundColor Gray
        }
    }

    "3" {
        # ─── Docker محلي ────────────────────────────────────────────────
        Write-Host ""
        Write-Host "  ═══ تشغيل Docker محلياً ═══" -ForegroundColor Green
        Write-Host ""

        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if (-not $docker) {
            Write-Host "  ✗ Docker غير مثبت" -ForegroundColor Red
            Write-Host "  حمّله من: https://desktop.docker.com" -ForegroundColor Yellow
            Start-Process "https://desktop.docker.com"
        } else {
            Write-Host "  بناء الصورة..." -ForegroundColor Yellow
            & docker compose up --build -d

            Start-Sleep -Seconds 5
            try {
                $r = Invoke-WebRequest "http://127.0.0.1:5001/healthz" -UseBasicParsing -TimeoutSec 5
                $localIP = (Get-NetIPAddress -AddressFamily IPv4 |
                    Where-Object { $_.InterfaceAlias -notmatch "Loopback" } |
                    Select-Object -First 1).IPAddress

                Write-Host ""
                Write-Host "  ✅ يعمل على:" -ForegroundColor Green
                Write-Host "     محلي:    http://127.0.0.1:5001" -ForegroundColor Cyan
                Write-Host "     الشبكة:  http://${localIP}:5001" -ForegroundColor Cyan
            } catch {
                Write-Host "  انتظر قليلاً ثم افتح: http://127.0.0.1:5001" -ForegroundColor Yellow
            }
        }
    }

    default {
        Write-Host "  اختيار غير صالح" -ForegroundColor Red
    }
}

Write-Host ""
Read-Host "  اضغط Enter للخروج"
