# -*- coding: utf-8 -*-
"""
إصلاح آمن لضريبة البنود في الفواتير القديمة:
- إذا كانت ضريبة البنود كلها 0
- وضريبة رأس الفاتورة > 0
- وإجمالي الفاتورة = مجموع البنود + ضريبة الرأس (legacy model)

الوضع الافتراضي: Dry-run
للتطبيق الفعلي: --apply
"""
import argparse
import io
import sys

from modules import create_app
from modules.extensions import get_db

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def allocate_tax(line_totals: list[float], tax_total: float) -> list[float]:
    base = sum(line_totals)
    if base <= 0 or tax_total <= 0:
        return [0.0 for _ in line_totals]

    out = []
    running = 0.0
    for i, v in enumerate(line_totals):
        if i == len(line_totals) - 1:
            share = round(tax_total - running, 2)
        else:
            share = round((v / base) * tax_total, 2)
            running += share
        out.append(max(0.0, share))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="عدد الفواتير الأخيرة")
    parser.add_argument("--apply", action="store_true", help="تطبيق الإصلاح فعليًا")
    args = parser.parse_args()

    app = create_app()
    fixed = 0
    scanned = 0

    with app.app_context():
        db = get_db()
        invoices = db.execute(
            """SELECT id, invoice_number, total, tax_amount
               FROM invoices
               WHERE invoice_type='sale'
               ORDER BY id DESC
               LIMIT ?""",
            (max(1, int(args.limit)),),
        ).fetchall()

        for inv in invoices:
            scanned += 1
            inv_id = inv["id"]
            inv_no = inv["invoice_number"]
            header_total = float(inv["total"] or 0)
            header_tax = float(inv["tax_amount"] or 0)
            if header_tax <= 0:
                continue

            lines = db.execute(
                "SELECT id, total, COALESCE(tax_amount,0) AS tax_amount FROM invoice_lines WHERE invoice_id=? ORDER BY id",
                (inv_id,),
            ).fetchall()
            if not lines:
                continue

            line_totals = [float(r["total"] or 0) for r in lines]
            line_taxes = [float(r["tax_amount"] or 0) for r in lines]

            all_line_tax_zero = all(abs(x) < 0.0001 for x in line_taxes)
            legacy_matches = abs((sum(line_totals) + header_tax) - header_total) <= 0.02
            if not (all_line_tax_zero and legacy_matches):
                continue

            new_taxes = allocate_tax(line_totals, header_tax)

            print(f"[CANDIDATE] {inv_no} | lines={len(lines)} | header_tax={header_tax:.2f} | apply={args.apply}")
            for row, tax in zip(lines, new_taxes):
                print(f"   - line#{row['id']} tax_amount: {row['tax_amount']} -> {tax:.2f}")
                if args.apply:
                    db.execute("UPDATE invoice_lines SET tax_amount=? WHERE id=?", (tax, row["id"]))

            fixed += 1

        if args.apply:
            db.commit()

    print()
    print(f"scanned={scanned} | fixed_candidates={fixed} | apply={args.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
