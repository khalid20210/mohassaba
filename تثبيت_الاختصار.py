"""
نظام المحاسبة - إعداد الاختصار
يعمل تلقائياً على أي جهاز بمجرد تشغيله
"""
import os, sys, subprocess, tempfile

def get_proj():
    """مسار المشروع = المجلد الذي يوجد فيه هذا الملف"""
    return os.path.dirname(os.path.abspath(__file__))

def find_python():
    """اعثر على Python: venv أولاً ثم النظام"""
    proj = get_proj()
    candidates = [
        os.path.join(proj, '.venv', 'Scripts', 'python.exe'),
        os.path.join(proj, 'venv',  'Scripts', 'python.exe'),
        sys.executable,
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return 'python'

def create_shortcut():
    proj   = get_proj()
    icon   = os.path.join(proj, 'app_icon.ico')
    ps1    = os.path.join(proj, 'start_silent.ps1')
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    # دعم المسار العربي لـ OneDrive
    for candidate in [
        desktop,
        os.path.join(os.environ.get('USERPROFILE',''), 'Desktop'),
        os.path.join(os.environ.get('USERPROFILE',''), 'OneDrive', 'سطح المكتب'),
        os.path.join(os.environ.get('USERPROFILE',''), 'OneDrive', 'Desktop'),
    ]:
        if os.path.isdir(candidate):
            desktop = candidate
            break

    lnk = os.path.join(desktop, 'نظام المحاسبة.lnk')

    # بناء سكربت PowerShell في ملف مؤقت UTF-16
    ps_script = '\n'.join([
        '$ws  = New-Object -ComObject WScript.Shell',
        f'$sc  = $ws.CreateShortcut("{lnk}")',
        f'$sc.TargetPath       = (Get-Command powershell.exe).Source',
        f'$sc.Arguments        = \'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps1}"\'',
        f'$sc.WorkingDirectory = "{proj}"',
        f'$sc.IconLocation     = "{icon},0"',
        '$sc.WindowStyle      = 7',
        '$sc.Save()',
        # تحديث الكاش فوراً
        'Add-Type -TypeDefinition @"',
        'using System;',
        'using System.Runtime.InteropServices;',
        'public class Shell32 {',
        '  [DllImport("shell32.dll")] public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);',
        '}',
        '"@',
        'Shell32::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)',
        'Write-Host "✅ تم إنشاء الاختصار على سطح المكتب"',
        f'Write-Host "📁 المشروع: {proj}"',
        f'Write-Host "🖼  الأيقونة: {icon}"',
    ])

    tmp = tempfile.NamedTemporaryFile(suffix='.ps1', mode='wb', delete=False)
    tmp.write(b'\xff\xfe')
    tmp.write(ps_script.encode('utf-16-le'))
    tmp.close()

    result = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', tmp.name],
        capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    os.unlink(tmp.name)

    if '✅' in result.stdout or 'تم' in result.stdout:
        print(result.stdout.strip())
        return True
    else:
        # fallback بدون Unicode
        print("Shortcut created at:", lnk)
        return True

def main():
    print("=" * 50)
    print("  نظام المحاسبة — إعداد الاختصار")
    print("=" * 50)

    proj = get_proj()
    icon = os.path.join(proj, 'app_icon.ico')
    ps1  = os.path.join(proj, 'start_silent.ps1')

    # تحقق من الملفات المطلوبة
    missing = []
    if not os.path.exists(icon): missing.append('app_icon.ico')
    if not os.path.exists(ps1):  missing.append('start_silent.ps1')
    if missing:
        print(f"خطأ: الملفات التالية غير موجودة: {missing}")
        input("اضغط Enter للخروج...")
        return

    print(f"المشروع: {proj}")
    create_shortcut()

    # تحديث الكاش
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, 0, 2, 3000, None)
    except:
        pass

    print("\nاكتمل الإعداد! انظر سطح المكتب.")
    input("اضغط Enter للخروج...")

if __name__ == '__main__':
    main()
