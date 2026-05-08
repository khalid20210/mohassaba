"""
modules/observability.py
نظام مراقبة شامل: تسجيل، قياسات أداء، متتبع أخطاء
"""
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

from flask import g, request

# ── إعداد Logger موحد ──
def setup_logging(app, log_level: str = "INFO") -> logging.Logger:
    """إعداد نظام logging مركزي مع JSON output للإنتاج."""
    logger = logging.getLogger("jenan_biz")
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # ولا توجد handlers مسبقاً — سنضيف الخاصة بنا
    if logger.handlers:
        return logger
    
    # Handler: JSON للإنتاج، عادي للـ development
    from modules.config import IS_PROD
    
    if IS_PROD:
        handler = logging.StreamHandler()
        formatter = _JSONFormatter()
    else:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(levelname)-8s [%(name)s] %(message)s"
        )
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    app.logger = logger
    return logger


class _JSONFormatter(logging.Formatter):
    """Formatter يُخرج JSON logs مناسبة للإنتاج والمراقبة."""
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # أضف metadata من Flask g
        if hasattr(g, "request_id"):
            log_obj["request_id"] = g.request_id
        if hasattr(g, "business_id"):
            log_obj["business_id"] = g.business_id
        if hasattr(g, "user_id"):
            log_obj["user_id"] = g.user_id
        
        # معلومات الطلب
        if request:
            log_obj["http"] = {
                "method": request.method,
                "path": request.path,
                "ip": request.remote_addr,
                "user_agent": request.user_agent.string[:100] if request.user_agent else None,
            }
        
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_obj, ensure_ascii=False, default=str)


class PerformanceTracker:
    """تتبع أداء الطلبات والعمليات الحرجة."""
    
    def __init__(self):
        self.logger = logging.getLogger("jenan_biz.perf")
        self.thresholds = {
            "db_query": 500,       # ms
            "api_endpoint": 1000,  # ms
            "slow_operation": 2000, # ms
        }
    
    def track_db_query(self, query: str, duration_ms: float, 
                      params: tuple = None, result_count: int = 0):
        """تسجيل استعلام DB مع التنبيه للبطيئة."""
        is_slow = duration_ms > self.thresholds["db_query"]
        level = "WARNING" if is_slow else "DEBUG"
        
        self.logger.log(
            getattr(logging, level),
            f"DB_QUERY | {duration_ms:.1f}ms | rows={result_count}",
            extra={
                "query_first_80": query[:80],
                "duration_ms": duration_ms,
                "params_count": len(params or []),
                "result_count": result_count,
                "is_slow": is_slow,
            }
        )
    
    def track_endpoint(self, method: str, path: str, status: int, 
                      duration_ms: float, bytes_sent: int = 0):
        """تسجيل استدعاء API مع التنبيه للبطيئة."""
        is_slow = duration_ms > self.thresholds["api_endpoint"]
        level = "WARNING" if is_slow else "INFO"
        
        self.logger.log(
            getattr(logging, level),
            f"{method} {path} {status} | {duration_ms:.1f}ms",
            extra={
                "http_method": method,
                "http_path": path,
                "http_status": status,
                "duration_ms": duration_ms,
                "bytes_sent": bytes_sent,
                "is_slow": is_slow,
            }
        )
    
    def track_error(self, error_type: str, message: str, 
                   context: Optional[dict] = None):
        """تسجيل خطأ مع context كامل."""
        error_obj = {
            "error_type": error_type,
            "error_message": message,
        }
        if context:
            error_obj.update(context)
        
        self.logger.error(
            f"ERROR | {error_type}: {message}",
            extra=error_obj
        )


# سنسخة عامة
perf_tracker = PerformanceTracker()


class MetricsCollector:
    """جمع مؤشرات الأداء (Prometheus-style)."""
    
    def __init__(self):
        self.logger = logging.getLogger("jenan_biz.metrics")
        self.counters = {}
        self.histograms = {}
    
    def increment(self, metric_name: str, value: int = 1, tags: dict = None):
        """زيادة counter."""
        key = f"{metric_name}:{json.dumps(tags or {})}"
        self.counters[key] = self.counters.get(key, 0) + value
        
        if value > 0:
            self.logger.debug(
                f"COUNTER | {metric_name}={self.counters[key]}",
                extra={"metric": metric_name, "value": self.counters[key], "tags": tags}
            )
    
    def observe_histogram(self, metric_name: str, value: float, tags: dict = None):
        """تسجيل observation في histogram."""
        key = f"{metric_name}:{json.dumps(tags or {})}"
        if key not in self.histograms:
            self.histograms[key] = []
        self.histograms[key].append(value)
        
        self.logger.debug(
            f"HISTOGRAM | {metric_name}={value:.2f}",
            extra={"metric": metric_name, "value": value, "tags": tags}
        )
    
    def get_metrics_summary(self) -> dict:
        """ملخص المؤشرات الحالية (للـ /metrics endpoint)."""
        summary = {}
        for key, value in self.counters.items():
            summary[f"counter_{key}"] = value
        
        for key, values in self.histograms.items():
            if values:
                summary[f"histogram_{key}_avg"] = sum(values) / len(values)
                summary[f"histogram_{key}_max"] = max(values)
                summary[f"histogram_{key}_min"] = min(values)
        
        return summary


metrics = MetricsCollector()
