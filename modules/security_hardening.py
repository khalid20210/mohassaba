"""
modules/security_hardening.py
طبقة أقفال أمنية للميدان + الأوفلاين + المزامنة.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any


def ensure_security_tables(db) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_clock_anchor (
            business_id INTEGER NOT NULL,
            agent_id INTEGER NOT NULL,
            last_server_ts TEXT NOT NULL,
            last_device_ts TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (business_id, agent_id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            agent_id INTEGER,
            incident_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'medium',
            payload_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS client_verification (
            business_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 0,
            gps_verified INTEGER NOT NULL DEFAULT 0,
            tax_verified INTEGER NOT NULL DEFAULT 0,
            first_payment_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (business_id, contact_id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_custody_daily (
            business_id INTEGER NOT NULL,
            agent_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            opened_at TEXT,
            closed_at TEXT,
            backup_hash TEXT,
            stock_settled INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            PRIMARY KEY (business_id, agent_id, work_date)
        )
        """
    )


def register_security_incident(
    db,
    business_id: int,
    incident_type: str,
    payload: dict[str, Any] | None = None,
    severity: str = "medium",
    agent_id: int | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO security_incidents (business_id, agent_id, incident_type, severity, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            business_id,
            agent_id,
            incident_type,
            severity,
            json.dumps(payload or {}, ensure_ascii=False),
        ),
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def enforce_secure_local_timestamp(
    db,
    business_id: int,
    agent_id: int,
    device_ts: str | None,
    max_back_minutes: int = 5,
) -> tuple[bool, str]:
    """
    يمنع timestamp spoofing: لا يسمح بتاريخ جهاز أقدم كثيراً من آخر مرساة سيرفر.
    """
    ensure_security_tables(db)

    now = datetime.utcnow()
    row = db.execute(
        "SELECT last_server_ts FROM security_clock_anchor WHERE business_id=? AND agent_id=?",
        (business_id, agent_id),
    ).fetchone()

    device_dt = _parse_dt(device_ts)
    if row:
        anchor_dt = _parse_dt(row["last_server_ts"])
        if anchor_dt and device_dt:
            min_allowed = anchor_dt - timedelta(minutes=max_back_minutes)
            if device_dt < min_allowed:
                return False, "رفض الطلب: ختم الوقت المحلي متراجع بشكل غير آمن"

    db.execute(
        """
        INSERT INTO security_clock_anchor (business_id, agent_id, last_server_ts, last_device_ts, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(business_id, agent_id)
        DO UPDATE SET last_server_ts=excluded.last_server_ts,
                      last_device_ts=excluded.last_device_ts,
                      updated_at=datetime('now')
        """,
        (
            business_id,
            agent_id,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            (device_dt.strftime("%Y-%m-%d %H:%M:%S") if device_dt else None),
        ),
    )
    return True, "ok"


def detect_mock_location(payload: dict[str, Any] | None) -> tuple[bool, str]:
    payload = payload or {}
    mock_flags = [
        payload.get("is_mock_location"),
        payload.get("mock_location"),
        payload.get("gps_mocked"),
    ]
    if any(v in (True, 1, "1", "true", "yes") for v in mock_flags):
        return True, "تم اكتشاف Mock Location"

    provider = str(payload.get("location_provider") or "").lower()
    if provider in {"mock", "fake", "simulated"}:
        return True, "مزود الموقع غير موثوق"

    acc = payload.get("accuracy")
    try:
        if acc is not None and float(acc) > 5000:
            return True, "دقة الموقع متدنية بشكل مريب"
    except Exception:
        pass

    return False, "ok"


def mark_custody_open(db, business_id: int, agent_id: int, work_date: str) -> None:
    ensure_security_tables(db)
    db.execute(
        """
        INSERT INTO agent_custody_daily (business_id, agent_id, work_date, opened_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(business_id, agent_id, work_date)
        DO UPDATE SET opened_at=COALESCE(agent_custody_daily.opened_at, datetime('now'))
        """,
        (business_id, agent_id, work_date),
    )


def mark_custody_close(
    db,
    business_id: int,
    agent_id: int,
    work_date: str,
    backup_hash: str | None = None,
    notes: str | None = None,
) -> None:
    ensure_security_tables(db)
    db.execute(
        """
        INSERT INTO agent_custody_daily (business_id, agent_id, work_date, closed_at, backup_hash, stock_settled, notes)
        VALUES (?, ?, ?, datetime('now'), ?, 1, ?)
        ON CONFLICT(business_id, agent_id, work_date)
        DO UPDATE SET closed_at=datetime('now'),
                      backup_hash=excluded.backup_hash,
                      stock_settled=1,
                      notes=COALESCE(excluded.notes, agent_custody_daily.notes)
        """,
        (business_id, agent_id, work_date, backup_hash, notes),
    )


def require_open_custody_for_sales(db, business_id: int, agent_id: int, work_date: str) -> tuple[bool, str]:
    ensure_security_tables(db)
    row = db.execute(
        """
        SELECT opened_at FROM agent_custody_daily
        WHERE business_id=? AND agent_id=? AND work_date=?
        """,
        (business_id, agent_id, work_date),
    ).fetchone()
    if not row or not row["opened_at"]:
        return False, "لا يمكن البيع قبل Check-in عهدة اليوم"
    return True, "ok"


def resolve_commission_status_for_invoice(
    db,
    business_id: int,
    contact_id: int | None,
    payment_method: str,
    invoice_status: str,
) -> tuple[str, str]:
    """
    منع ثغرة العملاء الوهميين + البيع الآجل:
    لا تُصرف عمولة الآجل، ولا عمولة عميل غير متحقق.
    """
    pm = (payment_method or "").strip().lower()
    st = (invoice_status or "").strip().lower()

    if pm in {"credit", "ajal"} or st in {"unpaid", "pending", "draft", "partial"}:
        return "hold", "عمولة معلقة: بيع آجل"

    if not contact_id:
        return "hold", "عمولة معلقة: عميل غير معرف"

    ensure_security_tables(db)
    vr = db.execute(
        """
        SELECT is_verified, first_payment_at FROM client_verification
        WHERE business_id=? AND contact_id=?
        """,
        (business_id, contact_id),
    ).fetchone()
    if not vr or int(vr["is_verified"] or 0) != 1 or not vr["first_payment_at"]:
        return "hold", "عمولة معلقة: العميل غير موثق/أول دفعة غير مثبتة"

    return "pending", "ok"


def mark_first_payment_verified(db, business_id: int, contact_id: int) -> None:
    ensure_security_tables(db)
    db.execute(
        """
        INSERT INTO client_verification (business_id, contact_id, is_verified, gps_verified, tax_verified, first_payment_at, updated_at)
        VALUES (?, ?, 1, 1, 1, datetime('now'), datetime('now'))
        ON CONFLICT(business_id, contact_id)
        DO UPDATE SET is_verified=1,
                      first_payment_at=COALESCE(client_verification.first_payment_at, datetime('now')),
                      updated_at=datetime('now')
        """,
        (business_id, contact_id),
    )


def enforce_invoice_item_integrity(items: list[dict[str, Any]]) -> tuple[bool, str]:
    for idx, item in enumerate(items, start=1):
        try:
            qty = float(item.get("qty", 1))
            price = float(item.get("price", item.get("unit_price", 0)))
        except Exception:
            return False, f"بيانات الصنف #{idx} غير صالحة"

        if qty <= 0:
            return False, f"كمية غير صالحة في الصنف #{idx}"
        if price <= 0:
            return False, f"سعر غير صالح (صفر/سالب) في الصنف #{idx}"

        try:
            dp = float(item.get("discount_pct", 0) or 0)
            if dp > 60:
                return False, f"خصم غير منطقي في الصنف #{idx}"
        except Exception:
            pass

    return True, "ok"


def enforce_credit_limit(
    db,
    business_id: int,
    contact_id: int | None,
    invoice_total: float,
    payment_method: str,
) -> tuple[bool, str]:
    if not contact_id:
        return True, "ok"

    pm = (payment_method or "").strip().lower()
    if pm not in {"credit", "ajal"}:
        return True, "ok"

    try:
        c = db.execute(
            "SELECT credit_limit FROM contacts WHERE id=? AND business_id=? LIMIT 1",
            (contact_id, business_id),
        ).fetchone()
        if not c or c["credit_limit"] is None:
            return True, "ok"
        limit_v = float(c["credit_limit"])
    except Exception:
        return True, "ok"

    exposure = db.execute(
        """
        SELECT COALESCE(SUM(total),0) AS exp
        FROM invoices
        WHERE business_id=? AND party_id=? AND status IN ('unpaid', 'partial', 'pending', 'draft')
        """,
        (business_id, contact_id),
    ).fetchone()
    current_exp = float((exposure["exp"] if exposure else 0) or 0)
    if current_exp + float(invoice_total) > limit_v:
        return False, "تجاوز الحد الائتماني للعميل"
    return True, "ok"


def enforce_price_floor(
    db,
    business_id: int,
    items: list[dict[str, Any]],
    min_ratio: float = 1.0,
) -> tuple[bool, str, dict[str, Any]]:
    """
    يمنع البيع بسعر أقل من سعر المنتج المسجل (Price Floor).
    min_ratio=1.0 يعني لا يسمح بأي نزول عن سعر القائمة.
    """
    ratio = min(1.0, max(0.0, float(min_ratio or 0)))
    for idx, item in enumerate(items, start=1):
        product_id = item.get("product_id")
        if not product_id:
            continue

        try:
            sale_price = float(item.get("price", item.get("unit_price", 0)) or 0)
        except Exception:
            return False, f"سعر غير صالح في الصنف #{idx}", {"line": idx, "product_id": product_id}

        row = db.execute(
            """
            SELECT unit_price FROM product_inventory
            WHERE business_id=? AND product_id=?
            LIMIT 1
            """,
            (business_id, product_id),
        ).fetchone()
        if not row or row["unit_price"] is None:
            continue

        try:
            list_price = float(row["unit_price"])
        except Exception:
            continue
        floor_price = round(list_price * ratio, 4)
        if list_price > 0 and sale_price < floor_price:
            return (
                False,
                f"السعر أقل من الحد الأدنى للصنف #{idx}",
                {
                    "line": idx,
                    "product_id": product_id,
                    "list_price": list_price,
                    "sale_price": sale_price,
                    "floor_price": floor_price,
                    "min_ratio": ratio,
                },
            )

    return True, "ok", {}


def detect_debt_kiting_risk(db, business_id: int, contact_id: int | None, agent_id: int) -> tuple[bool, dict[str, Any]]:
    if not contact_id:
        return False, {}
    row = db.execute(
        """
        SELECT COUNT(*) AS c, COALESCE(SUM(total),0) AS s
        FROM invoices
        WHERE business_id=?
          AND party_id=?
          AND status IN ('unpaid', 'partial', 'pending')
          AND invoice_date >= date('now', '-7 days')
        """,
        (business_id, contact_id),
    ).fetchone()
    cnt = int((row["c"] if row else 0) or 0)
    total = float((row["s"] if row else 0) or 0)
    if cnt >= 3 and total >= 1000:
        return True, {"contact_id": contact_id, "open_invoices_7d": cnt, "open_amount_7d": total, "agent_id": agent_id}
    return False, {}


def _version_tuple(v: str) -> tuple[int, int, int]:
    raw = (v or "0.0.0").strip().split("-")[0]
    parts = raw.split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except Exception:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def enforce_agent_app_version(db, business_id: int | None, app_version: str | None) -> tuple[bool, dict[str, Any]]:
    """
    Force update policy من settings:
      - agent_force_update = 1
      - agent_min_app_version = x.y.z
    """
    if not business_id:
        return True, {"enforced": False}

    min_v_row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='agent_min_app_version' LIMIT 1",
        (business_id,),
    ).fetchone()
    force_row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='agent_force_update' LIMIT 1",
        (business_id,),
    ).fetchone()

    min_v = (min_v_row["value"] if min_v_row and min_v_row["value"] else "2.0.0").strip()
    force_update = str(force_row["value"] if force_row else "1").strip() in {"1", "true", "yes"}

    if not force_update:
        return True, {"enforced": False, "min_version": min_v}

    current_v = (app_version or "0.0.0").strip()
    if _version_tuple(current_v) < _version_tuple(min_v):
        return False, {
            "enforced": True,
            "reason": "force_update_required",
            "min_version": min_v,
            "current_version": current_v,
        }

    return True, {"enforced": True, "min_version": min_v, "current_version": current_v}
