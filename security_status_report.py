import logging
from datetime import datetime
from pathlib import Path


LOG_FILE = Path(__file__).with_name("jenan_security_audit.log")


_logger = logging.getLogger("jenan.security.audit")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    _logger.addHandler(file_handler)
    _logger.propagate = False


def report_status(operation_name: str, status: str, details: str = "") -> str:
    """يرفع تقريرًا فوريًا في التيرمينال وفي ملف السجل."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_line = (
        f"[{timestamp}] | العملية: {operation_name} | الحالة: {status} | تفاصيل: {details}"
    )
    try:
        print(report_line)
    except UnicodeEncodeError:
        safe_line = report_line.encode("cp1256", errors="replace").decode("cp1256")
        print(safe_line)
    _logger.info(report_line)
    return report_line