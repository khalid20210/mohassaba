"""
launcher.py — مشغّل سطح المكتب (يدعم وضعين):
1) Launch mode: فتح الواجهة وتشغيل الخادم بالخلفية.
2) Serve mode (--serve): تشغيل الخادم فقط لاستخدامه من نسخة EXE مُثبتة.
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).parent.resolve()


APP_DIR = Path(__file__).parent.resolve()
BUNDLE_DIR = _bundle_dir()
APP_HOME = Path(os.environ.get("JENAN_APP_HOME", Path.home() / "AppData" / "Local" / "JenanBiz"))

PORT = int(os.environ.get("JENAN_PORT", "5001"))
HOST = os.environ.get("JENAN_HOST", "127.0.0.1")
URL = f"http://127.0.0.1:{PORT}"

VENV_PY = APP_DIR / ".venv" / "Scripts" / "python.exe"
RUN_SCRIPT = APP_DIR / "run_production.py"
DB_SOURCE = BUNDLE_DIR / "database" / "accounting_dev.db"
DB_TARGET = APP_HOME / "database" / "accounting_dev.db"


def is_port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _prepare_runtime_environment() -> None:
    """تهيئة مسارات قابلة للكتابة داخل AppData للنسخة المُثبتة."""
    (APP_HOME / "database").mkdir(parents=True, exist_ok=True)
    (APP_HOME / "uploads" / "excel").mkdir(parents=True, exist_ok=True)
    (APP_HOME / "instance" / "sessions").mkdir(parents=True, exist_ok=True)
    (APP_HOME / "static" / "logos").mkdir(parents=True, exist_ok=True)

    if not DB_TARGET.exists() and DB_SOURCE.exists():
        shutil.copy2(DB_SOURCE, DB_TARGET)

    os.environ.setdefault("FLASK_ENV", "production")
    os.environ.setdefault("HOST", HOST)
    os.environ.setdefault("PORT", str(PORT))
    os.environ.setdefault("WAITRESS_THREADS", "8")

    # override مسارات الكتابة للنسخة المُثبتة.
    os.environ.setdefault("DB_PATH", str(DB_TARGET))
    os.environ.setdefault("UPLOAD_FOLDER", str(APP_HOME / "uploads"))
    os.environ.setdefault("LOGO_FOLDER", str(APP_HOME / "static" / "logos"))
    os.environ.setdefault("SESSION_FILE_DIR", str(APP_HOME / "instance" / "sessions"))


def _serve_mode() -> None:
    """تشغيل الخادم فقط (يستدعى من نفس EXE عبر --serve)."""
    _prepare_runtime_environment()
    from run_production import main as run_server

    run_server()


def start_server() -> subprocess.Popen:
    """تشغيل الخادم في الخلفية (dev عبر venv، وinstalled عبر exe نفسه)."""
    env = os.environ.copy()
    env.setdefault("PORT", str(PORT))
    env.setdefault("HOST", HOST)
    env.setdefault("WAITRESS_THREADS", "8")

    if getattr(sys, "frozen", False):
        _prepare_runtime_environment()
        return subprocess.Popen(
            [sys.executable, "--serve"],
            cwd=str(APP_HOME),
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if not VENV_PY.exists() or not RUN_SCRIPT.exists():
        raise FileNotFoundError("Runtime files not found (.venv or run_production.py)")

    return subprocess.Popen(
        [str(VENV_PY), str(RUN_SCRIPT)],
        cwd=str(APP_DIR),
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_and_open(proc: subprocess.Popen, splash_root: tk.Tk) -> None:
    for _ in range(50):
        if proc.poll() is not None:
            splash_root.after(
                0,
                lambda: messagebox.showerror(
                    "خطأ",
                    "فشل تشغيل الخادم!\nتحقق من ملفات التطبيق وصلاحيات الكتابة.",
                ),
            )
            splash_root.after(0, splash_root.destroy)
            return

        if is_port_open(PORT):
            splash_root.after(0, splash_root.destroy)
            webbrowser.open(URL)
            return

        time.sleep(0.5)

    splash_root.after(
        0,
        lambda: messagebox.showwarning(
            "تنبيه",
            f"تشغيل الخادم أخذ وقتًا أطول من المتوقع.\nيمكنك فتح الرابط يدويًا:\n{URL}",
        ),
    )
    splash_root.after(0, splash_root.destroy)


def show_splash(proc: subprocess.Popen) -> None:
    root = tk.Tk()
    root.title("جنان بيز")
    root.geometry("420x220")
    root.resizable(False, False)
    root.configure(bg="#0D1B2A")
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - 420) // 2
    y = (sh - 220) // 2
    root.geometry(f"420x220+{x}+{y}")

    frame = tk.Frame(root, bg="#0D1B2A")
    frame.pack(fill="both", expand=True, padx=2, pady=2)

    tk.Label(frame, text="جنان بيز", font=("Arial", 28, "bold"), bg="#0D1B2A", fg="#4FA8E0").pack(pady=(30, 2))
    tk.Label(frame, text="نظام إدارة الأعمال", font=("Arial", 13), bg="#0D1B2A", fg="#A0C4E0").pack()

    tk.Label(frame, text="جاري تشغيل الخادم...", font=("Arial", 10), bg="#0D1B2A", fg="#6B8FAD").pack(pady=(20, 5))

    canvas = tk.Canvas(frame, width=300, height=6, bg="#1E3A52", highlightthickness=0)
    canvas.pack()
    bar = canvas.create_rectangle(0, 0, 0, 6, fill="#4FA8E0", outline="")
    anim_state = {"w": 0, "dir": 1}

    def animate() -> None:
        w = anim_state["w"] + anim_state["dir"] * 3
        if w >= 300:
            w = 300
            anim_state["dir"] = -1
        if w <= 0:
            w = 0
            anim_state["dir"] = 1
        anim_state["w"] = w
        canvas.coords(bar, 0, 0, w, 6)
        root.after(30, animate)

    animate()
    threading.Thread(target=wait_and_open, args=(proc, root), daemon=True).start()
    root.mainloop()


def main() -> None:
    if "--serve" in sys.argv:
        _serve_mode()
        return

    if is_port_open(PORT):
        webbrowser.open(URL)
        return

    try:
        proc = start_server()
    except Exception as exc:
        messagebox.showerror("خطأ", f"تعذر تشغيل الخادم:\n{exc}")
        raise SystemExit(1)

    show_splash(proc)


if __name__ == "__main__":
    main()
