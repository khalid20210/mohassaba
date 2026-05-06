' مشغّل صامت لنظام المحاسبة - بدون نافذة CMD
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

APP_DIR = "C:\Users\JEN21\OneDrive\سطح المكتب\محاسبه"
PYTHON  = APP_DIR & "\.venv\Scripts\python.exe"
SCRIPT  = APP_DIR & "\run_production.py"
URL     = "http://127.0.0.1:5000"

' تشغيل الخادم بدون نافذة (0 = مخفي)
objShell.Run """" & PYTHON & """ """ & SCRIPT & """", 0, False

' انتظار 4 ثوانٍ
WScript.Sleep 4000

' فتح المتصفح
objShell.Run "cmd /c start """" """ & URL & """", 0, False
