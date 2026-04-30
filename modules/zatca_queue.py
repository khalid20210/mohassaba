"""
modules/zatca_queue.py — طابور مزامنة ZATCA عند انقطاع الاتصال

المنطق:
  - عند إنشاء فاتورة → تُضاف تلقائياً للطابور (status='pending')
  - عند نجاح الإرسال → تتحوّل لـ 'sent'
  - عند الفشل → تُزاد retry_count وتُجدوَل للمحاولة التالية
  - Retry exponential backoff: 5s, 30s, 5m, 30m, 2h, max 24h

لا يحتاج Redis أو Celery — يعمل بـ SQLite + background thread.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

_log = logging.getLogger(__name__)

# ── ثوابت ─────────────────────────────────────────────────────────────────────
_RETRY_DELAYS = [5, 30, 300, 1800, 7200, 86400]   # ثواني: 5s 30s 5m 30m 2h 24h
_MAX_RETRIES  = len(_RETRY_DELAYS)
_WORKER_SLEEP = 30   # ثانية بين دورات الـ worker

# ── Migration SQL ──────────────────────────────────────────────────────────────
ZATCA_QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS zatca_queue (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id    INTEGER NOT NULL,
    invoice_id     INTEGER NOT NULL,
    invoice_number TEXT    NOT NULL,
    payload_json   TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'pending',  -- pending|sent|failed|skipped
    retry_count    INTEGER NOT NULL DEFAULT 0,
    next_retry_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    last_error     TEXT,
    sent_at        TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_zatca_queue_status
    ON zatca_queue(status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_zatca_queue_business
    ON zatca_queue(business_id, status);
"""


# ── إنشاء الجداول عند بدء التطبيق ────────────────────────────────────────────

def init_zatca_queue(db):
    """يُستدعى مرة واحدة عند init_app لإنشاء جدول الطابور"""
    for stmt in ZATCA_QUEUE_SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            db.execute(stmt)
    db.commit()
    _log.info("ZATCA queue table initialized")


# ── إضافة فاتورة للطابور ───────────────────────────────────────────────────────

def enqueue_invoice(db, business_id: int, invoice_id: int,
                    invoice_number: str, payload: dict) -> int:
    """
    يُضيف فاتورة لطابور ZATCA.
    يُعيد id السطر في الجدول.
    """
    payload_json = json.dumps(payload, ensure_ascii=False)
    db.execute(
        """INSERT INTO zatca_queue
           (business_id, invoice_id, invoice_number, payload_json,
            status, retry_count, next_retry_at)
           VALUES (?, ?, ?, ?, 'pending', 0, datetime('now'))""",
        (business_id, invoice_id, invoice_number, payload_json)
    )
    row_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    _log.info(f"Enqueued invoice {invoice_number} (queue_id={row_id})")
    return row_id


# ── المعالج الفعلي لإرسال ZATCA ───────────────────────────────────────────────

def _send_to_zatca(business_id: int, payload: dict) -> bool:
    """
    يُحاول إرسال الفاتورة لـ ZATCA.
    يُعيد True عند النجاح، False عند الفشل.

    حالياً: Stub — يُسجّل فقط.
    في الإنتاج: استبدل بـ ZATCA Fatoora API call.
    """
    try:
        # TODO: استبدل هذا الـ stub بـ ZATCA API الفعلي
        # import requests
        # r = requests.post(ZATCA_API_URL, json=payload, timeout=10,
        #                   headers={"Authorization": f"Bearer {get_token(business_id)}"})
        # return r.status_code == 200
        _log.info(f"[ZATCA-STUB] Would send invoice {payload.get('invoice_number')} "
                  f"for business {business_id}")
        return True   # stub دائماً ينجح
    except Exception as e:
        _log.error(f"ZATCA send error: {e}")
        return False


# ── Worker: يعمل في background thread ─────────────────────────────────────────

class ZATCAWorker:
    """
    Worker خفيف يعمل في خيط منفصل ويعيد إرسال الطوابير المعلّقة.
    يبدأ مرة واحدة مع التطبيق عبر start().
    """

    _instance: Optional["ZATCAWorker"] = None
    _lock = threading.Lock()

    def __init__(self, app):
        self._app     = app
        self._stop    = threading.Event()
        self._thread  = threading.Thread(
            target=self._run, name="zatca-worker", daemon=True
        )

    @classmethod
    def start(cls, app) -> "ZATCAWorker":
        with cls._lock:
            if cls._instance and cls._instance._thread.is_alive():
                return cls._instance
            cls._instance = cls(app)
            cls._instance._thread.start()
            _log.info("ZATCA worker thread started")
            return cls._instance

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._process_pending()
            except Exception as e:
                _log.error(f"ZATCA worker error: {e}")
            self._stop.wait(timeout=_WORKER_SLEEP)

    def _process_pending(self):
        with self._app.app_context():
            from .extensions import get_db
            db  = get_db()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            pending = db.execute(
                """SELECT id, business_id, invoice_id, invoice_number,
                          payload_json, retry_count
                   FROM zatca_queue
                   WHERE status='pending' AND next_retry_at <= ?
                   ORDER BY created_at ASC LIMIT 50""",
                (now,)
            ).fetchall()

            for row in pending:
                queue_id    = row["id"]
                retry_count = row["retry_count"]
                payload     = json.loads(row["payload_json"])

                success = _send_to_zatca(row["business_id"], payload)

                if success:
                    db.execute(
                        "UPDATE zatca_queue SET status='sent', sent_at=?, last_error=NULL WHERE id=?",
                        (now, queue_id)
                    )
                    _log.info(f"ZATCA sent: invoice {row['invoice_number']} (queue_id={queue_id})")
                else:
                    new_retry = retry_count + 1
                    if new_retry >= _MAX_RETRIES:
                        db.execute(
                            "UPDATE zatca_queue SET status='failed', retry_count=?, last_error=? WHERE id=?",
                            (new_retry, "استنفدت محاولات الإعادة", queue_id)
                        )
                        _log.error(f"ZATCA failed permanently: queue_id={queue_id}")
                    else:
                        delay      = _RETRY_DELAYS[new_retry]
                        next_retry = (datetime.now() + timedelta(seconds=delay)
                                      ).strftime("%Y-%m-%d %H:%M:%S")
                        db.execute(
                            """UPDATE zatca_queue
                               SET retry_count=?, next_retry_at=?, last_error=?
                               WHERE id=?""",
                            (new_retry, next_retry,
                             f"محاولة {new_retry} فشلت", queue_id)
                        )
                        _log.warning(f"ZATCA retry {new_retry}/{_MAX_RETRIES} "
                                     f"for queue_id={queue_id} in {delay}s")

                db.commit()


# ── دوال مساعدة للـ dashboard ─────────────────────────────────────────────────

def get_queue_stats(db, business_id: int) -> dict:
    """إحصائيات الطابور لـ dashboard المنشأة"""
    rows = db.execute(
        """SELECT status, COUNT(*) as cnt
           FROM zatca_queue
           WHERE business_id=?
           GROUP BY status""",
        (business_id,)
    ).fetchall()
    stats = {"pending": 0, "sent": 0, "failed": 0, "skipped": 0}
    for r in rows:
        stats[r["status"]] = r["cnt"]
    return stats


def retry_failed(db, business_id: int) -> int:
    """إعادة جدولة الفواتير الفاشلة — تُستخدم من dashboard"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """UPDATE zatca_queue
           SET status='pending', retry_count=0, next_retry_at=?, last_error=NULL
           WHERE business_id=? AND status='failed'""",
        (now, business_id)
    )
    db.commit()
    return db.execute(
        "SELECT changes()"
    ).fetchone()[0]
