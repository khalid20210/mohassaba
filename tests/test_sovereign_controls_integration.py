import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime

import pytest


def _db():
    db_path = os.environ.get("DB_PATH")
    if not db_path:
        from modules.config import DB_PATH
        db_path = str(DB_PATH)
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _base_db_path():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "accounting_dev.db")


def _isolated_app(tmp_path, monkeypatch):
    temp_db = tmp_path / f"test-{uuid.uuid4().hex}.db"
    shutil.copy2(_base_db_path(), temp_db)
    monkeypatch.setenv("DB_PATH", str(temp_db))
    for name in list(sys.modules.keys()):
        if name == "app" or name == "modules" or name.startswith("modules."):
            sys.modules.pop(name, None)
    import app as app_module
    return app_module.app


def _find_owner_user():
    conn = _db()
    rows = conn.execute(
        """
        SELECT u.id AS user_id, u.business_id AS business_id, r.permissions AS permissions
        FROM users u
        LEFT JOIN roles r ON r.id = u.role_id
        """
    ).fetchall()
    conn.close()

    for row in rows:
        try:
            perms = json.loads(row["permissions"] or "{}")
        except Exception:
            perms = {}
        if perms.get("all"):
            return int(row["user_id"]), int(row["business_id"])
    return None


def _ensure_onboarding_complete(conn, business_id: int):
    conn.execute(
        """
        INSERT INTO settings (business_id, key, value)
        VALUES (?, 'onboarding_complete', '1')
        ON CONFLICT(business_id, key) DO UPDATE SET value='1'
        """,
        (business_id,),
    )


def _ensure_invoice_cancel_requests_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_cancel_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            requested_by INTEGER,
            reason TEXT NOT NULL,
            evidence_ref TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            review_note TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _ensure_invoice_columns(conn):
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(invoices)").fetchall()}
    if "payment_method" not in cols:
        conn.execute("ALTER TABLE invoices ADD COLUMN payment_method TEXT DEFAULT 'cash'")
    if "party_vat" not in cols:
        conn.execute("ALTER TABLE invoices ADD COLUMN party_vat TEXT DEFAULT ''")
    if "pos_shift_id" not in cols:
        conn.execute("ALTER TABLE invoices ADD COLUMN pos_shift_id INTEGER")


def _ensure_hr_columns(conn):
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(employees)").fetchall()}
    if "allowances" not in cols:
        conn.execute("ALTER TABLE employees ADD COLUMN allowances REAL DEFAULT 0")
    if "status" not in cols:
        conn.execute("ALTER TABLE employees ADD COLUMN status TEXT DEFAULT 'active'")


def _sessionify(client, user_id: int, business_id: int):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["business_id"] = business_id
        sess["csrf_token"] = "test-csrf-token"


def test_cashier_lock_blocks_pos_until_owner_release(tmp_path, monkeypatch):
    app = _isolated_app(tmp_path, monkeypatch)
    from modules.sovereign_controls import ensure_sovereign_tables, set_owner_policy

    owner = _find_owner_user()
    if owner is None:
        pytest.skip("No owner user with permissions.all found in database")

    user_id, business_id = owner
    conn = _db()
    ensure_sovereign_tables(conn)
    _ensure_invoice_cancel_requests_table(conn)
    _ensure_invoice_columns(conn)
    _ensure_onboarding_complete(conn, business_id)
    _ensure_hr_columns(conn)

    baseline_requests = conn.execute(
        "SELECT COUNT(*) FROM invoice_cancel_requests WHERE business_id=? AND requested_by=? AND datetime(created_at) >= datetime('now', '-1 day')",
        (business_id, user_id),
    ).fetchone()[0]
    baseline_cancelled = conn.execute(
        "SELECT COUNT(*) FROM invoices WHERE business_id=? AND cancelled_by=? AND datetime(COALESCE(cancelled_at, created_at)) >= datetime('now', '-1 day')",
        (business_id, user_id),
    ).fetchone()[0]
    threshold = int(baseline_requests or 0) + int(baseline_cancelled or 0) + 1
    set_owner_policy(conn, business_id, "pos_cancel_daily_threshold", threshold, updated_by=user_id)

    invoice_number = f"TEST-CANCEL-{uuid.uuid4().hex[:8]}"
    cur = conn.execute(
        """
        INSERT INTO invoices (
            business_id, invoice_number, invoice_type, invoice_date,
            subtotal, tax_amount, total, paid_amount, status,
            created_by, created_at, payment_method, party_name
        ) VALUES (?, ?, 'sale', date('now'), 120, 0, 120, 120, 'paid', ?, datetime('now'), 'cash', 'عميل اختبار')
        """,
        (business_id, invoice_number, user_id),
    )
    invoice_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    client = app.test_client()
    _sessionify(client, user_id, business_id)

    resp = client.post(
        f"/invoices/{invoice_id}/cancel",
        data={
            "reason": "سبب اختبار مقبول ومفصل لإلغاء فاتورة مدفوعة",
            "evidence_ref": "DOC-12345",
            "csrf_token": "test-csrf-token",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = _db()
    lock = conn.execute(
        "SELECT id, status FROM pos_cashier_locks WHERE business_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
        (business_id, user_id),
    ).fetchone()
    assert lock is not None
    assert lock["status"] == "active"
    lock_id = int(lock["id"])
    conn.close()

    blocked = client.post("/api/pos/checkout", json={})
    assert blocked.status_code == 423

    released = client.post(
        f"/owner/api/cashier-locks/{lock_id}/release",
        json={"release_note": "فك تجميد اختباري"},
    )
    assert released.status_code == 200
    assert released.get_json()["status"] == "success"

    after_release = client.post("/api/pos/checkout", json={})
    assert after_release.status_code != 423

def test_owner_approval_executes_inventory_damage_request(tmp_path, monkeypatch):
    app = _isolated_app(tmp_path, monkeypatch)
    from modules.sovereign_controls import ensure_sovereign_tables

    owner = _find_owner_user()
    if owner is None:
        pytest.skip("No owner user with permissions.all found in database")

    user_id, business_id = owner
    conn = _db()
    ensure_sovereign_tables(conn)
    _ensure_onboarding_complete(conn, business_id)
    _ensure_hr_columns(conn)

    cur = conn.execute(
        "INSERT INTO products (business_id, name, purchase_price, sale_price, created_at, updated_at) VALUES (?, ?, 5, 8, datetime('now'), datetime('now'))",
        (business_id, f"منتج-{uuid.uuid4().hex[:6]}"),
    )
    stock_product_id = int(cur.lastrowid)

    cur = conn.execute(
        """
        INSERT INTO product_inventory (
            business_id, product_id, sku, current_qty, min_qty, max_qty, unit_cost, unit_price, created_at, updated_at
        ) VALUES (?, ?, ?, 10, 1, 100, 5, 8, datetime('now'), datetime('now'))
        """,
        (business_id, stock_product_id, f"SKU-{uuid.uuid4().hex[:6]}"),
    )
    product_id = int(cur.lastrowid)
    payload = json.dumps({
        "movement_type": "waste",
        "normalized_type": "damage",
        "quantity": 3,
        "current_qty": 10,
        "requested_new_qty": 7,
        "sku": "TEST-SKU",
    }, ensure_ascii=False)
    cur = conn.execute(
        """
        INSERT INTO owner_action_requests (
            business_id, request_type, entity_type, entity_id, requested_by, status, reason, payload_json
        ) VALUES (?, 'inventory.damage.writeoff', 'product_inventory', ?, ?, 'pending', ?, ?)
        """,
        (business_id, product_id, user_id, "اختبار طلب تالف", payload),
    )
    req_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    client = app.test_client()
    _sessionify(client, user_id, business_id)
    resp = client.post(f"/owner/api/action-requests/{req_id}/resolve", json={"decision": "approve", "owner_note": "اعتماد الاختبار"})
    assert resp.status_code == 200
    assert resp.get_json()["decision"] == "approved"

    conn = _db()
    qty = conn.execute("SELECT current_qty FROM product_inventory WHERE id=?", (product_id,)).fetchone()[0]
    assert float(qty) == 7.0
    movement = conn.execute(
        "SELECT movement_type, quantity FROM inventory_movements WHERE business_id=? AND product_id=? ORDER BY id DESC LIMIT 1",
        (business_id, stock_product_id),
    ).fetchone()
    assert movement is not None
    assert movement["movement_type"] == "damage"
    assert float(movement["quantity"]) == 3.0
def test_owner_approval_executes_payroll_salary_override_request(tmp_path, monkeypatch):
    app = _isolated_app(tmp_path, monkeypatch)
    from modules.sovereign_controls import ensure_sovereign_tables

    owner = _find_owner_user()
    if owner is None:
        pytest.skip("No owner user with permissions.all found in database")

    user_id, business_id = owner
    conn = _db()
    ensure_sovereign_tables(conn)
    _ensure_onboarding_complete(conn, business_id)
    _ensure_hr_columns(conn)

    cur = conn.execute(
        """
        INSERT INTO employees (business_id, full_name, base_salary, is_active, created_at, allowances)
        VALUES (?, ?, 100, 1, datetime('now'), 10)
        """,
        (business_id, f"موظف-{uuid.uuid4().hex[:6]}"),
    )
    employee_id = int(cur.lastrowid)
    payload = json.dumps({
        "employee_name": "موظف اختبار",
        "old_base_salary": 100,
        "new_base_salary": 200,
        "old_allowances": 10,
        "new_allowances": 40,
    }, ensure_ascii=False)
    cur = conn.execute(
        """
        INSERT INTO owner_action_requests (
            business_id, request_type, entity_type, entity_id, requested_by, status, reason, payload_json
        ) VALUES (?, 'payroll.salary_override', 'employee', ?, ?, 'pending', ?, ?)
        """,
        (business_id, employee_id, user_id, "اختبار تعديل راتب", payload),
    )
    req_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    client = app.test_client()
    _sessionify(client, user_id, business_id)
    resp = client.post(f"/owner/api/action-requests/{req_id}/resolve", json={"decision": "approve", "owner_note": "اعتماد تعديل الراتب"})
    assert resp.status_code == 200

    conn = _db()
    row = conn.execute("SELECT base_salary, allowances FROM employees WHERE id=?", (employee_id,)).fetchone()
    assert float(row["base_salary"]) == 200.0
    assert float(row["allowances"]) == 40.0
def test_posted_journal_edit_request_can_be_approved_with_execution_linking(tmp_path, monkeypatch):
    app = _isolated_app(tmp_path, monkeypatch)
    from modules.sovereign_controls import ensure_sovereign_tables, set_owner_policy

    owner = _find_owner_user()
    if owner is None:
        pytest.skip("No owner user with permissions.all found in database")

    user_id, business_id = owner
    conn = _db()
    ensure_sovereign_tables(conn)
    _ensure_onboarding_complete(conn, business_id)
    set_owner_policy(conn, business_id, "journal_posted_requires_owner", 1, updated_by=user_id)
    cur = conn.execute(
        """
        INSERT INTO journal_entries (
            business_id, entry_number, entry_date, description,
            total_debit, total_credit, is_posted, created_by, created_at
        ) VALUES (?, ?, date('now'), ?, 150, 150, 1, ?, datetime('now'))
        """,
        (business_id, f"JE-{uuid.uuid4().hex[:8]}", "قيد اختبار مرحل", user_id),
    )
    je_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    client = app.test_client()
    _sessionify(client, user_id, business_id)
    req_create = client.post(f"/accounting/{je_id}/request-edit", json={"reason": "نحتاج تعديل مرحلي مضبوط"})
    assert req_create.status_code == 200
    data = req_create.get_json()
    assert data["success"] is True
    req_id = int(data["request_id"])

    approve = client.post(
        f"/owner/api/action-requests/{req_id}/resolve",
        json={"decision": "approve", "owner_note": "موافقة استثناء اختبارية"},
    )
    assert approve.status_code == 200
    assert approve.get_json()["decision"] == "approved"

    conn = _db()
    req = conn.execute(
        "SELECT request_type, status, entity_id FROM owner_action_requests WHERE business_id=? AND id=? LIMIT 1",
        (business_id, req_id),
    ).fetchone()
    assert req is not None
    assert req["request_type"] == "accounting.posted_journal_edit"
    assert req["status"] == "approved"

    row = conn.execute(
        "SELECT owner_edit_exception_until, owner_edit_exception_by, owner_edit_exception_note FROM journal_entries WHERE id=? AND business_id=? LIMIT 1",
        (je_id, business_id),
    ).fetchone()
    assert row is not None
    assert row["owner_edit_exception_until"] is not None
    assert int(row["owner_edit_exception_by"] or 0) == int(user_id)
    assert "استثناء" in str(row["owner_edit_exception_note"] or "")
    conn.close()


def test_owner_approval_executes_payroll_manual_payment_request(tmp_path, monkeypatch):
    app = _isolated_app(tmp_path, monkeypatch)
    from modules.sovereign_controls import ensure_sovereign_tables

    owner = _find_owner_user()
    if owner is None:
        pytest.skip("No owner user with permissions.all found in database")

    user_id, business_id = owner
    conn = _db()
    ensure_sovereign_tables(conn)
    _ensure_onboarding_complete(conn, business_id)
    _ensure_hr_columns(conn)

    emp_cur = conn.execute(
        """
        INSERT INTO employees (business_id, full_name, base_salary, is_active, created_at, allowances)
        VALUES (?, ?, 2500, 1, datetime('now'), 200)
        """,
        (business_id, f"موظف-راتب-{uuid.uuid4().hex[:6]}"),
    )
    employee_id = int(emp_cur.lastrowid)

    payroll_cur = conn.execute(
        """
        INSERT INTO hr_payroll (
            business_id, employee_id, period_month, base_salary, allowances,
            advance_deduction, social_insurance, gross_salary, net_salary,
            status, created_at
        ) VALUES (?, ?, strftime('%Y-%m','now'), 2500, 200, 0, 0, 2700, 2700, 'pending', datetime('now'))
        """,
        (business_id, employee_id),
    )
    payroll_id = int(payroll_cur.lastrowid)

    payload = json.dumps(
        {
            "employee_id": employee_id,
            "period_month": datetime.now().strftime("%Y-%m"),
            "net_salary": 2700,
            "status": "pending",
        },
        ensure_ascii=False,
    )
    req_cur = conn.execute(
        """
        INSERT INTO owner_action_requests (
            business_id, request_type, entity_type, entity_id, requested_by, status, reason, payload_json
        ) VALUES (?, 'payroll.manual_payment', 'hr_payroll', ?, ?, 'pending', ?, ?)
        """,
        (business_id, payroll_id, user_id, "اختبار صرف راتب يدوي", payload),
    )
    req_id = int(req_cur.lastrowid)
    conn.commit()
    conn.close()

    client = app.test_client()
    _sessionify(client, user_id, business_id)
    resp = client.post(
        f"/owner/api/action-requests/{req_id}/resolve",
        json={"decision": "approve", "owner_note": "اعتماد صرف الراتب"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["decision"] == "approved"

    conn = _db()
    payroll = conn.execute(
        "SELECT status, payment_date FROM hr_payroll WHERE id=? AND business_id=? LIMIT 1",
        (payroll_id, business_id),
    ).fetchone()
    assert payroll is not None
    assert payroll["status"] == "paid"
    assert payroll["payment_date"] is not None
    conn.close()
