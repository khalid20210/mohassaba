"""
launcher.py — مشغّل البرنامج لسطح المكتب
محاسبة - نظام إدارة الأعمال
"""
import os
import sys
import time
import socket
import threading
import webbrowser
import subprocess
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

# ─── تأكد من أن المسار الجذر صحيح ──────────────────────────────────────────
APP_DIR   = Path(__file__).parent.resolve()
VENV_PY   = APP_DIR / ".venv" / "Scripts" / "python.exe"
RUN_SCRIPT = APP_DIR / "run_production.py"
PORT      = 5001
URL       = f"http://localhost:{PORT}"
ICON_PATH = APP_DIR / "static" / "icons" / "app_icon.ico"
LOG_DIR   = APP_DIR / "logs"
LOG_FILE  = LOG_DIR / "desktop_launcher.log"


def is_port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def start_server() -> subprocess.Popen:
    """تشغيل خادم Flask في الخلفية"""
    env = os.environ.copy()
    env["PORT"] = str(PORT)
    env["HOST"] = "127.0.0.1"  # محلي فقط (أمان)
    env["WAITRESS_THREADS"] = "8"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    log_handle.write(f"\n\n=== launcher start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    log_handle.flush()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(
        [str(VENV_PY), str(RUN_SCRIPT)],
        cwd=str(APP_DIR),
        env=env,
        creationflags=creationflags,  # Windows — بلا نافذة سوداء
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    proc._log_handle = log_handle  # type: ignore[attr-defined]
    return proc


def _tail_log_lines(path: Path, max_lines: int = 20) -> str:
    try:
        if not path.exists():
            return "لا يوجد ملف سجل بعد."
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:]) if lines else "ملف السجل فارغ."
    except Exception:
        return "تعذر قراءة سجل التشغيل."


def wait_and_open(proc: subprocess.Popen, splash_root: tk.Tk):
    """انتظر الخادم ثم افتح المتصفح"""
    for attempt in range(40):  # حتى 20 ثانية
        if proc.poll() is not None:
            # الخادم انهار
            details = _tail_log_lines(LOG_FILE, 16)
            splash_root.after(0, lambda: messagebox.showerror(
                "خطأ",
                "فشل تشغيل الخادم!\n"
                f"راجع السجل:\n{LOG_FILE}\n\n"
                f"آخر رسائل:\n{details}"
            ))
            splash_root.after(0, splash_root.destroy)
            return

        if is_port_open(PORT):
            splash_root.after(0, splash_root.destroy)
            webbrowser.open(URL)
            return
        time.sleep(0.5)

    # انتهت المهلة
    splash_root.after(0, lambda: messagebox.showwarning(
        "تنبيه", f"البرنامج يستغرق وقتاً. سيُفتح المتصفح الآن.\n{URL}"
    ))
    splash_root.after(0, splash_root.destroy)
    webbrowser.open(URL)


def show_splash(proc: subprocess.Popen):
    """نافذة تحميل جميلة أثناء انتظار الخادم"""
    root = tk.Tk()
    root.title("محاسبة - نظام إدارة الأعمال")
    root.geometry("420x220")
    root.resizable(False, False)
    root.configure(bg="#0D1B2A")
    root.overrideredirect(True)  # بلا شريط عنوان
    root.attributes("-topmost", True)

    # تمركز النافذة
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x  = (sw - 420) // 2
    y  = (sh - 220) // 2
    root.geometry(f"420x220+{x}+{y}")

    # محتوى السبلاش
    frame = tk.Frame(root, bg="#0D1B2A")
    frame.pack(fill="both", expand=True, padx=2, pady=2)

    tk.Label(
        frame, text="محاسبة", font=("Arial", 28, "bold"),
        bg="#0D1B2A", fg="#4FA8E0"
    ).pack(pady=(30, 2))

    tk.Label(
        frame, text="نظام إدارة الأعمال",
        font=("Arial", 13), bg="#0D1B2A", fg="#A0C4E0"
    ).pack()

    status_var = tk.StringVar(value="جاري تشغيل الخادم ...")
    tk.Label(
        frame, textvariable=status_var,
        font=("Arial", 10), bg="#0D1B2A", fg="#6B8FAD"
    ).pack(pady=(20, 5))

    # شريط تقدم بسيط
    canvas = tk.Canvas(frame, width=300, height=6, bg="#1E3A52", highlightthickness=0)
    canvas.pack()
    bar = canvas.create_rectangle(0, 0, 0, 6, fill="#4FA8E0", outline="")

    anim_state = {"w": 0, "dir": 1}

    def animate():
        w = anim_state["w"] + anim_state["dir"] * 3
        if w >= 300: w = 300; anim_state["dir"] = -1
        if w <= 0:   w = 0;   anim_state["dir"] = 1
        anim_state["w"] = w
        canvas.coords(bar, 0, 0, w, 6)
        root.after(30, animate)

    animate()

    # تشغيل الانتظار في خيط منفصل
    t = threading.Thread(target=wait_and_open, args=(proc, root), daemon=True)
    t.start()

    root.mainloop()


def main():
    # هل الخادم يعمل مسبقاً؟
    if is_port_open(PORT):
        webbrowser.open(URL)
        return

    if not VENV_PY.exists():
        messagebox.showerror(
            "خطأ",
            f"لم يُعثر على بيئة Python:\n{VENV_PY}\n\nتأكد من تثبيت المتطلبات."
        )
        sys.exit(1)

    if not RUN_SCRIPT.exists():
        messagebox.showerror("خطأ", f"الملف غير موجود:\n{RUN_SCRIPT}")
        sys.exit(1)

    proc = start_server()
    show_splash(proc)


if __name__ == "__main__":
    main()
