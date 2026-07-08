' مشغّل صامت لجنان بيز — بدون نافذة CMD
' يستخدم launcher.py لتجربة احترافية مع splash screen
Option Explicit

Dim objShell, objFSO, APP_DIR, PYTHON, LAUNCHER, PORT, URL

Set objShell = CreateObject("WScript.Shell")
Set objFSO   = CreateObject("Scripting.FileSystemObject")

' استخراج مجلد هذا الملف تلقائياً (يعمل من أي مكان)
APP_DIR  = objFSO.GetParentFolderName(WScript.ScriptFullName)
PYTHON   = APP_DIR & "\.venv\Scripts\pythonw.exe"
LAUNCHER = APP_DIR & "\launcher.py"
PORT     = "5001"
URL      = "http://127.0.0.1:" & PORT

' التحقق من وجود Python
If Not objFSO.FileExists(PYTHON) Then
    MsgBox "خطأ: لم يتم العثور على Python." & vbCrLf & _
           "المسار المتوقع: " & PYTHON & vbCrLf & vbCrLf & _
           "تأكد من تثبيت البيئة الافتراضية (.venv)", _
           vbCritical, "جنان بيز"
    WScript.Quit 1
End If

' إذا كان الخادم يعمل بالفعل — افتح المتصفح مباشرة
Dim oHTTP
On Error Resume Next
Set oHTTP = CreateObject("MSXML2.XMLHTTP")
oHTTP.open "GET", "http://127.0.0.1:" & PORT & "/healthz", False
oHTTP.send
If oHTTP.status = 200 Then
    objShell.Run "cmd /c start """" """ & URL & """", 0, False
    WScript.Quit 0
End If
On Error GoTo 0

' تشغيل launcher.py (مع splash screen تلقائي)
objShell.Run """" & PYTHON & """ """ & LAUNCHER & """", 0, False
