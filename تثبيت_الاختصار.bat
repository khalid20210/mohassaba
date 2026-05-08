@echo off
chcp 65001 > nul
title نظام المحاسبة - تثبيت الاختصار

echo ================================================
echo   نظام المحاسبة -- انشاء اختصار سطح المكتب
echo ================================================
echo.

cd /d "%~dp0"

REM البحث عن Python
set PYTHON=
if exist ".venv\Scripts\python.exe" set PYTHON=.venv\Scripts\python.exe
if exist "venv\Scripts\python.exe"  set PYTHON=venv\Scripts\python.exe
if "%PYTHON%"=="" where python >nul 2>&1 && set PYTHON=python

if "%PYTHON%"=="" (
    echo خطأ: Python غير موجود. يرجى تثبيت Python أولاً.
    pause
    exit /b 1
)

echo Python: %PYTHON%
echo.
"%PYTHON%" تثبيت_الاختصار.py
