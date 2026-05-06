$desktop  = [Environment]::GetFolderPath('Desktop')
$lnk      = Join-Path $desktop 'نظام المحاسبة.lnk'
$proj     = 'c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه'
$ps1      = Join-Path $proj 'start_silent.ps1'
$ico      = Join-Path $proj 'app_icon.ico'

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath       = 'powershell.exe'
$sc.Arguments        = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1`""
$sc.WorkingDirectory = $proj
$sc.IconLocation     = "$ico,0"
$sc.WindowStyle      = 7
$sc.Description      = 'نظام المحاسبة'
$sc.Save()

Write-Host "✅ تم تحديث أيقونة الاختصار على سطح المكتب"
