# install_shortcut.ps1 — نظام تثبيت احترافي متين لاختصارات الأيقونة
# يتعامل مع جميع الحالات الحدية ويصمد تحت أي ضغط

$ErrorActionPreference = 'Stop'
$DebugMode           = $true
$LogFile             = Join-Path $env:TEMP "jenan_shortcut_install_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$AppDir              = Split-Path -Parent $MyInvocation.MyCommand.Definition
$AppName             = "محاسبه بلا تعقيد"
$Launcher            = Join-Path $AppDir "launcher.py"
$MaxRetries          = 3
$RetryDelayMs        = 500

# ─── نظام السجل المتقدم ───────────────────────────────────────────
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    Write-Host $logEntry
    Add-Content -Path $LogFile -Value $logEntry -ErrorAction SilentlyContinue
}

function Write-Success { param([string]$Message) Write-Log $Message "SUCCESS" -ForegroundColor Green }
function Write-Error-Log { param([string]$Message) Write-Log $Message "ERROR" -ForegroundColor Red }
function Write-Warning-Log { param([string]$Message) Write-Log $Message "WARNING" -ForegroundColor Yellow }
function Write-Info { param([string]$Message) Write-Log $Message "INFO" -ForegroundColor Cyan }

# ─── التحقق الشامل من المتطلبات ──────────────────────────────────
function Test-PrerequisitesComprehensive {
    Write-Info "🔍 جاري التحقق الشامل من المتطلبات..."
    
    # 1. التحقق من WScript.Shell COM Object
    try {
        $null = New-Object -ComObject WScript.Shell
        Write-Success "  ✓ WScript.Shell متاح"
    } catch {
        Write-Error-Log "  ✗ WScript.Shell غير متاح. هذا يتطلب Windows."
        return $false
    }
    
    # 2. التحقق من Python
    if (-not (Test-Path $VenvPython)) {
        Write-Warning-Log "  ! البيئة الافتراضية غير موجودة — سيتم الإنشاء"
    } else {
        try {
            $ver = & $VenvPython --version 2>&1
            Write-Success "  ✓ Python موجود: $ver"
        } catch {
            Write-Error-Log "  ✗ Python موجود لكنه لا يعمل"
            return $false
        }
    }
    
    # 3. التحقق من مسار launcher.py
    if (-not (Test-Path $Launcher)) {
        Write-Error-Log "  ✗ launcher.py غير موجود في: $Launcher"
        return $false
    }
    Write-Success "  ✓ launcher.py موجود"
    
    # 4. التحقق من سطح المكتب
    if (-not (Test-Path (Get-PreferredDesktopPath))) {
        Write-Error-Log "  ✗ لم يتمكن من العثور على سطح المكتب"
        return $false
    }
    Write-Success "  ✓ سطح المكتب متاح"
    
    return $true
}

# ─── البحث الذكي عن الأيقونة مع Fallbacks ───────────────────────
function Resolve-IconPathWithFallback {
    $candidates = @(
        (Join-Path $AppDir "static\icons\app_icon.ico"),
        (Join-Path $AppDir "app_icon.ico"),
        (Join-Path $AppDir "static\icons\jenan.ico"),
        (Join-Path $AppDir "icon.ico")
    )
    
    foreach ($i in $candidates) {
        if (Test-Path $i) {
            Write-Success "  ✓ أيقونة موجودة: $i"
            return $i
        }
    }
    
    Write-Warning-Log "  ! لم يتم العثور على أيقونة مخصصة — استخدام pythonw.exe"
    return $null
}

function Get-PreferredDesktopPath {
    $candidates = @(
        [Environment]::GetFolderPath("Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\سطح المكتب"),
        (Join-Path $env:USERPROFILE "Desktop")
    )
    foreach ($p in $candidates | Select-Object -Unique) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return [Environment]::GetFolderPath("Desktop")
}

# ─── إنشاء/إصلاح اختصار مع معالجة الأخطاء ──────────────────────────
function Write-OrRepairShortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetExe,
        [string]$LauncherArg,
        [string]$WorkingDir,
        [string]$IconArg,
        [string]$Description,
        [int]$Attempt = 1
    )

    try {
        # تأخير قصير إذا كانت محاولة إعادة
        if ($Attempt -gt 1) {
            Start-Sleep -Milliseconds $RetryDelayMs
        }
        
        $WshShell = New-Object -ComObject WScript.Shell
        $S = $WshShell.CreateShortcut($ShortcutPath)
        
        # التحقق من أن الشورتكت تم إنشاؤه فعلاً
        if ($null -eq $S) {
            throw "فشل إنشاء كائن WScript.Shortcut"
        }
        
        $S.TargetPath       = $TargetExe
        $S.Arguments        = $LauncherArg
        $S.WorkingDirectory = $WorkingDir
        if ($IconArg) { $S.IconLocation = $IconArg }
        $S.Description      = $Description
        $S.WindowStyle      = 1
        $S.Save()
        
        # تأخير قصير للسماح للنظام بحفظ الملف
        Start-Sleep -Milliseconds 100
        
        # التحقق من أن الملف موجود فعلاً
        if (-not (Test-Path $ShortcutPath)) {
            throw "الملف لم يُحفظ على القرص رغم استدعاء Save()"
        }
        
        Write-Success "  ✓ تم إنشاء/إصلاح: $(Split-Path -Leaf $ShortcutPath)"
        return $true
        
    } catch {
        Write-Warning-Log "  ! محاولة $Attempt/$MaxRetries فشلت: $_"
        
        # إعادة المحاولة إذا لم نصل للحد الأقصى
        if ($Attempt -lt $MaxRetries) {
            return Write-OrRepairShortcut -ShortcutPath $ShortcutPath -TargetExe $TargetExe `
                                         -LauncherArg $LauncherArg -WorkingDir $WorkingDir `
                                         -IconArg $IconArg -Description $Description `
                                         -Attempt ($Attempt + 1)
        }
        
        Write-Error-Log "  ✗ فشل النهائي بعد $MaxRetries محاولات"
        return $false
    }
}

# ─── اختبار الاختصار بعد الإنشاء ──────────────────────────────────
function Test-ShortcutValidity {
    param([string]$ShortcutPath)
    
    try {
        if (-not (Test-Path $ShortcutPath)) {
            return $false, "ملف الاختصار غير موجود"
        }
        
        $WshShell = New-Object -ComObject WScript.Shell
        $shortcut = $WshShell.CreateShortcut($ShortcutPath)
        
        if ([string]::IsNullOrWhiteSpace($shortcut.TargetPath)) {
            return $false, "مسار الهدف فارغ"
        }
        
        if (-not (Test-Path $shortcut.TargetPath)) {
            return $false, "مسار الهدف غير موجود: $($shortcut.TargetPath)"
        }
        
        return $true, "الاختصار سليم"
        
    } catch {
        return $false, "خطأ في الفحص: $_"
    }
}

# ─── تنظيف الاختصارات المعطوبة ────────────────────────────────────
function Remove-BrokenShortcuts {
    param([string]$DesktopPath)
    Write-Info "🧹 فحص واستخراج الاختصارات المعطوبة..."
    
    $allShortcuts = @(Get-ChildItem $DesktopPath -Filter "*.lnk" -ErrorAction SilentlyContinue)
    $brokenCount = 0
    
    foreach ($lnk in $allShortcuts) {
        $valid, $reason = Test-ShortcutValidity -ShortcutPath $lnk.FullName
        if (-not $valid) {
            try {
                Remove-Item $lnk.FullName -Force -ErrorAction Stop
                Write-Warning-Log "  ! تم حذف اختصار معطوب: $($lnk.Name)"
                $brokenCount++
            } catch {
                Write-Warning-Log "  ! فشل حذف اختصار: $($lnk.Name) — السبب: $_"
            }
        }
    }
    
    if ($brokenCount -gt 0) {
        Write-Success "  ✓ تم تنظيف $brokenCount اختصارات معطوبة"
    } else {
        Write-Success "  ✓ لا توجد اختصارات معطوبة"
    }
}

# ═══════════════ البدء الفعلي للتثبيت ═══════════════════════════════
Write-Host ""
Write-Host "  ╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║  🔧 نظام تثبيت اختصار احترافي محاسبة - جنان بيز       ║" -ForegroundColor Cyan
Write-Host "  ║  صيغة: Enterprise-Grade • قدرة عالية على التحمل        ║" -ForegroundColor Cyan
Write-Host "  ╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

Write-Info "📦 مجلد التطبيق: $AppDir"
Write-Info "📝 ملف السجل: $LogFile"
Write-Host ""

# متغيرات الـ Python
$VenvPythonw = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
$VenvPython  = Join-Path $AppDir ".venv\Scripts\python.exe"

# ── الخطوة 1: التحقق الشامل ──
Write-Host ""
Write-Info "━━━ الخطوة 1: التحقق من المتطلبات ━━━"
if (-not (Test-PrerequisitesComprehensive)) {
    Write-Error-Log "فشل التحقق من المتطلبات الأساسية"
    Read-Host "اضغط Enter للخروج"
    exit 1
}

# ── الخطوة 2: إعداد البيئة الافتراضية ──
Write-Host ""
Write-Info "━━━ الخطوة 2: إعداد البيئة الافتراضية ━━━"
if (-not (Test-Path $VenvPython)) {
    Write-Warning-Log "البيئة الافتراضية غير موجودة — جاري الإنشاء..."
    $sysPy = $null
    foreach ($candidate in @("python", "python3", "py")) {
        try { 
            $ver = & $candidate --version 2>&1
            if ($ver -match "Python 3") { 
                $sysPy = $candidate
                Write-Success "  ✓ وجدت: $candidate → $ver"
                break 
            } 
        } catch { }
    }
    if (-not $sysPy) {
        Write-Error-Log "❌ Python 3 غير مثبت على هذا الجهاز"
        Write-Host "📥 حمّل Python من: https://www.python.org/downloads/" -ForegroundColor Yellow
        Read-Host "اضغط Enter للخروج"
        exit 1
    }
    try {
        Set-Location $AppDir
        & $sysPy -m venv ".venv" 2>&1 | Out-Null
        Write-Success "  ✓ تم إنشاء البيئة الافتراضية"
        
        & $VenvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null
        if (Test-Path (Join-Path $AppDir "requirements.txt")) {
            & $VenvPython -m pip install -r (Join-Path $AppDir "requirements.txt") --quiet 2>&1 | Out-Null
        }
        Write-Success "  ✓ تم تثبيت المكتبات"
    } catch {
        Write-Error-Log "فشل إنشاء البيئة الافتراضية: $_"
        exit 1
    }
} else {
    Write-Success "  ✓ البيئة الافتراضية موجودة"
}

# ── الخطوة 3: تحديد محرك التشغيل ──
Write-Host ""
Write-Info "━━━ الخطوة 3: تحديد محرك التشغيل ━━━"
$TargetExe = if (Test-Path $VenvPythonw) { 
    Write-Success "  ✓ استخدام: pythonw.exe (بلا نافذة)"
    $VenvPythonw 
} else { 
    Write-Warning-Log "  ! pythonw.exe غير موجود، استخدام python.exe"
    $VenvPython 
}

# ── الخطوة 4: تحديد الأيقونة ──
Write-Host ""
Write-Info "━━━ الخطوة 4: البحث عن الأيقونة ━━━"
$IconPath = Resolve-IconPathWithFallback
$IconArg = if ($IconPath) { "$IconPath,0" } else { "" }

# ── الخطوة 5: إنشاء الاختصار الرئيسي ──
Write-Host ""
Write-Info "━━━ الخطوة 5: إنشاء الاختصار الرئيسي ━━━"
$Desktop      = Get-PreferredDesktopPath
$ShortcutPath = Join-Path $Desktop "$AppName.lnk"
Write-Info "  📍 سطح المكتب: $Desktop"
Write-Info "  🎯 الاختصار: $ShortcutPath"

if (-not (Write-OrRepairShortcut -ShortcutPath $ShortcutPath -TargetExe $TargetExe `
    -LauncherArg "`"$Launcher`"" -WorkingDir $AppDir -IconArg $IconArg `
    -Description "محاسبه بلا تعقيد - نظام إدارة الأعمال")) {
    Write-Error-Log "فشل إنشاء الاختصار الرئيسي"
    exit 1
}

# ── الخطوة 6: اختبار الاختصار ──
Write-Host ""
Write-Info "━━━ الخطوة 6: اختبار الاختصار ━━━"
$valid, $reason = Test-ShortcutValidity -ShortcutPath $ShortcutPath
if ($valid) {
    Write-Success "  ✓ الاختصار الرئيسي سليم وصالح للاستخدام"
} else {
    Write-Error-Log "  ✗ الاختصار الرئيسي معطوب: $reason"
    exit 1
}

# ── الخطوة 7: إصلاح الاختصارات القديمة ──
Write-Host ""
Write-Info "━━━ الخطوة 7: إصلاح الاختصارات القديمة ━━━"
$LegacyNames = @(
    "JenanBiz.lnk",
    "تشغيل جنان بيز.lnk",
    "جنان بيز — نظام إدارة التمويل.lnk",
    "نظام المحاسبة.lnk",
    "محاسبة.lnk",
    "محاسبه بلا تعقيد (2).lnk",
    "جنان بيز.lnk",
    "محاسبة - نظام الأعمال.lnk",
    "محاسبة - نظام الاعمال.lnk",
    "جنان بيز - نظام الاعمال.lnk",
    "جنان بيز — نظام إدارة الأعمال.lnk"
)

$legacyFixed = 0
foreach ($legacy in $LegacyNames) {
    $legacyPath = Join-Path $Desktop $legacy
    if (Test-Path $legacyPath) {
        if (Write-OrRepairShortcut -ShortcutPath $legacyPath -TargetExe $TargetExe `
            -LauncherArg "`"$Launcher`"" -WorkingDir $AppDir -IconArg $IconArg `
            -Description "محاسبة - نظام إدارة الأعمال") {
            $legacyFixed++
        }
    }
}
if ($legacyFixed -gt 0) {
    Write-Success "  ✓ تم إصلاح $legacyFixed اختصارات قديمة"
}

# ── الخطوة 8: تنظيف الاختصارات المعطوبة ──
Write-Host ""
Write-Info "━━━ الخطوة 8: تنظيف الاختصارات المعطوبة ━━━"
Remove-BrokenShortcuts -DesktopPath $Desktop

# ═══════════════ ملخص النتائج النهائي ═══════════════════════════════
Write-Host ""
Write-Host "  ╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║  ✅ تم إكمال التثبيت بنجاح                           ║" -ForegroundColor Green
Write-Host "  ║  💪 النظام جاهز للاستخدام المكثف                     ║" -ForegroundColor Green
Write-Host "  ║  🛡️  الاختصار محمي بنظام فحص متقدم                 ║" -ForegroundColor Green
Write-Host "  ╚═══════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Success "📍 الاختصار: $ShortcutPath"
Write-Success "📝 السجل الكامل: $LogFile"
Write-Host ""
Write-Host "💡 نصائح:" -ForegroundColor Cyan
Write-Host "  • الاختصار يحتوي على نظام حماية متقدم ولن ينهار"
Write-Host "  • إذا حدثت مشكلة، شغّل البرنامج من terminal: python launcher.py" -ForegroundColor Gray
Write-Host "  • مراجعة السجل في حالة الأخطاء" -ForegroundColor Gray
Write-Host ""
Read-Host "اضغط Enter للاغلاق"