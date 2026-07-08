"""
build_portable.py - بناء نسخة محمولة من جنان بيز
ينشئ: dist\JenanBiz-Portable-<version>.zip
"""
import os, sys, shutil, zipfile
from pathlib import Path

VERSION  = "1.0.2"
APP_DIR  = Path(__file__).parent.resolve()
DIST_DIR = APP_DIR / "dist" / "portable"

# الملفات التي يتم تضمينها في النسخة المحمولة
INCLUDE = [
    "launcher.py",
    "run_production.py",
    "app.py",
    "modules",
    "templates",
    "static",
    "migrations",
    "database/schema.sql",
    "database/accounting_prod.db",
    "app_icon.ico",
    "requirements.txt",
    ".env.example",
    "install_shortcut.ps1",
    "start_silent.vbs",
    "share_demo.ps1",
]

EXCLUDE_PATTERNS = [
    "__pycache__", ".pyc", ".pyo",
    "accounting_dev.db", ".git",
    "node_modules", ".venv",
]

def should_exclude(path: Path) -> bool:
    for pat in EXCLUDE_PATTERNS:
        if pat in str(path):
            return True
    return False


def copy_into(src: Path, dst: Path):
    """نسخ ملف أو مجلد (مع استبعاد غير المرغوب)."""
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    elif src.is_dir():
        for item in src.rglob("*"):
            if should_exclude(item):
                continue
            rel = item.relative_to(src)
            target = dst / rel
            if item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)


def build_portable():
    print(f"بناء النسخة المحمولة {VERSION}...")

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    # نسخ الملفات
    for inc in INCLUDE:
        src = APP_DIR / inc
        dst = DIST_DIR / inc
        if src.exists():
            copy_into(src, dst)
            print(f"  ✓ {inc}")
        else:
            print(f"  - تجاهل (غير موجود): {inc}")

    # إنشاء سكريبت التشغيل الأول
    setup_bat = DIST_DIR / "تشغيل_أول_مرة.bat"
    setup_bat.write_text(
        '@echo off\r\nchcp 65001 > nul\r\n'
        'echo ================================================\r\n'
        'echo   جنان بيز - الإعداد الأول\r\n'
        'echo ================================================\r\n'
        'echo.\r\n'
        'cd /d "%~dp0"\r\n'
        'python -m venv .venv\r\n'
        '.venv\\Scripts\\python.exe -m pip install -r requirements.txt -q\r\n'
        'copy .env.example .env\r\n'
        'echo FLASK_ENV=production >> .env\r\n'
        'echo DEBUG=false >> .env\r\n'
        '.venv\\Scripts\\python.exe install_shortcut.ps1 2>nul\r\n'
        'powershell -ExecutionPolicy Bypass -File install_shortcut.ps1\r\n'
        'echo.\r\n'
        'echo تم الإعداد! يمكنك الآن تشغيل البرنامج من الأيقونة\r\n'
        'pause\r\n',
        encoding="utf-8"
    )
    print("  ✓ تشغيل_أول_مرة.bat")

    # إنشاء ملف README
    readme = DIST_DIR / "اقرأني.txt"
    readme.write_text(
        "جنان بيز - نظام إدارة الأعمال\r\n"
        "==============================\r\n\r\n"
        "للتشغيل أول مرة:\r\n"
        "1. شغّل ملف: تشغيل_أول_مرة.bat\r\n"
        "2. انتظر اكتمال التثبيت\r\n"
        "3. انقر مزدوجاً على الأيقونة في سطح المكتب\r\n\r\n"
        "للتشغيل العادي:\r\n"
        "- انقر مزدوجاً على أيقونة سطح المكتب\r\n\r\n"
        "الرابط المحلي: http://127.0.0.1:5001\r\n\r\n"
        "للمشاركة مع الآخرين:\r\n"
        "- شغّل: share_demo.ps1\r\n"
        "- ستحصل على رابط عام مؤقت\r\n",
        encoding="utf-8"
    )
    print("  ✓ اقرأني.txt")

    # ضغط كل شيء في ZIP
    zip_path = APP_DIR / "dist" / f"JenanBiz-Portable-{VERSION}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in DIST_DIR.rglob("*"):
            if file.is_file() and not should_exclude(file):
                arc_name = f"JenanBiz-{VERSION}/{file.relative_to(DIST_DIR)}"
                zf.write(file, arc_name)

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"\n✅ تم بناء النسخة المحمولة:")
    print(f"   {zip_path}")
    print(f"   الحجم: {size_mb:.1f} MB")
    return zip_path


if __name__ == "__main__":
    path = build_portable()
    print(f"\nأرسل هذا الملف لأي شخص:")
    print(f"  {path}")
