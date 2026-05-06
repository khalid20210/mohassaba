$AppDir     = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PythonExe  = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
$Launcher   = Join-Path $AppDir "launcher.py"
$IconFile   = Join-Path $AppDir "static\iconspp_icon.ico"
$AppName    = "Jenan Biz"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Error: Python not found: $PythonExe" -ForegroundColor Red
    exit 1
}

$WshShell     = New-Object -ComObject WScript.Shell
$Desktop      = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "$AppName.lnk"

$S = $WshShell.CreateShortcut($ShortcutPath)
$S.TargetPath       = $PythonExe
$S.Arguments        = "`"$Launcher`""
$S.WorkingDirectory = $AppDir
$S.IconLocation     = "$IconFile,0"
$S.Description      = "Jenan Biz - Business Management System"
$S.WindowStyle      = 1
$S.Save()

Write-Host ""
Write-Host "OK: Desktop shortcut installed!" -ForegroundColor Green
Write-Host "Path: $ShortcutPath" -ForegroundColor Cyan
