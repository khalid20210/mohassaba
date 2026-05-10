' مشغّل صامت لنظام المحاسبة - بدون نافذة CMD
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

APP_DIR = objFSO.GetParentFolderName(WScript.ScriptFullName)
PYTHON  = APP_DIR & "\.venv\Scripts\python.exe"
SCRIPT  = APP_DIR & "\run_production.py"
URL     = "http://127.0.0.1:5001"

If Not objFSO.FileExists(PYTHON) Then
  MsgBox "Python executable not found:" & vbCrLf & PYTHON, 16, "Launch Error"
  WScript.Quit 1
End If

If Not objFSO.FileExists(SCRIPT) Then
  MsgBox "Run script not found:" & vbCrLf & SCRIPT, 16, "Launch Error"
  WScript.Quit 1
End If

' تشغيل الخادم بدون نافذة (0 = مخفي)
objShell.Run """" & PYTHON & """ """ & SCRIPT & """", 0, False

' انتظار 4 ثوانٍ
WScript.Sleep 4000

' فتح المتصفح
objShell.Run "cmd /c start """" """ & URL & """", 0, False
