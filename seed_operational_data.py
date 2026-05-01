"""
seed_operational_data.py

ينفذ الحزمة النهائية التالية على database/accounting.db:
1) تصحيح الأسعار الخاسرة
2) تمييز الأسماء المكررة وتوليد باركود ناقص
3) ضمان الحسابات/المخازن والـ stock لكل منشأة نشطة
4) توليد معاملات مبيعات ومشتريات وقيود يومية لآخر 30 يوماً
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from modules.extensions import seed_business_accounts


DB_PATH = Path("database/accounting.db")
MARKER = "[AUTOSEED30]"
RNG = random.Random(20260501)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ean13_checksum(base12: str) -> str:
    digits = [int(ch) for ch in base12]
    odd = sum(digits[::2])
    even = sum(digits[1::2])
    checksum = (10 - ((odd + even * 3) % 10)) % 10
    return f"{base12}{checksum}"


def unique_barcode(cur: sqlite3.Cursor, business_id: int) -> str:
    while True:
        base12 = f"29{RNG.randint(10**9, (10**10) - 1):010d}"
        code = ean13_checksum(base12)
        row = cur.execute(
            "SELECT 1 FROM products WHERE business_id=? AND barcode=?",
            (business_id, code),
        ).fetchone()
        if not row:
            return code


def ensure_infrastructure(cur: sqlite3.Cursor, conn: sqlite3.Connection) -> dict[int, int]:
    warehouse_map: dict[int, int] = {}
    business_ids = [
        row[0]
        for row in cur.execute(
            """
            SELECT DISTINCT b.id
            FROM businesses b
            JOIN products p ON p.business_id=b.id AND p.is_active=1
            WHERE b.is_active=1
            ORDER BY b.id
            """
        ).fetchall()
    ]

    for business_id in business_ids:
        seed_business_accounts(conn, business_id)

        wh = cur.execute(
            "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
            (business_id,),
        ).fetchone()
        if not wh:
            cur.execute(
                "INSERT INTO warehouses (business_id, name, is_default, is_active) VALUES (?,?,1,1)",
                (business_id, "المستودع الرئيسي"),
            )
            warehouse_map[business_id] = cur.lastrowid
        else:
            warehouse_map[business_id] = int(wh["id"])

        cur.execute(
            "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
            (business_id, "invoice_prefix_purchase", "PUR"),
        )

    conn.commit()
    return warehouse_map


def sanitize_products(cur: sqlite3.Cursor) -> dict[str, int]:
    fixed_prices = 0
    renamed_duplicates = 0
    barcodes_added = 0

    rows = cur.execute(
        "SELECT id, purchase_price, sale_price FROM products WHERE sale_price < purchase_price"
    ).fetchall()
    for row in rows:
        purchase = float(row["purchase_price"] or 0)
        new_sale = round(max(purchase * 1.20, purchase + 1), 2)
        cur.execute(
            "UPDATE products SET sale_price=?, updated_at=datetime('now') WHERE id=?",
            (new_sale, row["id"]),
        )
        fixed_prices += 1

    dup_groups = cur.execute(
        """
        SELECT business_id, name, COUNT(*) AS cnt
        FROM products
        GROUP BY business_id, name
        HAVING cnt > 1
        ORDER BY business_id, name
        """
    ).fetchall()
    for group in dup_groups:
        business_id = int(group["business_id"])
        name = group["name"]
        rows = cur.execute(
            "SELECT id FROM products WHERE business_id=? AND name=? ORDER BY id",
            (business_id, name),
        ).fetchall()
        for index, row in enumerate(rows[1:], start=2):
            candidate = f"{name} - {index}"
            suffix = index
            while cur.execute(
                "SELECT 1 FROM products WHERE business_id=? AND name=? AND id<>?",
                (business_id, candidate, row["id"]),
            ).fetchone():
                suffix += 1
                candidate = f"{name} - {suffix}"
            cur.execute(
                "UPDATE products SET name=?, updated_at=datetime('now') WHERE id=?",
                (candidate, row["id"]),
            )
            renamed_duplicates += 1

    missing_rows = cur.execute(
        "SELECT id, business_id FROM products WHERE barcode IS NULL OR TRIM(barcode)=''"
    ).fetchall()
    for row in missing_rows:
        code = unique_barcode(cur, int(row["business_id"]))
        cur.execute(
            "UPDATE products SET barcode=?, updated_at=datetime('now') WHERE id=?",
            (code, row["id"]),
        )
        barcodes_added += 1

    return {
        "fixed_prices": fixed_prices,
        "renamed_duplicates": renamed_duplicates,
        "barcodes_added": barcodes_added,
    }


def seed_stock(cur: sqlite3.Cursor, warehouse_map: dict[int, int]) -> dict[str, int]:
    inserted = 0
    updated = 0
    product_rows = cur.execute(
        """
        SELECT id, business_id, purchase_price, track_stock
        FROM products
        WHERE is_active=1
        ORDER BY business_id, id
        """
    ).fetchall()

    for row in product_rows:
        if int(row["track_stock"] or 1) == 0:
            continue
        business_id = int(row["business_id"])
        warehouse_id = warehouse_map[business_id]
        quantity = float(RNG.randint(14, 120))
        avg_cost = round(float(row["purchase_price"] or 0), 4)
        stock_row = cur.execute(
            "SELECT id, quantity FROM stock WHERE product_id=? AND warehouse_id=?",
            (row["id"], warehouse_id),
        ).fetchone()
        if stock_row:
            if float(stock_row["quantity"] or 0) <= 0:
                cur.execute(
                    "UPDATE stock SET quantity=?, avg_cost=?, last_updated=datetime('now') WHERE id=?",
                    (quantity, avg_cost, stock_row["id"]),
                )
                updated += 1
        else:
            cur.execute(
                """
                INSERT INTO stock (business_id, product_id, warehouse_id, quantity, avg_cost, last_updated)
                VALUES (?,?,?,?,?,datetime('now'))
                """,
                (business_id, row["id"], warehouse_id, quantity, avg_cost),
            )
            inserted += 1

    return {"inserted_stock": inserted, "updated_zero_stock": updated}


def ensure_contacts(cur: sqlite3.Cursor) -> dict[str, int]:
    created = 0
    business_rows = cur.execute(
        """
        SELECT DISTINCT b.id, b.name
        FROM businesses b
        JOIN products p ON p.business_id=b.id AND p.is_active=1
        WHERE b.is_active=1
        ORDER BY b.id
        """
    ).fetchall()

    for biz in business_rows:
        business_id = int(biz["id"])
        base_name = biz["name"]
        customers = cur.execute(
            "SELECT COUNT(*) FROM contacts WHERE business_id=? AND contact_type='customer'",
            (business_id,),
        ).fetchone()[0]
        suppliers = cur.execute(
            "SELECT COUNT(*) FROM contacts WHERE business_id=? AND contact_type='supplier'",
            (business_id,),
        ).fetchone()[0]

        for idx in range(customers + 1, 9):
            cur.execute(
                """
                INSERT INTO contacts (business_id, contact_type, name, phone, email, is_active, created_at)
                VALUES (?,?,?,?,?,?,datetime('now'))
                """,
                (
                    business_id,
                    "customer",
                    f"عميل {base_name} {idx}",
                    f"700{business_id:02d}{idx:04d}",
                    f"customer{business_id}_{idx}@autoseed.local",
                    1,
                ),
            )
            created += 1

        for idx in range(suppliers + 1, 6):
            cur.execute(
                """
                INSERT INTO contacts (business_id, contact_type, name, phone, email, is_active, created_at)
                VALUES (?,?,?,?,?,?,datetime('now'))
                """,
                (
                    business_id,
                    "supplier",
                    f"مورد {base_name} {idx}",
                    f"711{business_id:02d}{idx:04d}",
                    f"supplier{business_id}_{idx}@autoseed.local",
                    1,
                ),
            )
            created += 1

    return {"created_contacts": created}


def next_invoice_number(cur: sqlite3.Cursor, business_id: int, invoice_type: str) -> str:
    prefixes = {
        "sale": "INV",
        "purchase": "PUR",
    }
    prefix = prefixes[invoice_type]
    count = cur.execute(
        "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type=?",
        (business_id, invoice_type),
    ).fetchone()[0]
    return f"{prefix}-{count + 1:05d}"


def next_entry_number(cur: sqlite3.Cursor, business_id: int) -> str:
    count = cur.execute(
        "SELECT COUNT(*) FROM journal_entries WHERE business_id=?",
        (business_id,),
    ).fetchone()[0]
    return f"JE-{count + 1:06d}"


def get_account_id(cur: sqlite3.Cursor, business_id: int, code: str) -> int | None:
    row = cur.execute(
        "SELECT id FROM accounts WHERE business_id=? AND code=?",
        (business_id, code),
    ).fetchone()
    return int(row["id"]) if row else None


def business_user(cur: sqlite3.Cursor, business_id: int) -> int | None:
    row = cur.execute(
        "SELECT id FROM users WHERE business_id=? AND is_active=1 ORDER BY id LIMIT 1",
        (business_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def pick_products_for_sale(cur: sqlite3.Cursor, business_id: int, warehouse_id: int) -> list[sqlite3.Row]:
    return cur.execute(
        """
        SELECT p.id, p.name, p.sale_price, p.purchase_price, s.quantity, s.avg_cost
        FROM products p
        JOIN stock s ON s.product_id=p.id AND s.warehouse_id=?
        WHERE p.business_id=? AND p.is_active=1 AND p.is_pos=1 AND p.product_type='product' AND s.quantity > 3
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (warehouse_id, business_id, RNG.randint(2, 5)),
    ).fetchall()


def pick_products_for_purchase(cur: sqlite3.Cursor, business_id: int) -> list[sqlite3.Row]:
    return cur.execute(
        """
        SELECT id, name, purchase_price, sale_price
        FROM products
        WHERE business_id=? AND is_active=1 AND product_type='product'
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (business_id, RNG.randint(2, 6)),
    ).fetchall()


def seed_transactions(cur: sqlite3.Cursor, conn: sqlite3.Connection, warehouse_map: dict[int, int]) -> dict[str, int]:
    if cur.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] > 0:
        raise RuntimeError("جدول invoices ليس فارغاً؛ أوقف التوليد لتفادي مضاعفة البيانات.")

    sale_invoices = 0
    purchase_invoices = 0
    sale_journal_entries = 0
    purchase_journal_entries = 0
    cogs_journal_entries = 0

    biz_rows = cur.execute(
        """
        SELECT DISTINCT b.id, b.name
        FROM businesses b
        JOIN products p ON p.business_id=b.id AND p.is_active=1
        WHERE b.is_active=1
        ORDER BY b.id
        """
    ).fetchall()

    for biz in biz_rows:
        business_id = int(biz["id"])
        warehouse_id = warehouse_map[business_id]
        user_id = business_user(cur, business_id)
        cash_acc = get_account_id(cur, business_id, "1101")
        bank_acc = get_account_id(cur, business_id, "1102")
        ap_acc = get_account_id(cur, business_id, "2101")
        inventory_acc = get_account_id(cur, business_id, "1104")
        sales_acc = get_account_id(cur, business_id, "4101")
        cogs_acc = get_account_id(cur, business_id, "5101")

        customer_ids = [
            int(r["id"])
            for r in cur.execute(
                "SELECT id FROM contacts WHERE business_id=? AND contact_type='customer' ORDER BY id",
                (business_id,),
            ).fetchall()
        ]
        supplier_ids = [
            int(r["id"])
            for r in cur.execute(
                "SELECT id FROM contacts WHERE business_id=? AND contact_type='supplier' ORDER BY id",
                (business_id,),
            ).fetchall()
        ]

        for offset in range(29, -1, -1):
            day = datetime.now() - timedelta(days=offset)
            sale_count = 2 if business_id == 1 else 1
            if RNG.random() > 0.55:
                sale_count += 1

            for sale_idx in range(sale_count):
                products = pick_products_for_sale(cur, business_id, warehouse_id)
                if not products:
                    continue
                customer_id = customer_ids[(offset + sale_idx) % len(customer_ids)] if customer_ids else None
                customer = cur.execute(
                    "SELECT name FROM contacts WHERE id=?",
                    (customer_id,),
                ).fetchone() if customer_id else None
                party_name = customer["name"] if customer else None
                pay_mode = "cash" if RNG.random() < 0.72 else "bank"
                debit_acc = cash_acc if pay_mode == "cash" else bank_acc or cash_acc
                invoice_number = next_invoice_number(cur, business_id, "sale")
                invoice_date = day.strftime("%Y-%m-%d")
                created_at = day.replace(
                    hour=9 + (sale_idx * 2), minute=RNG.randint(0, 55), second=RNG.randint(0, 59)
                ).strftime("%Y-%m-%d %H:%M:%S")

                subtotal = 0.0
                cogs_total = 0.0
                line_payload = []
                for product in products:
                    stock = cur.execute(
                        "SELECT quantity, avg_cost FROM stock WHERE product_id=? AND warehouse_id=?",
                        (product["id"], warehouse_id),
                    ).fetchone()
                    available = float(stock["quantity"] or 0)
                    if available <= 1:
                        continue
                    qty = min(float(RNG.randint(1, 4)), max(1.0, available // 3))
                    if qty <= 0:
                        continue
                    unit_price = round(float(product["sale_price"] or 0), 2)
                    line_total = round(qty * unit_price, 2)
                    unit_cost = round(float(stock["avg_cost"] or product["purchase_price"] or 0), 4)
                    subtotal += line_total
                    cogs_total += round(qty * unit_cost, 2)
                    line_payload.append((product, qty, unit_price, line_total, unit_cost))

                if not line_payload or subtotal <= 0:
                    continue

                cur.execute(
                    """
                    INSERT INTO invoices
                    (business_id, invoice_number, invoice_type, invoice_date, party_id, party_name,
                     warehouse_id, subtotal, tax_amount, total, paid_amount, status, notes, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        business_id,
                        invoice_number,
                        "sale",
                        invoice_date,
                        customer_id,
                        party_name,
                        warehouse_id,
                        round(subtotal, 2),
                        0,
                        round(subtotal, 2),
                        round(subtotal, 2),
                        "paid",
                        f"{MARKER} POS sale",
                        user_id,
                        created_at,
                    ),
                )
                invoice_id = cur.lastrowid

                for line_order, (product, qty, unit_price, line_total, unit_cost) in enumerate(line_payload, start=1):
                    cur.execute(
                        """
                        INSERT INTO invoice_lines
                        (invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_amount, total, line_order)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            invoice_id,
                            product["id"],
                            product["name"],
                            qty,
                            unit_price,
                            0,
                            0,
                            line_total,
                            line_order,
                        ),
                    )
                    cur.execute(
                        "UPDATE stock SET quantity=quantity-?, last_updated=? WHERE product_id=? AND warehouse_id=?",
                        (qty, created_at, product["id"], warehouse_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO stock_movements
                        (business_id, product_id, warehouse_id, movement_type, quantity, unit_cost,
                         reference_type, reference_id, notes, created_by, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            business_id,
                            product["id"],
                            warehouse_id,
                            "sale",
                            -qty,
                            unit_cost,
                            "invoice",
                            invoice_id,
                            MARKER,
                            user_id,
                            created_at,
                        ),
                    )

                sale_entry_number = next_entry_number(cur, business_id)
                cur.execute(
                    """
                    INSERT INTO journal_entries
                    (business_id, entry_number, entry_date, description, reference_type, reference_id,
                     total_debit, total_credit, is_posted, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        business_id,
                        sale_entry_number,
                        invoice_date,
                        f"{MARKER} قيد مبيعات {invoice_number}",
                        "invoice",
                        invoice_id,
                        round(subtotal, 2),
                        round(subtotal, 2),
                        1,
                        user_id,
                        created_at,
                    ),
                )
                sale_je_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO journal_entry_lines (entry_id, account_id, description, debit, credit, line_order) VALUES (?,?,?,?,?,?)",
                    (sale_je_id, debit_acc, f"{MARKER} قبض مبيعات", round(subtotal, 2), 0, 1),
                )
                cur.execute(
                    "INSERT INTO journal_entry_lines (entry_id, account_id, description, debit, credit, line_order) VALUES (?,?,?,?,?,?)",
                    (sale_je_id, sales_acc, f"{MARKER} إيراد مبيعات", 0, round(subtotal, 2), 2),
                )

                cogs_entry_number = next_entry_number(cur, business_id)
                cur.execute(
                    """
                    INSERT INTO journal_entries
                    (business_id, entry_number, entry_date, description, reference_type, reference_id,
                     total_debit, total_credit, is_posted, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        business_id,
                        cogs_entry_number,
                        invoice_date,
                        f"{MARKER} قيد تكلفة {invoice_number}",
                        "invoice",
                        invoice_id,
                        round(cogs_total, 2),
                        round(cogs_total, 2),
                        1,
                        user_id,
                        created_at,
                    ),
                )
                cogs_je_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO journal_entry_lines (entry_id, account_id, description, debit, credit, line_order) VALUES (?,?,?,?,?,?)",
                    (cogs_je_id, cogs_acc, f"{MARKER} تكلفة بضاعة مباعة", round(cogs_total, 2), 0, 1),
                )
                cur.execute(
                    "INSERT INTO journal_entry_lines (entry_id, account_id, description, debit, credit, line_order) VALUES (?,?,?,?,?,?)",
                    (cogs_je_id, inventory_acc, f"{MARKER} إقفال مخزون", 0, round(cogs_total, 2), 2),
                )
                cur.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (sale_je_id, invoice_id))

                sale_invoices += 1
                sale_journal_entries += 1
                cogs_journal_entries += 1

            purchase_today = business_id == 1 or offset % 3 == (business_id % 3)
            if not purchase_today:
                continue

            products = pick_products_for_purchase(cur, business_id)
            if not products:
                continue

            supplier_id = supplier_ids[offset % len(supplier_ids)] if supplier_ids else None
            supplier = cur.execute("SELECT name FROM contacts WHERE id=?", (supplier_id,)).fetchone() if supplier_id else None
            party_name = supplier["name"] if supplier else None
            pay_mode = "credit" if RNG.random() < 0.45 else ("cash" if RNG.random() < 0.5 else "bank")
            credit_acc = ap_acc if pay_mode == "credit" else (cash_acc if pay_mode == "cash" else bank_acc or cash_acc)
            invoice_number = next_invoice_number(cur, business_id, "purchase")
            invoice_date = day.strftime("%Y-%m-%d")
            created_at = day.replace(hour=16, minute=RNG.randint(0, 50), second=RNG.randint(0, 59)).strftime("%Y-%m-%d %H:%M:%S")

            subtotal = 0.0
            line_payload = []
            for product in products:
                qty = float(RNG.randint(6, 24))
                unit_cost = round(max(float(product["purchase_price"] or 0), 1.0) * RNG.uniform(0.98, 1.08), 2)
                line_total = round(qty * unit_cost, 2)
                subtotal += line_total
                line_payload.append((product, qty, unit_cost, line_total))

            cur.execute(
                """
                INSERT INTO invoices
                (business_id, invoice_number, invoice_type, invoice_date, party_id, party_name,
                 warehouse_id, subtotal, tax_amount, total, paid_amount, status, notes, created_by, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    business_id,
                    invoice_number,
                    "purchase",
                    invoice_date,
                    supplier_id,
                    party_name,
                    warehouse_id,
                    round(subtotal, 2),
                    0,
                    round(subtotal, 2),
                    0 if pay_mode == "credit" else round(subtotal, 2),
                    "partial" if pay_mode == "credit" else "paid",
                    f"{MARKER} Supplier purchase",
                    user_id,
                    created_at,
                ),
            )
            invoice_id = cur.lastrowid

            for line_order, (product, qty, unit_cost, line_total) in enumerate(line_payload, start=1):
                cur.execute(
                    """
                    INSERT INTO invoice_lines
                    (invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_amount, total, line_order)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        invoice_id,
                        product["id"],
                        product["name"],
                        qty,
                        unit_cost,
                        0,
                        0,
                        line_total,
                        line_order,
                    ),
                )
                stock = cur.execute(
                    "SELECT quantity, avg_cost FROM stock WHERE product_id=? AND warehouse_id=?",
                    (product["id"], warehouse_id),
                ).fetchone()
                old_qty = float(stock["quantity"] or 0)
                old_avg = float(stock["avg_cost"] or 0)
                new_qty = old_qty + qty
                new_avg = ((old_qty * old_avg) + (qty * unit_cost)) / new_qty if new_qty else unit_cost
                cur.execute(
                    "UPDATE stock SET quantity=?, avg_cost=?, last_updated=? WHERE product_id=? AND warehouse_id=?",
                    (round(new_qty, 4), round(new_avg, 4), created_at, product["id"], warehouse_id),
                )
                cur.execute(
                    "UPDATE products SET purchase_price=?, updated_at=datetime('now') WHERE id=?",
                    (unit_cost, product["id"]),
                )
                cur.execute(
                    """
                    INSERT INTO stock_movements
                    (business_id, product_id, warehouse_id, movement_type, quantity, unit_cost,
                     reference_type, reference_id, notes, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        business_id,
                        product["id"],
                        warehouse_id,
                        "purchase",
                        qty,
                        unit_cost,
                        "invoice",
                        invoice_id,
                        MARKER,
                        user_id,
                        created_at,
                    ),
                )

            purchase_entry_number = next_entry_number(cur, business_id)
            cur.execute(
                """
                INSERT INTO journal_entries
                (business_id, entry_number, entry_date, description, reference_type, reference_id,
                 total_debit, total_credit, is_posted, created_by, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    business_id,
                    purchase_entry_number,
                    invoice_date,
                    f"{MARKER} قيد مشتريات {invoice_number}",
                    "invoice",
                    invoice_id,
                    round(subtotal, 2),
                    round(subtotal, 2),
                    1,
                    user_id,
                    created_at,
                ),
            )
            purchase_je_id = cur.lastrowid
            cur.execute(
                "INSERT INTO journal_entry_lines (entry_id, account_id, description, debit, credit, line_order) VALUES (?,?,?,?,?,?)",
                (purchase_je_id, inventory_acc, f"{MARKER} إضافة مخزون", round(subtotal, 2), 0, 1),
            )
            cur.execute(
                "INSERT INTO journal_entry_lines (entry_id, account_id, description, debit, credit, line_order) VALUES (?,?,?,?,?,?)",
                (purchase_je_id, credit_acc, f"{MARKER} سداد/استحقاق مورد", 0, round(subtotal, 2), 2),
            )
            cur.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (purchase_je_id, invoice_id))

            purchase_invoices += 1
            purchase_journal_entries += 1

    conn.commit()
    return {
        "sale_invoices": sale_invoices,
        "purchase_invoices": purchase_invoices,
        "sale_journal_entries": sale_journal_entries,
        "purchase_journal_entries": purchase_journal_entries,
        "cogs_journal_entries": cogs_journal_entries,
    }


def summarize(cur: sqlite3.Cursor) -> dict[str, float]:
    today = datetime.now().strftime("%Y-%m-%d")
    sales_today = float(
        cur.execute(
            "SELECT COALESCE(SUM(total),0) FROM invoices WHERE invoice_type='sale' AND status='paid' AND DATE(invoice_date)=?",
            (today,),
        ).fetchone()[0]
        or 0
    )
    purchases_today = float(
        cur.execute(
            "SELECT COALESCE(SUM(total),0) FROM invoices WHERE invoice_type='purchase' AND DATE(invoice_date)=?",
            (today,),
        ).fetchone()[0]
        or 0
    )
    revenue_today = float(
        cur.execute(
            """
            SELECT COALESCE(SUM(jel.credit),0)
            FROM journal_entry_lines jel
            JOIN journal_entries je ON je.id=jel.entry_id
            JOIN accounts a ON a.id=jel.account_id
            WHERE a.code='4101' AND DATE(je.entry_date)=?
            """,
            (today,),
        ).fetchone()[0]
        or 0
    )
    cogs_today = float(
        cur.execute(
            """
            SELECT COALESCE(SUM(jel.debit),0)
            FROM journal_entry_lines jel
            JOIN journal_entries je ON je.id=jel.entry_id
            JOIN accounts a ON a.id=jel.account_id
            WHERE a.code='5101' AND DATE(je.entry_date)=?
            """,
            (today,),
        ).fetchone()[0]
        or 0
    )
    return {
        "sales_today": round(sales_today, 2),
        "purchases_today": round(purchases_today, 2),
        "net_profit_today": round(revenue_today - cogs_today, 2),
        "total_invoices": int(cur.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]),
        "total_entries": int(cur.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]),
    }


def main() -> None:
    conn = connect()
    cur = conn.cursor()

    print("=" * 72)
    print(" بدء الحزمة النهائية: تنظيف البيانات + زرع المخزون + المعاملات ")
    print("=" * 72)

    warehouse_map = ensure_infrastructure(cur, conn)
    sanitize_report = sanitize_products(cur)
    stock_report = seed_stock(cur, warehouse_map)
    contacts_report = ensure_contacts(cur)
    conn.commit()

    tx_report = seed_transactions(cur, conn, warehouse_map)
    post_tx_sanitize = sanitize_products(cur)
    sanitize_report["fixed_prices"] += post_tx_sanitize["fixed_prices"]
    summary = summarize(cur)
    conn.commit()
    conn.close()

    print("Data Sanitization:")
    print(f"  fixed_prices={sanitize_report['fixed_prices']}")
    print(f"  renamed_duplicates={sanitize_report['renamed_duplicates']}")
    print(f"  barcodes_added={sanitize_report['barcodes_added']}")
    print("Inventory Seeding:")
    print(f"  inserted_stock={stock_report['inserted_stock']}")
    print(f"  updated_zero_stock={stock_report['updated_zero_stock']}")
    print(f"  created_contacts={contacts_report['created_contacts']}")
    print("Transactional Seeding:")
    print(f"  sale_invoices={tx_report['sale_invoices']}")
    print(f"  purchase_invoices={tx_report['purchase_invoices']}")
    print(f"  sale_journal_entries={tx_report['sale_journal_entries']}")
    print(f"  purchase_journal_entries={tx_report['purchase_journal_entries']}")
    print(f"  cogs_journal_entries={tx_report['cogs_journal_entries']}")
    print("Summary:")
    print(f"  sales_today={summary['sales_today']}")
    print(f"  purchases_today={summary['purchases_today']}")
    print(f"  net_profit_today={summary['net_profit_today']}")
    print(f"  total_invoices={summary['total_invoices']}")
    print(f"  total_entries={summary['total_entries']}")
    print("DONE")


if __name__ == "__main__":
    main()
