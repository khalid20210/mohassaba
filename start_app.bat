@echo off
chcp 65001 >nul
title نظام المحاسبة

SET APP_DIR=%~dp0
IF "%APP_DIR:~-1%"=="\" SET APP_DIR=%APP_DIR:~0,-1%
SET PYTHON=%APP_DIR%\.venv\Scripts\python.exe
SET SCRIPT=%APP_DIR%\run_production.py

cd /d "%APP_DIR%"

echo.
echo  ============================================
echo   نظام المحاسبة - جاري تشغيل الخادم...
echo  ============================================
echo.

REM تشغيل الخادم في الخلفية
start "" /B "%PYTHON%" "%SCRIPT%"

REM انتظار 4 ثوان لبدء الخادم
timeout /t 4 /nobreak >nul

REM فتح المتصفح
start "" "http://127.0.0.1:5001"

echo   تم تشغيل النظام بنجاح.
echo   الرابط: http://127.0.0.1:5001
echo.
echo   اضغط اي مفتاح لايقاف الخادم وإغلاق البرنامج.
pause >nul

REM إيقاف العملية عند الإغلاق
taskkill /F /IM python.exe /T >nul 2>&1
echo   تم ايقاف الخادم.
