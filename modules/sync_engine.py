# -*- coding: utf-8 -*-
"""
modules/sync_engine.py
═══════════════════════════════════════════════════════════════════
محرك المزامنة اللامتزامن — Async Sync Engine
يُعالج سيناريو "إعصار المزامنة": 70,000 طلب في دقيقة واحدة

المبدأ:
  1. قَبول فوري (202 Accepted) — لا blocking
  2. وضع الطلبات في طابور SQLite
  3. Worker thread واحد يعالج الطابور بشكل تسلسلي لكل منشأة
  4. كشف تضارب المخزون وحله بمنطق "آخر كاتب ينبه"

هيكل الجداول الجديدة:
  • offline_sync_queue  — طابور الطلبات المعلقة
  • sync_conflicts      — سجل تضاربات المخزون
═══════════════════════════════════════════════════════════════════
"""
import json
import logging
import sqlite3
import threading
import time
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
from typing import Optional

from modules.config import DB_PATH, SQLITE_BUSY_TIMEOUT_MS
from modules.extensions import get_account_id, next_entry_number, next_invoice_number

logger = logging.getLogger(__name__)

Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")


def _d(v) -> Decimal:
    return Decimal(str(v or 0))

# ─── إعدادات الطابور ───────────────────────────────────────────────────────
MAX_ITEMS_PER_BATCH  = 100     # أقصى عدد عناصر في طلب واحد
WORKER_SLEEP_SEC     = 0.3     # فترة استراحة الـ Worker بين الدورات
WORKER_BATCH_SIZE    = 50      # عدد العناصر التي يعالجها الـ Worker في كل دورة
MAX_RETRY            = 3       # أقصى عدد محاولات إعادة لكل عنصر فاشل

# ─── Rate Limiting في الذاكرة (Token Bucket — بدون Redis) ─────────────────
# هيكل: { business_id: {"tokens": float, "last_refill": float} }
_rl_buckets: dict = {}
_rl_lock = threading.Lock()

BUCKET_CAPACITY  = 10    # أقصى رصيد للـ token
BUCKET_REFILL_PS = 2.0   # refill rate: 2 token/ثانية (120 batch/دقيقة لكل منشأة)


def _check_rate_limit(key) -> bool:
    """
    Token Bucket per-key (business_id أو أي مفتاح فريد).
    يعيد True إذا كان مسموحاً، False إذا تجاوز الحد.
    """
    now = time.monotonic()
    with _rl_lock:
        bucket = _rl_buckets.get(key)
        if bucket is None:
            _rl_buckets[key] = {"tokens": BUCKET_CAPACITY - 1, "last_refill": now}
            return True
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(BUCKET_CAPACITY, bucket["tokens"] + elapsed * BUCKET_REFILL_PS)
        bucket["last_refill"] = now
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False


# ─── اتصال مباشر بـ SQLite (خارج Flask g — للـ Worker) ───────────────────
def _raw_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(
        DB_PATH,
        timeout=max(1, SQLITE_BUSY_TIMEOUT_MS // 1000),
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


# ─── إنشاء الجداول ──────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS offline_sync_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    agent_id        INTEGER,
    local_id        TEXT,
    action_type     TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    conflict_detail TEXT,
    priority        INTEGER DEFAULT 0,
    retry_count     INTEGER DEFAULT 0,
    error_msg       TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    processed_at    TEXT,
    UNIQUE(business_id, agent_id, local_id)
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    queue_id        INTEGER,
    product_id      INTEGER,
    requested_qty   REAL,
    available_qty   REAL,
    shortage_qty    REAL,
    resolution      TEXT,
    resolved_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_osq_status_biz
    ON offline_sync_queue(status, business_id, id);
CREATE INDEX IF NOT EXISTS idx_osq_local
    ON offline_sync_queue(business_id, agent_id, local_id);
"""


def init_sync_tables(conn: Optional[sqlite3.Connection] = None):
    """يُنشئ الجداول عند الحاجة — آمن للاستدعاء المتكرر"""
    close_after = conn is None
    if conn is None:
        conn = _raw_conn()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        if close_after:
            conn.close()


# ─── قَبول الطلب (Fast Accept) ──────────────────────────────────────────────
def enqueue_batch(
    db: sqlite3.Connection,
    business_id: int,
    agent_id: int,
    items: list,
    rate_limit_key=None,
) -> dict:
    """
    يقبل قائمة العناصر فوراً، يضعها في offline_sync_queue.
    rate_limit_key: مفتاح منفصل لـ rate-limit (اختياري).
                   مفيد في الاختبارات لمحاكاة 1400 عميل مختلف.
    يعيد:
      { "accepted": N, "rejected_dup": M, "queue_tip": last_id }
    """
    rl_key = rate_limit_key if rate_limit_key is not None else business_id
    if not _check_rate_limit(rl_key):
        return {"error": "rate_limit", "retry_after": 30}

    items = items[:MAX_ITEMS_PER_BATCH]
    accepted = 0
    rejected_dup = 0

    for item in items:
        local_id    = item.get("local_id") or item.get("id")
        action_type = item.get("action_type", "")
        payload     = json.dumps(item.get("payload", item), ensure_ascii=False)

        try:
            db.execute(
                """INSERT INTO offline_sync_queue
                   (business_id, agent_id, local_id, action_type, payload_json, status)
                   VALUES (?, ?, ?, ?, ?, 'pending')""",
                (business_id, agent_id, local_id, action_type, payload),
            )
            accepted += 1
        except sqlite3.IntegrityError:
            # تضاعف local_id — فاتورة مُرسلة مسبقاً (idempotent)
            rejected_dup += 1

    db.commit()
    last_row = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {
        "accepted":     accepted,
        "rejected_dup": rejected_dup,
        "queue_tip":    last_row,
    }


def get_queue_status(db: sqlite3.Connection, business_id: int, agent_id: int) -> dict:
    """حالة الطابور للمنشأة/المندوب"""
    row = db.execute(
        """SELECT
               SUM(CASE WHEN status='pending'    THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) AS processing,
               SUM(CASE WHEN status='done'       THEN 1 ELSE 0 END) AS done,
               SUM(CASE WHEN status='failed'     THEN 1 ELSE 0 END) AS failed,
               SUM(CASE WHEN status='conflict'   THEN 1 ELSE 0 END) AS conflicts
           FROM offline_sync_queue
           WHERE business_id = ? AND agent_id = ?""",
        (business_id, agent_id),
    ).fetchone()

    conflicts = db.execute(
        """SELECT sc.product_id, sc.requested_qty, sc.available_qty,
                  sc.shortage_qty, sc.resolution, sc.resolved_at
           FROM sync_conflicts sc
           JOIN offline_sync_queue q ON q.id = sc.queue_id
           WHERE q.business_id = ? AND q.agent_id = ?
           ORDER BY sc.id DESC LIMIT 10""",
        (business_id, agent_id),
    ).fetchall()

    return {
        "pending":     row["pending"]     or 0,
        "processing":  row["processing"]  or 0,
        "done":        row["done"]        or 0,
        "failed":      row["failed"]      or 0,
        "conflicts":   row["conflicts"]   or 0,
        "conflict_details": [dict(c) for c in conflicts],
    }


# ═══════════════════════════════════════════════════════════════════════════
# معالج العنصر الواحد (نفس منطق agent_sync القديم + كشف التضارب)
# ═══════════════════════════════════════════════════════════════════════════

def _process_item(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    """
    يعالج عنصراً واحداً من الطابور.
    يعيد: 'done' | 'conflict' | 'failed'
    """
    queue_id    = row["id"]
    biz_id      = row["business_id"]
    agent_id    = row["agent_id"]
    action      = row["action_type"]
    payload     = json.loads(row["payload_json"])

    # normalize payload: إذا كان العنصر مُخزناً كاملاً (من batch)
    p = payload.get("payload", payload)

    try:
        if action == "create_invoice":
            return _handle_create_invoice(conn, queue_id, biz_id, agent_id, p)

        elif action == "log_visit":
            conn.execute(
                """INSERT OR IGNORE INTO agent_visits
                   (business_id, agent_id, contact_id, client_profile_id,
                    visit_type, outcome, notes, rejection_reason, lat, lng)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (biz_id, agent_id,
                 p.get("contact_id"), p.get("client_profile_id"),
                 p.get("visit_type", "visit"), p.get("outcome", "neutral"),
                 (p.get("notes") or "").strip() or None,
                 (p.get("rejection_reason") or "").strip() or None,
                 p.get("lat"), p.get("lng")),
            )

        elif action == "collect_payment":
            amt = float(p.get("amount", 0))
            if amt <= 0:
                raise ValueError("مبلغ التحصيل غير صالح")
            conn.execute(
                """INSERT OR IGNORE INTO agent_collections
                   (business_id, agent_id, contact_id, invoice_id,
                    amount, payment_method, notes, collected_at, confirmed)
                   VALUES (?,?,?,?,?,?,?,datetime('now'),0)""",
                (biz_id, agent_id,
                 p.get("contact_id"), p.get("invoice_id"),
                 amt, p.get("payment_method", "cash"),
                 (p.get("notes") or "").strip() or None),
            )

        elif action == "checkin":
            today = datetime.now().strftime("%Y-%m-%d")
            conn.execute(
                """INSERT OR IGNORE INTO agent_attendance
                   (business_id, agent_id, work_date, checkin_at, checkin_lat, checkin_lng)
                   VALUES (?,?,?,datetime('now'),?,?)""",
                (biz_id, agent_id, today, p.get("lat"), p.get("lng")),
            )

        elif action == "checkout":
            rec = conn.execute(
                "SELECT id, checkin_at FROM agent_attendance WHERE agent_id=? AND work_date=date('now')",
                (agent_id,),
            ).fetchone()
            if rec:
                ci    = datetime.fromisoformat(rec["checkin_at"].replace("Z", ""))
                hours = round((datetime.now() - ci).total_seconds() / 3600, 2)
                conn.execute(
                    """UPDATE agent_attendance
                       SET checkout_at=datetime('now'), checkout_lat=?, checkout_lng=?, total_hours=?
                       WHERE id=?""",
                    (p.get("lat"), p.get("lng"), hours, rec["id"]),
                )

        elif action == "log_location":
            conn.execute(
                """INSERT INTO agent_locations
                   (business_id, agent_id, latitude, longitude, accuracy, battery, recorded_at)
                   VALUES (?,?,?,?,?,?,datetime('now'))""",
                (biz_id, agent_id,
                 p.get("lat"), p.get("lng"),
                 p.get("accuracy"), p.get("battery")),
            )

        elif action == "add_client":
            conn.execute(
                """INSERT OR IGNORE INTO agent_client_profiles
                   (business_id, agent_id, company_name, manager_name,
                    phone, region, address, notes, lat, lng, is_active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                (biz_id, agent_id,
                 (p.get("company_name") or "").strip(),
                 (p.get("manager_name") or "").strip() or None,
                 (p.get("phone") or "").strip() or None,
                 (p.get("region") or "").strip() or None,
                 (p.get("address") or "").strip() or None,
                 (p.get("notes") or "").strip() or None,
                 p.get("lat") or None,
                 p.get("lng") or None),
            )

        elif action == "draft_order":
            conn.execute(
                """INSERT OR IGNORE INTO agent_draft_orders
                   (business_id, agent_id, contact_id, client_name,
                    items_json, total, notes, status)
                   VALUES (?,?,?,?,?,?,?,'pending')""",
                (biz_id, agent_id,
                 p.get("contact_id"),
                 (p.get("client_name") or "").strip() or None,
                 json.dumps(p.get("items", []), ensure_ascii=False),
                 float(p.get("total", 0)),
                 (p.get("notes") or "").strip() or None),
            )

        else:
            raise ValueError(f"action غير معروف: {action!r}")

        return "done"

    except Exception as exc:
        raise exc


def _handle_create_invoice(
    conn: sqlite3.Connection,
    queue_id: int,
    biz_id: int,
    agent_id: int,
    p: dict,
) -> str:
    """
    معالجة فاتورة مع كشف تضارب المخزون.
    إستراتيجية الحل: "نفّذ مع الإنذار" — لا نوقف البيع، نسجّل النقص.
    """
    items = p.get("items", [])
    if not items:
        raise ValueError("لا توجد أصناف في الفاتورة")

    # حافظ على نفس عداد INV الرسمي (ICV chain) بدل ترقيم AGT-SYNC المنفصل.
    inv_num = next_invoice_number(conn, biz_id)

    tax_row = conn.execute(
        "SELECT rate FROM tax_settings WHERE business_id=? AND is_active=1 ORDER BY id LIMIT 1",
        (biz_id,),
    ).fetchone()
    tax_rate = _d(tax_row["rate"] if tax_row else 0)

    subtotal = Decimal("0")
    for i in items:
        qty = _d(i.get("qty", 1))
        price = _d(i.get("unit_price", 0))
        subtotal += (qty * price).quantize(Q4, rounding=ROUND_HALF_UP)
    subtotal_2 = subtotal.quantize(Q2, rounding=ROUND_HALF_UP)
    tax_amount = (subtotal_2 * tax_rate / Decimal("100")).quantize(Q2, rounding=ROUND_HALF_UP)
    grand = (subtotal_2 + tax_amount).quantize(Q2, rounding=ROUND_HALF_UP)

    # ── فحص تضارب المخزون قبل الكتابة ──────────────────────────────────
    conflicts_found = []
    for i in items:
        pid = i.get("product_id")
        qty = float(_d(i.get("qty", 1)))
        if not pid:
            continue
        stock_row = conn.execute(
            "SELECT COALESCE(quantity, 0) AS qty FROM stock WHERE product_id=? AND business_id=?",
            (pid, biz_id),
        ).fetchone()
        available = float(stock_row["qty"]) if stock_row else 0.0
        if available < qty:
            conflicts_found.append({
                "product_id":   pid,
                "requested":    qty,
                "available":    available,
                "shortage":     round(qty - available, 4),
            })

    # ── إنشاء الفاتورة (حتى مع تضارب — نفّذ مع الإنذار) ─────────────
    conn.execute(
        """INSERT INTO invoices
           (business_id, invoice_number, invoice_date, due_date, status,
            party_id, notes, subtotal, tax_amount, total, invoice_type)
           VALUES (?,?,date('now'),date('now','+30 days'),'unpaid',?,?,?,?,?,'sale')""",
        (biz_id, inv_num,
         p.get("contact_id") or None,
         ((p.get("client_name") or "") + " — أوفلاين").strip(" —") or None,
         float(subtotal_2), float(tax_amount), float(grand)),
    )
    inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    cogs_total = Decimal("0")

    for i in items:
        qty_d = _d(i.get("qty", 1))
        price_d = _d(i.get("unit_price", 0))
        qty = float(qty_d)
        price = float(price_d)

        line_sub = (qty_d * price_d).quantize(Q4, rounding=ROUND_HALF_UP)
        line_tax = (line_sub * tax_rate / Decimal("100")).quantize(Q4, rounding=ROUND_HALF_UP)
        line_total = (line_sub + line_tax).quantize(Q4, rounding=ROUND_HALF_UP)

        conn.execute(
            """INSERT INTO invoice_lines
               (invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_amount, total)
               VALUES (?,?,?,?,?,?,?,?)""",
            (inv_id, i.get("product_id"),
             (i.get("description") or "").strip() or None,
             qty, price, float(tax_rate), float(line_tax), float(line_total)),
        )

        if i.get("product_id"):
            prod = conn.execute(
                "SELECT COALESCE(purchase_price,0) AS purchase_price FROM products WHERE id=? AND business_id=?",
                (i["product_id"], biz_id),
            ).fetchone()
            purchase_price = _d(prod["purchase_price"] if prod else 0)
            cogs_total += (qty_d * purchase_price).quantize(Q4, rounding=ROUND_HALF_UP)

            # خفض المخزون — MAX(0,...) يمنع السالب لكننا نسجل النقص
            conn.execute(
                """UPDATE stock
                   SET quantity = MAX(0, quantity - ?)
                   WHERE product_id=? AND business_id=?""",
                (qty, i["product_id"], biz_id),
            )
            conn.execute(
                """INSERT INTO inventory_movements
                   (business_id, product_id, movement_type, quantity,
                    reference_type, reference_id, reason)
                   VALUES (?,?,'sale',?,?,?,?)""",
                (biz_id, i["product_id"], qty, "invoice", inv_id,
                 f"مزامنة أوفلاين — مندوب #{agent_id}"),
            )

    # قيود يومية المبيعات + COGS داخل sync لمنع فساد القيد المزدوج.
    recv_acc_id = get_account_id(conn, biz_id, "1201")
    sales_acc_id = get_account_id(conn, biz_id, "4101")
    tax_acc_id = get_account_id(conn, biz_id, "2102")
    cogs_acc_id = get_account_id(conn, biz_id, "5101")
    inv_acc_id = get_account_id(conn, biz_id, "1104")

    if recv_acc_id and sales_acc_id:
        je_sale_num = next_entry_number(conn, biz_id)
        conn.execute(
            """INSERT INTO journal_entries
               (business_id, entry_number, entry_date, description,
                reference_type, reference_id, total_debit, total_credit, is_posted, created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_sale_num, datetime.now().strftime("%Y-%m-%d"),
             f"قيد مبيعات مزامنة — فاتورة {inv_num}",
             "invoice", inv_id, float(grand), float(grand), agent_id),
        )
        je_sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_sale_id, recv_acc_id, "ذمم مدينة — مبيعات مزامنة", float(grand), 0, 1),
        )
        conn.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_sale_id, sales_acc_id, f"إيراد مبيعات — {inv_num}", 0, float(subtotal_2), 2),
        )
        if tax_acc_id and tax_amount > 0:
            conn.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_sale_id, tax_acc_id, "ضريبة القيمة المضافة", 0, float(tax_amount), 3),
            )

        conn.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (je_sale_id, inv_id))
    else:
        logger.warning("[SyncWorker] تخطى قيد المبيعات — حسابات أساسية غير موجودة")

    cogs_total_2 = cogs_total.quantize(Q2, rounding=ROUND_HALF_UP)
    if cogs_total_2 > 0 and cogs_acc_id and inv_acc_id:
        je_cogs_num = next_entry_number(conn, biz_id)
        conn.execute(
            """INSERT INTO journal_entries
               (business_id, entry_number, entry_date, description,
                reference_type, reference_id, total_debit, total_credit, is_posted, created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_cogs_num, datetime.now().strftime("%Y-%m-%d"),
             f"قيد تكلفة البضاعة المباعة — {inv_num}",
             "invoice", inv_id, float(cogs_total_2), float(cogs_total_2), agent_id),
        )
        je_cogs_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_cogs_id, cogs_acc_id, "تكلفة البضاعة المباعة", float(cogs_total_2), 0, 1),
        )
        conn.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_cogs_id, inv_acc_id, "إقفال مخزون مباع", 0, float(cogs_total_2), 2),
        )

    # عمولة المندوب
    ag = conn.execute(
        "SELECT commission_rate FROM agents WHERE id=? AND business_id=?",
        (agent_id, biz_id),
    ).fetchone()
    if ag and float(ag["commission_rate"] or 0) > 0:
        rate = float(ag["commission_rate"])
        comm = round(float(grand) * rate / 100, 2)
        conn.execute(
            """INSERT OR IGNORE INTO agent_commissions
               (business_id, agent_id, invoice_id, invoice_total,
                commission_rate, commission_amount, status)
               VALUES (?,?,?,?,?,?,'pending')""",
            (biz_id, agent_id, inv_id, float(grand), rate, comm),
        )

    conn.execute(
        "INSERT OR IGNORE INTO agent_invoice_links (business_id, agent_id, invoice_id) VALUES (?,?,?)",
        (biz_id, agent_id, inv_id),
    )

    # ── تسجيل التضاربات ────────────────────────────────────────────────
    if conflicts_found:
        for cf in conflicts_found:
            conn.execute(
                """INSERT INTO sync_conflicts
                   (business_id, queue_id, product_id, requested_qty,
                    available_qty, shortage_qty, resolution)
                   VALUES (?,?,?,?,?,?,'executed_with_shortage')""",
                (biz_id, queue_id,
                 cf["product_id"], cf["requested"],
                 cf["available"], cf["shortage"]),
            )
        return "conflict"   # فاتورة أُنشئت لكن فيها نقص مخزون

    return "done"


# ═══════════════════════════════════════════════════════════════════════════
# Worker Thread — معالج الطابور في الخلفية
# ═══════════════════════════════════════════════════════════════════════════

_worker_started = False
_worker_lock    = threading.Lock()


def _worker_loop():
    """
    حلقة الـ Worker اللانهائية:
    - تجلب WORKER_BATCH_SIZE عنصر في كل دورة
    - تعالجهم واحداً واحداً
    - تنام WORKER_SLEEP_SEC ثم تكرر
    """
    conn = None
    logger.info("[SyncWorker] بدأ تشغيل الـ Worker 🟢")
    while True:
        try:
            if conn is None:
                conn = _raw_conn()

            # جلب العناصر المعلقة مرتبة حسب الأولوية ثم الـ ID
            rows = conn.execute(
                """SELECT * FROM offline_sync_queue
                   WHERE status = 'pending' AND retry_count < ?
                   ORDER BY priority DESC, id ASC
                   LIMIT ?""",
                (MAX_RETRY, WORKER_BATCH_SIZE),
            ).fetchall()

            if not rows:
                time.sleep(WORKER_SLEEP_SEC)
                continue

            for row in rows:
                qid = row["id"]
                # تأشير "جارٍ المعالجة" لمنع التكرار
                conn.execute(
                    "UPDATE offline_sync_queue SET status='processing' WHERE id=?",
                    (qid,),
                )
                conn.commit()

                try:
                    conn.execute("BEGIN IMMEDIATE")
                    result = _process_item(conn, row)
                    conn.execute(
                        """UPDATE offline_sync_queue
                           SET status=?, processed_at=datetime('now'), error_msg=NULL
                           WHERE id=?""",
                        (result, qid),
                    )
                    conn.execute("COMMIT")
                except Exception as exc:
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    retry = (row["retry_count"] or 0) + 1
                    new_status = "failed" if retry >= MAX_RETRY else "pending"
                    try:
                        conn.execute(
                            """UPDATE offline_sync_queue
                               SET status=?, retry_count=?, error_msg=?,
                                   processed_at=datetime('now')
                               WHERE id=?""",
                            (new_status, retry, str(exc)[:500], qid),
                        )
                        conn.commit()
                    except Exception:
                        conn = None  # أعد فتح الاتصال في الدورة التالية
                        break

        except Exception as outer_exc:
            logger.error(f"[SyncWorker] خطأ في حلقة الـ Worker: {outer_exc}")
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            conn = None
            time.sleep(2)


def start_worker():
    """
    يبدأ الـ Worker thread مرة واحدة فقط (singleton).
    يُستدعى عند تهيئة التطبيق.
    """
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        init_sync_tables()
        t = threading.Thread(target=_worker_loop, name="SyncWorker", daemon=True)
        t.start()
        _worker_started = True
        logger.info("[SyncWorker] Thread مُشغَّل ✅")
