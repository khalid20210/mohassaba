"""
modules/request_tracking.py
تتبع الطلبات الكامل: timing، logging، error handling
"""
import time
from typing import Optional

from flask import g, request, jsonify


def track_request_start():
    """بدء تتبع الطلب - يُستدعى قبل معالجة الطلب."""
    g.request_start_time = time.time()
    g.request_bytes_sent = 0


def track_request_end(response):
    """إنهاء تتبع الطلب - يُستدعى بعد معالجة الطلب."""
    from modules.observability import perf_tracker, metrics
    
    if not hasattr(g, "request_start_time"):
        return response
    
    elapsed_ms = (time.time() - g.request_start_time) * 1000
    status_code = response.status_code if hasattr(response, "status_code") else 200
    try:
        bytes_sent = len(response.get_data()) if hasattr(response, "get_data") else 0
    except RuntimeError:
        bytes_sent = response.content_length or 0
    
    # تسجيل الأداء
    perf_tracker.track_endpoint(
        request.method,
        request.path,
        status_code,
        elapsed_ms,
        bytes_sent
    )
    
    # تحديث المؤشرات
    metrics.increment(
        "http_requests_total",
        tags={"method": request.method, "status": status_code}
    )
    metrics.observe_histogram(
        "http_request_duration_ms",
        elapsed_ms,
        tags={"path": request.path[:50], "method": request.method}
    )
    
    # إضافة headers مفيدة
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    
    return response


def handle_request_error(error: Exception):
    """معالجة أخطاء الطلبات الموحدة."""
    from modules.observability import perf_tracker, metrics
    
    status_code = 500
    error_type = type(error).__name__
    
    # معالجة أنواع أخطاء معروفة
    if isinstance(error, ValueError):
        status_code = 400
        error_type = "validation_error"
    elif isinstance(error, KeyError):
        status_code = 400
        error_type = "missing_field"
    elif isinstance(error, PermissionError):
        status_code = 403
        error_type = "permission_denied"
    
    # تسجيل الخطأ
    perf_tracker.track_error(
        error_type,
        str(error),
        {
            "path": request.path,
            "method": request.method,
            "status_code": status_code,
        }
    )
    
    # زيادة عداد الأخطاء
    metrics.increment("errors_total", tags={"type": error_type, "status": status_code})
    
    return jsonify({
        "success": False,
        "error": error_type,
        "message": str(error),
        "request_id": getattr(g, "request_id", "unknown"),
    }), status_code
