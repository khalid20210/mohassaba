# install_shortcut.ps1 — يعمل على أي جهاز بلا تعديل
$ErrorActionPreference = 'Stop'
$AppDir    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$AppName   = "محاسبة - نظام الأعمال"
$Launcher  = Join-Path $AppDir "launcher.py"
$IconFile  = Join-Path $AppDir "static\icons\app_icon.ico"

Write-Host ""
Write-Host "  جنان بيز - تثبيت الاختصار" -ForegroundColor Cyan
Write-Host "  مجلد البرنامج: $AppDir" -ForegroundColor Gray
Write-Host ""

$VenvPythonw = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
$VenvPython  = Join-Path $AppDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "  [1] البيئة الافتراضية غير موجودة - جاري الانشاء..." -ForegroundColor Yellow
    $sysPy = $null
    foreach ($candidate in @("python", "python3", "py")) {
        try { $ver = & $candidate --version 2>&1; if ($ver -match "Python 3") { $sysPy = $candidate; break } } catch { }
    }
    if (-not $sysPy) {
        Write-Host "  خطأ: Python 3 غير مثبت على هذا الجهاز." -ForegroundColor Red
        Write-Host "  حمّل Python من: https://www.python.org/downloads/" -ForegroundColor Yellow
        Read-Host "  اضغط Enter للخروج"
        exit 1
    }
    Set-Location $AppDir
    & $sysPy -m venv ".venv"
    Write-Host "  [1] تم انشاء البيئة الافتراضية" -ForegroundColor Green
    Write-Host "  [2] تثبيت المتطلبات..." -ForegroundColor Yellow
    & $VenvPython -m pip install --upgrade pip --quiet
    if (Test-Path (Join-Path $AppDir "requirements.txt")) {
        & $VenvPython -m pip install -r (Join-Path $AppDir "requirements.txt") --quiet
    }
    Write-Host "  [2] تم تثبيت المتطلبات" -ForegroundColor Green
} else {
    Write-Host "  [1] البيئة الافتراضية موجودة" -ForegroundColor Green
}

$TargetExe = if (Test-Path $VenvPythonw) { $VenvPythonw } else { $VenvPython }
$IconArg = ""
if (Test-Path $IconFile) { $IconArg = "$IconFile,0" }

$WshShell     = New-Object -ComObject WScript.Shell
$Desktop      = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "$AppName.lnk"

$S = $WshShell.CreateShortcut($ShortcutPath)
$S.TargetPath       = $TargetExe
$S.Arguments        = "`"$Launcher`""
$S.WorkingDirectory = $AppDir
if ($IconArg) { $S.IconLocation = $IconArg }
$S.Description      = "محاسبة - نظام ادارة الاعمال"
$S.WindowStyle      = 1
$S.Save()

Write-Host ""
Write-Host "  تم انشاء الاختصار على سطح المكتب بنجاح!" -ForegroundColor Green
Write-Host "  المسار: $ShortcutPath" -ForegroundColor Cyan
Write-Host ""
Read-Host "  اضغط Enter للاغلاق"