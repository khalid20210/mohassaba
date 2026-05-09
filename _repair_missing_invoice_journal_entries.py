# -*- coding: utf-8 -*-
"""
ترميم قيود الفواتير المفقودة (آخر N فواتير بيع):
- يستهدف الفواتير paid/partial التي لا تملك journal_entry
- ينشئ قيدًا متوازنًا: مدين أصل (نقد/ذمم) مقابل دائن إيراد + دائن ضريبة (إن وجدت)

افتراضيًا: dry-run
فعليًا: --apply
"""
import argparse
import io
import sys
from datetime import datetime

from modules import create_app
from modules.extensions import get_db

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def pick_account_ids(db, biz_id: int):
    asset = db.execute(
        """SELECT id FROM accounts
           WHERE business_id=? AND is_active=1 AND is_header=0
             AND account_type='asset' AND account_nature='debit'
           ORDER BY id LIMIT 1""",
        (biz_id,),
    ).fetchone()
    revenue = db.execute(
        """SELECT id FROM accounts
           WHERE business_id=? AND is_active=1 AND is_header=0
             AND account_type='revenue' AND account_nature='credit'
           ORDER BY id LIMIT 1""",
        (biz_id,),
    ).fetchone()
    liability = db.execute(
        """SELECT id FROM accounts
           WHERE business_id=? AND is_active=1 AND is_header=0
             AND account_type='liability' AND account_nature='credit'
           ORDER BY id LIMIT 1""",
        (biz_id,),
    ).fetchone()
    return (
        int(asset["id"]) if asset else None,
        int(revenue["id"]) if revenue else None,
        int(liability["id"]) if liability else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    app = create_app()
    scanned = 0
    fixed = 0
    skipped = 0

    with app.app_context():
        db = get_db()
        rows = db.execute(
            """SELECT i.id, i.business_id, i.invoice_number, i.invoice_date, i.subtotal, i.tax_amount,
                      i.total, i.status, i.payment_method, i.created_by, i.journal_entry_id
               FROM invoices i
               WHERE i.invoice_type='sale' AND i.status IN ('paid','partial')
               ORDER BY i.id DESC
               LIMIT ?""",
            (max(1, int(args.limit)),),
        ).fetchall()

        for inv in rows:
            scanned += 1
            inv_id = int(inv["id"])
            biz_id = int(inv["business_id"])

            existing = db.execute(
                "SELECT id FROM journal_entries WHERE reference_type='invoice' AND reference_id=? LIMIT 1",
                (inv_id,),
            ).fetchone()
            if existing:
                continue

            asset_id, revenue_id, liability_id = pick_account_ids(db, biz_id)
            if not asset_id or not revenue_id:
                print(f"[SKIP] {inv['invoice_number']} missing account map asset/revenue")
                skipped += 1
                continue

            subtotal = round(float(inv["subtotal"] or 0), 2)
            tax = round(float(inv["tax_amount"] or 0), 2)
            total = round(float(inv["total"] or 0), 2)

            # fallback إذا subtotal غير معبأ بشكل صحيح
            if subtotal <= 0 and total > 0:
                subtotal = round(max(0.0, total - tax), 2)

            # تحقق توازن بسيط قبل الإدراج
            credit_total = round(subtotal + (tax if tax > 0 else 0.0), 2)
            if abs(credit_total - total) > 0.05:
                print(f"[SKIP] {inv['invoice_number']} totals mismatch subtotal+tax={credit_total} total={total}")
                skipped += 1
                continue

            entry_no = f"AUTO-INV-{inv_id}"
            entry_date = (inv["invoice_date"] or datetime.now().strftime("%Y-%m-%d"))
            desc = f"Auto repaired JE for invoice {inv['invoice_number']}"

            print(f"[CANDIDATE] {inv['invoice_number']} | total={total:.2f} | tax={tax:.2f} | apply={args.apply}")

            if args.apply:
                db.execute(
                    """INSERT INTO journal_entries
                       (business_id, entry_number, entry_date, description, reference_type, reference_id,
                        total_debit, total_credit, is_posted, created_by, posted_by, posted_at, created_at)
                       VALUES (?, ?, ?, ?, 'invoice', ?, ?, ?, 1, ?, ?, datetime('now'), datetime('now'))""",
                    (biz_id, entry_no, entry_date, desc, inv_id, total, total, inv["created_by"], inv["created_by"]),
                )
                je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                # مدين أصل (نقد/ذمم)
                db.execute(
                    """INSERT INTO journal_entry_lines
                       (entry_id, account_id, description, debit, credit, line_order)
                       VALUES (?, ?, ?, ?, 0, 1)""",
                    (je_id, asset_id, f"Debit for invoice {inv['invoice_number']}", total),
                )

                # دائن إيراد
                db.execute(
                    """INSERT INTO journal_entry_lines
                       (entry_id, account_id, description, debit, credit, line_order)
                       VALUES (?, ?, ?, 0, ?, 2)""",
                    (je_id, revenue_id, f"Revenue for invoice {inv['invoice_number']}", subtotal),
                )

                # دائن ضريبة (اختياري)
                if tax > 0:
                    tax_account = liability_id or revenue_id
                    db.execute(
                        """INSERT INTO journal_entry_lines
                           (entry_id, account_id, description, debit, credit, line_order)
                           VALUES (?, ?, ?, 0, ?, 3)""",
                        (je_id, tax_account, f"Tax for invoice {inv['invoice_number']}", tax),
                    )

                db.execute(
                    "UPDATE invoices SET journal_entry_id=? WHERE id=?",
                    (je_id, inv_id),
                )

            fixed += 1

        if args.apply:
            db.commit()

    print()
    print(f"scanned={scanned} | fixed_candidates={fixed} | skipped={skipped} | apply={args.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
