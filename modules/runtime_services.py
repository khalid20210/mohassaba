"""
modules/runtime_services.py
خدمات تشغيلية اختيارية لرفع الصلابة: Redis Sessions, Distributed Rate Limit, RQ Queue.
تعمل بشكل اختياري مع fallback آمن عندما لا تكون الخدمات متاحة.
"""
import os
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

from modules.config import (
    REDIS_URL,
    SESSION_BACKEND,
    SESSION_FILE_DIR,
    SESSION_REDIS_PREFIX,
    USE_REDIS_RATE_LIMIT,
    RATE_LIMIT_PREFIX,
    RATE_LIMIT_WINDOW_SEC,
    RATE_LIMIT_MAX_REQUEST,
    QUEUE_BACKEND,
    RQ_DEFAULT_QUEUE,
    REDIS_REQUIRED,
    QUEUE_REQUIRED,
)

_redis_client = None
_redis_error = ""
_rq_error = ""
_redis_session_client = None  # client بدون decode_responses لـ Flask-Session (pickle-safe)


def get_redis_client():
    """
    Redis client للعمليات النصية: rate limit, locks, health, queue.
    decode_responses=True ← يقرأ كـ string مباشرة.
    لا تستخدمه لتخزين بيانات ثنائية (pickle).
    """
    global _redis_client, _redis_error

    if _redis_client is not None:
        return _redis_client

    if not REDIS_URL:
        _redis_error = "REDIS_URL not configured"
        return None

    try:
        import redis
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        return _redis_client
    except Exception as exc:
        _redis_error = str(exc)
        return None


def get_redis_session_client():
    """
    Redis client خاص بـ Flask-Session (بدون decode_responses).
    Flask-Session تخزن بيانات الجلسة بصيغة pickle (binary).
    decode_responses=True يكسر القراءة ← يجب أن يكون False هنا.
    """
    global _redis_session_client

    if _redis_session_client is not None:
        return _redis_session_client

    if not REDIS_URL:
        return None

    try:
        import redis
        # decode_responses=False (الافتراضي) ← آمن مع pickle
        _redis_session_client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
        return _redis_session_client
    except Exception:
        return None


def get_redis_error() -> str:
    return _redis_error


def get_queue_error() -> str:
    return _rq_error


def setup_runtime_services(app) -> dict:
    """تهيئة session backend وتهيئة المجلدات المطلوبة."""
    status = {
        "session_backend": SESSION_BACKEND,
        "session": "filesystem",
        "redis": "disabled",
        "queue": "disabled",
    }

    # Session backend
    if SESSION_BACKEND == "redis":
        # استخدام session client (بدون decode_responses) لأن Flask-Session تخزن pickle
        session_redis = get_redis_session_client()
        if session_redis is not None:
            try:
                from flask_session import Session

                app.config["SESSION_TYPE"] = "redis"
                app.config["SESSION_REDIS"] = session_redis  # pickle-safe client
                app.config["SESSION_KEY_PREFIX"] = SESSION_REDIS_PREFIX
                app.config["SESSION_USE_SIGNER"] = True
                app.config["SESSION_PERMANENT"] = True
                Session(app)
                status["session"] = "redis"
            except Exception:
                _configure_filesystem_session(app)
                status["session"] = "filesystem_fallback"
        else:
            _configure_filesystem_session(app)
            status["session"] = "filesystem_fallback"
    else:
        _configure_filesystem_session(app)
        status["session"] = "filesystem"

    # Redis health
    redis_client = get_redis_client()
    if redis_client is not None:
        try:
            redis_client.ping()
            status["redis"] = "ok"
        except Exception as exc:
            status["redis"] = f"error: {exc}"
    else:
        status["redis"] = "disabled" if not REDIS_URL else f"error: {get_redis_error()}"

    # Queue readiness
    status["queue"] = queue_health_status()

    app.logger.info(
        "runtime services | session=%s redis=%s queue=%s",
        status["session"],
        status["redis"],
        status["queue"],
    )
    return status


def _configure_filesystem_session(app) -> None:
    """Fallback session storage (محلي)."""
    session_dir = Path(SESSION_FILE_DIR)
    session_dir.mkdir(parents=True, exist_ok=True)

    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = str(session_dir)
    app.config["SESSION_FILE_THRESHOLD"] = 10000
    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_PERMANENT"] = True

    try:
        from flask_session import Session

        Session(app)
    except Exception:
        # إذا Flask-Session غير مثبتة نترك Flask الافتراضي
        pass


def check_rate_limit_distributed(identity_key: str) -> Tuple[bool, int, str]:
    """
    Rate limiting موزع باستخدام Redis fixed-window.
    returns: (allowed, current_count, backend)
    """
    redis_client = get_redis_client()
    if redis_client is None:
        return True, 0, "local-fallback"

    now_bucket = int(time.time() // RATE_LIMIT_WINDOW_SEC)
    key = f"{RATE_LIMIT_PREFIX}:{identity_key}:{now_bucket}"

    try:
        count = int(redis_client.incr(key))
        if count == 1:
            redis_client.expire(key, RATE_LIMIT_WINDOW_SEC + 2)
        allowed = count <= RATE_LIMIT_MAX_REQUEST
        return allowed, count, "redis"
    except Exception:
        return True, 0, "local-fallback"


def should_use_distributed_rate_limit() -> bool:
    return USE_REDIS_RATE_LIMIT and bool(REDIS_URL)


def queue_health_status() -> str:
    """فحص جاهزية queue backend configured."""
    global _rq_error

    if QUEUE_BACKEND != "rq":
        return "disabled"

    redis_client = get_redis_client()
    if redis_client is None:
        return "error: redis unavailable"

    try:
        from rq import Queue

        q = Queue(RQ_DEFAULT_QUEUE, connection=redis_client)
        q.count
        return "ok"
    except Exception as exc:
        _rq_error = str(exc)
        return f"error: {exc}"


def enqueue_background_task(task_path: str, *args, **kwargs):
    """
    إدراج مهمة خلفية:
    - إذا QUEUE_BACKEND=rq: يرسل المهمة إلى RQ
    - غير ذلك: يعيد None (queue غير مفعلة)
    """
    if QUEUE_BACKEND != "rq":
        return None

    redis_client = get_redis_client()
    if redis_client is None:
        return None

    try:
        from rq import Queue

        q = Queue(RQ_DEFAULT_QUEUE, connection=redis_client)
        return q.enqueue(task_path, *args, **kwargs)
    except Exception:
        return None


def validate_runtime_requirements() -> tuple[bool, list[str]]:
    """تحقق من المتطلبات الحرجة قبل تشغيل الإنتاج (اختياري)."""
    errors: list[str] = []

    redis_status = "ok" if get_redis_client() is not None else "disabled"
    queue_status = queue_health_status()

    if REDIS_REQUIRED and redis_status != "ok":
        errors.append("REDIS_REQUIRED=true لكن Redis غير متاح")

    if QUEUE_REQUIRED and queue_status != "ok":
        errors.append(f"QUEUE_REQUIRED=true لكن queue status={queue_status}")

    return (len(errors) == 0, errors)


# ─── Per-business distributed write lock (لمنع تزاحم الكتابة على SQLite) ──────

_BIZ_LOCK_PREFIX = "jenan:biz_write_lock:"

# Fallback in-process locks عندما Redis غير متاح
# مفتاح = biz_id، قيمة = threading.Lock
_in_process_locks: dict[int, threading.Lock] = {}
_in_process_locks_meta: dict[int, dict] = {}   # token → thread holding it
_in_process_registry_lock = threading.Lock()   # يحمي عمليات قراءة/كتابة الـ dict نفسه


def _get_in_process_lock(biz_id: int) -> threading.Lock:
    """إنشاء أو جلب threading.Lock خاص بمنشأة."""
    with _in_process_registry_lock:
        if biz_id not in _in_process_locks:
            _in_process_locks[biz_id] = threading.Lock()
        return _in_process_locks[biz_id]


def acquire_business_lock(
    biz_id: int,
    timeout_ms: int = 5000,
    ttl_ms: int = 15000,
) -> Optional[str]:
    """
    محاولة الحصول على lock خاص بشركة واحدة لحماية عمليات الكتابة المتزامنة.

    - كل شركة لها lock مستقل ← كاشيري شركتين مختلفتين لا ينتظرون بعضهم أبداً.
    - يعيد token (str) عند النجاح، أو None عند انتهاء timeout.
    - إذا Redis متاح: يستخدم Redis distributed lock.
    - إذا Redis غير متاح: يستخدم threading.Lock in-process (مناسب لـ single process).
    """
    redis_client = get_redis_client()

    if redis_client is not None:
        # ── مسار Redis ────────────────────────────────────────────────────────
        import uuid
        token = uuid.uuid4().hex
        key = f"{_BIZ_LOCK_PREFIX}{biz_id}"
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            try:
                acquired = redis_client.set(key, token, px=ttl_ms, nx=True)
                if acquired:
                    return token
            except Exception:
                break  # Redis فشل → انتقل لـ in-process
            time.sleep(0.005)  # 5ms polling
        return None

    # ── Fallback: in-process threading.Lock ─────────────────────────────────
    import uuid
    lock = _get_in_process_lock(biz_id)
    timeout_sec = timeout_ms / 1000.0
    acquired = lock.acquire(blocking=True, timeout=timeout_sec)
    if acquired:
        token = uuid.uuid4().hex
        return f"inproc:{token}"
    return None  # انتهى timeout


def release_business_lock(biz_id: int, token: str) -> None:
    """
    تحرير lock الشركة إذا كان token المعطى هو نفس المخزن (atomic check-and-delete).
    يمنع حذف lock شركة أخرى بالخطأ.
    """
    if not token:
        return

    # ── Fallback in-process ───────────────────────────────────────────────────
    if token.startswith("inproc:"):
        lock = _get_in_process_lock(biz_id)
        try:
            lock.release()
        except RuntimeError:
            pass  # تجاهل إذا لم يكن محجوزاً
        return

    if token == "no-redis":
        return

    redis_client = get_redis_client()
    if redis_client is None:
        return

    key = f"{_BIZ_LOCK_PREFIX}{biz_id}"
    try:
        lua_script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        redis_client.eval(lua_script, 1, key, token)
    except Exception:
        pass
