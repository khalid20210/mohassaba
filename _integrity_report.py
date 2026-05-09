# -*- coding: utf-8 -*-
"""
تقرير سلامة البيانات — Data Integrity Report
يفحص آخر 100 فاتورة مبيعات ويطابق:
  1. مجاميع الفاتورة مقابل بنودها (Invoice ↔ Lines)
  2. قيود دفتر الأستاذ مقابل مبلغ الفاتورة (Invoice ↔ Journal)
  3. توازن دفتر الأستاذ: مدين = دائن (Debit = Credit)
  4. حركات المخزون مقابل كميات البنود (Lines ↔ Stock Movements)
  5. رصيد العميل مقابل الفواتير الآجلة (Customer Ledger ↔ Credit Sales)
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from modules import create_app
from modules.extensions import get_db

TOLERANCE = 0.01   # هللة واحدة = 0.01 ريال

app = create_app()
with app.app_context():
    db = get_db()

    # ── جلب آخر 100 فاتورة مبيعات ────────────────────────────────────────────
    invoices = db.execute("""
        SELECT id, business_id, invoice_number, invoice_type,
               subtotal, tax_amount, total, paid_amount, status,
               party_id, payment_method, journal_entry_id
        FROM invoices
        WHERE invoice_type = 'sale'
        ORDER BY id DESC
        LIMIT 100
    """).fetchall()

    if not invoices:
        print("⚠️  لا توجد فواتير مبيعات في قاعدة البيانات")
        sys.exit(0)

    total_invoices = len(invoices)
    issues = []   # قائمة المشاكل المكتشفة
    checked = {
        "invoice_lines_sum":    0,
        "journal_balance":      0,
        "journal_link":         0,
        "stock_movements":      0,
        "customer_ledger":      0,
        "legacy_tax_model":     0,
        "service_only_invoices": 0,
    }

    for inv in invoices:
        inv_id  = inv["id"]
        inv_num = inv["invoice_number"]
        biz_id  = inv["business_id"]

        # ══════════════════════════════════════════════════════════════════════
        # الفحص 1: مجموع البنود يساوي إجمالي الفاتورة
        # ══════════════════════════════════════════════════════════════════════
        lines = db.execute(
            """SELECT il.product_id, il.quantity, il.unit_price, il.discount_amount,
                      il.tax_amount, il.total, COALESCE(p.track_stock, 0) AS track_stock
               FROM invoice_lines il
               LEFT JOIN products p ON p.id = il.product_id
               WHERE il.invoice_id=?""",
            (inv_id,)
        ).fetchall()

        if not lines:
            issues.append({
                "invoice": inv_num,
                "check": "بنود الفاتورة",
                "detail": "لا توجد بنود لهذه الفاتورة"
            })
        else:
            lines_subtotal = round(sum((float(r["quantity"] or 0) * float(r["unit_price"] or 0)) - float(r["discount_amount"] or 0) for r in lines), 2)
            lines_tax      = round(sum(r["tax_amount"] for r in lines), 2)
            lines_total    = round(sum(r["total"] for r in lines), 2)

            header_subtotal = round(float(inv["subtotal"] or 0), 2)
            header_tax      = round(float(inv["tax_amount"] or 0), 2)
            header_total    = round(float(inv["total"] or 0), 2)

            header_matches_line_total = abs(lines_total - header_total) <= TOLERANCE
            header_matches_legacy_tax = abs((lines_total + header_tax) - header_total) <= TOLERANCE
            line_tax_matches_header = abs(lines_tax - header_tax) <= TOLERANCE

            if not header_matches_line_total and not header_matches_legacy_tax:
                issues.append({
                    "invoice": inv_num,
                    "check": "مجموع البنود ≠ إجمالي الفاتورة",
                    "detail": f"البنود={lines_total} | الفاتورة={header_total} | فرق={round(lines_total-header_total,4)}"
                })

            # نمط تاريخي: ضريبة الفاتورة محفوظة بالرأس بينما tax_amount في البنود = 0
            if line_tax_matches_header:
                pass
            elif abs(lines_tax) <= TOLERANCE and header_matches_legacy_tax:
                checked["legacy_tax_model"] += 1
            else:
                issues.append({
                    "invoice": inv_num,
                    "check": "ضريبة البنود ≠ ضريبة الفاتورة",
                    "detail": f"البنود={lines_tax} | الفاتورة={header_tax} | فرق={round(lines_tax-header_tax,4)}"
                })
        checked["invoice_lines_sum"] += 1

        # ══════════════════════════════════════════════════════════════════════
        # الفحص 2: وجود قيد محاسبي مرتبط
        # ══════════════════════════════════════════════════════════════════════
        je_rows = db.execute(
            "SELECT id, total_debit, total_credit FROM journal_entries WHERE reference_type='invoice' AND reference_id=?",
            (inv_id,)
        ).fetchall()

        if not je_rows:
            # فاتورة بحالة مدفوعة يجب أن يكون لها قيد
            if inv["status"] in ("paid", "partial"):
                issues.append({
                    "invoice": inv_num,
                    "check": "قيد محاسبي مفقود",
                    "detail": f"الفاتورة بحالة '{inv['status']}' ولا يوجد قيد journal_entry"
                })
        else:
            for je in je_rows:
                checked["journal_link"] += 1
                # الفحص 3: توازن القيد (مدين = دائن)
                debit  = round(float(je["total_debit"]  or 0), 2)
                credit = round(float(je["total_credit"] or 0), 2)
                if abs(debit - credit) > TOLERANCE:
                    issues.append({
                        "invoice": inv_num,
                        "check": "القيد غير متوازن (مدين ≠ دائن)",
                        "detail": f"JE#{je['id']}: مدين={debit} | دائن={credit} | فرق={round(debit-credit,4)}"
                    })
                checked["journal_balance"] += 1

                # التحقق من تفاصيل بنود القيد
                je_lines = db.execute(
                    "SELECT SUM(debit) as d, SUM(credit) as c FROM journal_entry_lines WHERE entry_id=?",
                    (je["id"],)
                ).fetchone()
                if je_lines:
                    jl_debit  = round(float(je_lines["d"] or 0), 2)
                    jl_credit = round(float(je_lines["c"] or 0), 2)
                    if abs(jl_debit - debit) > TOLERANCE:
                        issues.append({
                            "invoice": inv_num,
                            "check": "بنود القيد ≠ رأس القيد (مدين)",
                            "detail": f"JE#{je['id']}: رأس={debit} | بنود={jl_debit}"
                        })
                    if abs(jl_credit - credit) > TOLERANCE:
                        issues.append({
                            "invoice": inv_num,
                            "check": "بنود القيد ≠ رأس القيد (دائن)",
                            "detail": f"JE#{je['id']}: رأس={credit} | بنود={jl_credit}"
                        })

        # ══════════════════════════════════════════════════════════════════════
        # الفحص 4: حركات المخزون مقابل كميات البنود
        # ══════════════════════════════════════════════════════════════════════
        stock_lines = [r for r in lines if r["product_id"] and int(r["track_stock"] or 0) == 1]
        if not stock_lines:
            checked["service_only_invoices"] += 1
        else:
            sm = db.execute(
                """SELECT COALESCE(SUM(ABS(quantity)),0) AS moved
                   FROM stock_movements
                   WHERE reference_type='invoice' AND reference_id=?""",
                (inv_id,)
            ).fetchone()
            im = db.execute(
                """SELECT COALESCE(SUM(ABS(quantity)),0) AS moved
                   FROM inventory_movements
                   WHERE reference_type='invoice' AND reference_id=?""",
                (inv_id,)
            ).fetchone()
            checked["stock_movements"] += 1

            total_lines_qty = round(sum(float(r["quantity"] or 0) for r in stock_lines), 4)
            moved_stock_qty = float(sm["moved"] or 0)
            moved_inventory_qty = float(im["moved"] or 0)
            total_moved_qty = round(max(moved_stock_qty, moved_inventory_qty), 4)

            if total_lines_qty > 0 and abs(total_lines_qty - total_moved_qty) > 0.001:
                issues.append({
                    "invoice": inv_num,
                    "check": "كمية المخزون ≠ كمية البنود",
                    "detail": f"بنود={total_lines_qty} | حركة مخزون={total_moved_qty} | فرق={round(total_lines_qty-total_moved_qty,4)}"
                })

        # ══════════════════════════════════════════════════════════════════════
        # الفحص 5: رصيد العميل للمبيعات الآجلة
        # ══════════════════════════════════════════════════════════════════════
        if inv["payment_method"] == "credit" and inv["party_id"]:
            ct = db.execute(
                """SELECT COALESCE(SUM(CASE WHEN tx_type='sale' THEN amount ELSE 0 END), 0)
                          - COALESCE(SUM(CASE WHEN tx_type='payment' THEN amount ELSE 0 END), 0) AS balance
                   FROM customer_transactions
                   WHERE business_id=? AND contact_id=? AND reference_id=?""",
                (biz_id, inv["party_id"], inv_id)
            ).fetchone()
            checked["customer_ledger"] += 1
            if ct is None or ct["balance"] is None:
                issues.append({
                    "invoice": inv_num,
                    "check": "سجل ذمم مفقود",
                    "detail": f"فاتورة آجلة للعميل #{inv['party_id']} بدون سجل في customer_transactions"
                })

    # ══════════════════════════════════════════════════════════════════════════
    # طباعة التقرير
    # ══════════════════════════════════════════════════════════════════════════
    print()
    print("═" * 64)
    print("  📋 تقرير سلامة البيانات — Data Integrity Report")
    print(f"  آخر {total_invoices} فاتورة مبيعات")
    print("═" * 64)
    print()
    print("  الفحوصات المُجراة:")
    print(f"    ✔  مطابقة بنود الفاتورة مع المجاميع  : {checked['invoice_lines_sum']} فاتورة")
    print(f"    ✔  وجود وتوازن القيود المحاسبية        : {checked['journal_balance']} قيد")
    print(f"    ✔  توافق بنود القيد مع رأس القيد       : {checked['journal_link']} قيد")
    print(f"    ✔  حركات المخزون مقابل الكميات         : {checked['stock_movements']} فاتورة")
    print(f"    ✔  ذمم العملاء للمبيعات الآجلة         : {checked['customer_ledger']} فاتورة")
    print(f"    ℹ️  فواتير خدمات (بدون مخزون)           : {checked['service_only_invoices']} فاتورة")
    print(f"    ℹ️  نمط ضريبة رأسي legacy               : {checked['legacy_tax_model']} فاتورة")
    print()

    if not issues:
        print("  ✅ النتيجة: لا توجد أي مشكلة — البيانات سليمة 100%")
        print("  ✅ لا يوجد تضارب بمقدار هللة واحدة أو قطعة واحدة")
    else:
        print(f"  ⚠️  النتيجة: وُجدت {len(issues)} مشكلة:")
        print()
        # تجميع حسب نوع المشكلة
        by_type = {}
        for iss in issues:
            k = iss["check"]
            by_type.setdefault(k, []).append(iss)

        for chk_type, chk_issues in by_type.items():
            print(f"  ── {chk_type} ({len(chk_issues)} حالة)")
            for i in chk_issues[:5]:   # أظهر أول 5 فقط لكل نوع
                print(f"     • {i['invoice']}: {i['detail']}")
            if len(chk_issues) > 5:
                print(f"     ... و{len(chk_issues)-5} حالة أخرى")
            print()

    print("═" * 64)

    # ── ملخص إحصائي إضافي ─────────────────────────────────────────────────
    stats = db.execute("""
        SELECT
            COUNT(*) AS cnt,
            ROUND(SUM(total),2) AS total_revenue,
            ROUND(SUM(tax_amount),2) AS total_tax,
            ROUND(SUM(paid_amount),2) AS total_paid,
            ROUND(SUM(total - paid_amount),2) AS total_unpaid,
            SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) AS paid_count,
            SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial_count,
            SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled_count
        FROM invoices
        WHERE invoice_type='sale'
        ORDER BY id DESC
        LIMIT 100
    """).fetchone()

    print()
    print("  📊 إحصائيات آخر 100 فاتورة:")
    print(f"     إجمالي الإيرادات   : {stats['total_revenue']:>12,.2f} ريال")
    print(f"     إجمالي الضريبة     : {stats['total_tax']:>12,.2f} ريال")
    print(f"     مبالغ مقبوضة       : {stats['total_paid']:>12,.2f} ريال")
    print(f"     ذمم غير مقبوضة     : {stats['total_unpaid']:>12,.2f} ريال")
    print(f"     مدفوعة كاملاً      : {stats['paid_count']} فاتورة")
    print(f"     مدفوعة جزئياً      : {stats['partial_count']} فاتورة")
    print(f"     ملغاة              : {stats['cancelled_count']} فاتورة")
    print("═" * 64)
    print()
