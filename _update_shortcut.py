"""تحديث اختصار سطح المكتب بالأيقونة الجديدة"""
import os
import subprocess
from pathlib import Path

proj_path = Path(__file__).resolve().parent
ico_path = proj_path / "static" / "icons" / "app_icon.ico"
if not ico_path.exists():
    ico_path = proj_path / "app_icon.ico"
ps1_path = proj_path / "start_silent.ps1"

ico = str(ico_path)
ps1 = str(ps1_path)
proj = str(proj_path)

# نستخدم PowerShell مباشرة بدون ملف مؤقت
# نخزن المسارات في متغيرات بيئة مؤقتة لتجنب مشكلة الترميز
env = os.environ.copy()
env["_ICO"]  = ico
env["_PS1"]  = ps1
env["_PROJ"] = proj

script = (
    "$ws  = New-Object -ComObject WScript.Shell; "
    "$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '\u0646\u0638\u0627\u0645 \u0627\u0644\u0645\u062d\u0627\u0633\u0628\u0629.lnk'; "
    "$sc  = $ws.CreateShortcut($lnk); "
    "$sc.TargetPath = 'powershell.exe'; "
    "$sc.Arguments = \"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File '$env:_PS1'\"; "
    "$sc.WorkingDirectory = $env:_PROJ; "
    "$sc.IconLocation = \"$env:_ICO,0\"; "
    "$sc.WindowStyle = 7; "
    "$sc.Save(); "
    "Write-Host 'done'"
)

r = subprocess.run(
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
    capture_output=True, text=True, env=env
)
print(r.stdout.strip() or r.stderr[:300])
