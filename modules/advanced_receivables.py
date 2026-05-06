"""
modules/advanced_receivables.py — نظام متقدم للذمم المدينة والدائنة

الميزات:
  • تتبع الأرصدة الديناميكية (مدينة + دائنة)
  • تقارير التقادم (Aging Reports: 0-30, 31-60, 61-90, 90+)
  • تحليل الأداء (DSO, DPO, Collection Rate)
  • تحذيرات تلقائية
  • معالجة الديون المعدومة (Write-offs)
  • سياسات الائتمان

السياق: كل عميل/مورد يمكن أن يكون له ذمة مدينة (للعملاء) أو دائنة (للموردين)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List
import sqlite3

_log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1: إدارة أرصدة الذمم
# ════════════════════════════════════════════════════════════════════════════

def get_contact_balance(db: sqlite3.Connection, business_id: int, contact_id: int,
                        summary_type: str = 'receivable') -> Dict:
    """
    الحصول على رصيد العميل/المورد الحالي
    
    summary_type: 'receivable' (مدينة) أو 'payable' (دائنة)
    """
    summary = db.execute(
        """SELECT * FROM receivables_payables_summary
           WHERE business_id=? AND contact_id=? AND summary_type=?""",
        (business_id, contact_id, summary_type)
    ).fetchone()
    
    if not summary:
        return {
            'contact_id': contact_id,
            'summary_type': summary_type,
            'current_balance': 0,
            'opening_balance': 0,
            'paid_amount': 0,
            'is_overdue': False,
            'days_overdue': 0,
        }
    
    return {
        'id': summary['id'],
        'contact_id': summary['contact_id'],
        'summary_type': summary['summary_type'],
        'current_balance': float(summary['current_balance'] or 0),
        'opening_balance': float(summary['opening_balance'] or 0),
        'paid_amount': float(summary['paid_amount'] or 0),
        'is_overdue': bool(summary['is_overdue']),
        'days_overdue': summary['days_overdue'] or 0,
        'last_transaction_date': summary['last_transaction_date'],
        'last_payment_date': summary['last_payment_date'],
    }


def create_receivable_transaction(db: sqlite3.Connection, business_id: int,
                                 contact_id: int, transaction_type: str,
                                 amount: float, invoice_number: str,
                                 due_date: Optional[str] = None,
                                 reference_id: Optional[int] = None,
                                 notes: str = "") -> int:
    """
    إنشاء حركة ذمة جديدة (فاتورة بيع = ذمة مدينة)
    
    transaction_type: 'invoice', 'payment', 'credit_memo', 'debit_memo', 'write_off'
    """
    now = datetime.now().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if not due_date:
        # الحد الافتراضي 30 يوم
        due_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    
    # تحديد الحالة الأولية
    status = 'open' if amount > 0 else 'paid'
    remaining_balance = amount if amount > 0 else 0
    
    db.execute(
        """INSERT INTO receivables_payables_transactions
           (business_id, contact_id, transaction_type, reference_number,
            reference_id, transaction_date, due_date, amount, remaining_balance,
            status, description, notes, posted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (business_id, contact_id, transaction_type, invoice_number, reference_id,
         today, due_date, amount, remaining_balance,
         status, f"{transaction_type} - {invoice_number}", notes, now)
    )
    
    trans_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # تحديث الملخص
    _update_summary(db, business_id, contact_id, 'receivable')
    
    _log.info(f"تم إنشاء حركة ذمة: biz={business_id}, contact={contact_id}, "
              f"type={transaction_type}, amount={amount}, id={trans_id}")
    
    return trans_id


def record_payment(db: sqlite3.Connection, business_id: int, contact_id: int,
                  payment_amount: float, reference_number: str,
                  notes: str = "") -> Tuple[int, float]:
    """
    تسجيل دفعة/استقبال مبلغ
    
    Returns: (payment_transaction_id, remaining_balance)
    """
    now = datetime.now().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # إنشاء حركة الدفعة
    db.execute(
        """INSERT INTO receivables_payables_transactions
           (business_id, contact_id, transaction_type, reference_number,
            transaction_date, amount, remaining_balance, status, notes, posted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (business_id, contact_id, 'payment', reference_number,
         today, payment_amount, 0, 'paid', notes, now)
    )
    
    payment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # تخصيص المبلغ على الفواتير المفتوحة
    remaining = payment_amount
    open_invoices = db.execute(
        """SELECT id, remaining_balance FROM receivables_payables_transactions
           WHERE business_id=? AND contact_id=? AND status IN ('open', 'partial')
           AND transaction_type IN ('invoice', 'debit_memo')
           ORDER BY due_date ASC, id ASC""",
        (business_id, contact_id)
    ).fetchall()
    
    for invoice in open_invoices:
        if remaining <= 0:
            break
        
        invoice_id = invoice['id']
        outstanding = float(invoice['remaining_balance'] or 0)
        
        # تحديد المبلغ المخصص
        allocated = min(remaining, outstanding)
        new_balance = outstanding - allocated
        remaining -= allocated
        
        # تحديث الفاتورة
        new_status = 'paid' if new_balance <= 0 else 'partial'
        db.execute(
            """UPDATE receivables_payables_transactions
               SET paid_amount = paid_amount + ?,
                   remaining_balance = ?,
                   status = ?
               WHERE id=?""",
            (allocated, max(0, new_balance), new_status, invoice_id)
        )
        
        # تسجيل التخصيص
        db.execute(
            """INSERT INTO payment_allocations
               (business_id, payment_id, transaction_id, allocated_amount)
               VALUES (?,?,?,?)""",
            (business_id, payment_id, invoice_id, allocated)
        )
    
    # تحديث الملخص
    _update_summary(db, business_id, contact_id, 'receivable')
    
    _log.info(f"تم تسجيل دفعة: biz={business_id}, contact={contact_id}, "
              f"amount={payment_amount}, payment_id={payment_id}")
    
    return payment_id, remaining


def _update_summary(db: sqlite3.Connection, business_id: int, contact_id: int,
                   summary_type: str = 'receivable'):
    """تحديث ملخص الذمة بناءً على الحركات"""
    # حساب الرصيد الحالي
    trans = db.execute(
        """SELECT 
             SUM(CASE WHEN transaction_type='invoice' THEN amount ELSE 0 END) as invoices,
             SUM(CASE WHEN transaction_type='payment' THEN amount ELSE 0 END) as payments,
             SUM(remaining_balance) as open_balance,
             MAX(transaction_date) as last_trans,
             MAX(CASE WHEN transaction_type='payment' THEN transaction_date ELSE NULL END) as last_pay
           FROM receivables_payables_transactions
           WHERE business_id=? AND contact_id=? AND status != 'cancelled'""",
        (business_id, contact_id)
    ).fetchone()
    
    current_balance = float(trans['open_balance'] or 0)
    last_trans_date = trans['last_trans']
    last_pay_date = trans['last_pay']
    
    # حساب التأخر (overdue)
    is_overdue = False
    days_overdue = 0
    if current_balance > 0:
        overdue_trans = db.execute(
            """SELECT MAX(CAST((date('now') - due_date) AS INTEGER)) as max_days
               FROM receivables_payables_transactions
               WHERE business_id=? AND contact_id=? AND status IN ('open', 'partial')
               AND due_date < date('now')""",
            (business_id, contact_id)
        ).fetchone()
        
        if overdue_trans and overdue_trans['max_days']:
            days_overdue = max(0, overdue_trans['max_days'])
            is_overdue = days_overdue > 0
    
    # تحديث أو إنشاء الملخص
    existing = db.execute(
        """SELECT id FROM receivables_payables_summary
           WHERE business_id=? AND contact_id=? AND summary_type=?""",
        (business_id, contact_id, summary_type)
    ).fetchone()
    
    if existing:
        db.execute(
            """UPDATE receivables_payables_summary
               SET current_balance=?, is_overdue=?, days_overdue=?,
                   last_transaction_date=?, last_payment_date=?, updated_at=datetime('now')
               WHERE business_id=? AND contact_id=? AND summary_type=?""",
            (current_balance, is_overdue, days_overdue, last_trans_date, last_pay_date,
             business_id, contact_id, summary_type)
        )
    else:
        db.execute(
            """INSERT INTO receivables_payables_summary
               (business_id, contact_id, summary_type, current_balance,
                is_overdue, days_overdue, last_transaction_date, last_payment_date)
               VALUES (?,?,?,?,?,?,?,?)""",
            (business_id, contact_id, summary_type, current_balance,
             is_overdue, days_overdue, last_trans_date, last_pay_date)
        )
    
    db.commit()


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2: تقارير التقادم (Aging Reports)
# ════════════════════════════════════════════════════════════════════════════

def generate_aging_report(db: sqlite3.Connection, business_id: int,
                         report_type: str = 'receivable') -> Dict:
    """
    إنشاء تقرير التقادم
    
    النتائج مصنفة حسب:
    - 0-30 يوم (current)
    - 31-60 يوم
    - 61-90 يوم
    - 90+ يوم
    """
    today = datetime.now().strftime("%Y-%m-%d")
    
    # حساب النطاقات
    ranges = {
        '0-30': (0, 30),
        '31-60': (31, 60),
        '61-90': (61, 90),
        '90+': (91, 9999),
    }
    
    aging_data = {}
    grand_total = 0
    
    for range_name, (min_days, max_days) in ranges.items():
        if range_name == '0-30':
            result = db.execute(
                """SELECT 
                     COUNT(*) as count,
                     SUM(remaining_balance) as total
                   FROM receivables_payables_transactions
                   WHERE business_id=? AND status IN ('open', 'partial')
                   AND (due_date > ? OR due_date = ?)""",
                (business_id, today, today)
            ).fetchone()
        else:
            result = db.execute(
                """SELECT 
                     COUNT(*) as count,
                     SUM(remaining_balance) as total
                   FROM receivables_payables_transactions
                   WHERE business_id=? AND status IN ('open', 'partial')
                   AND CAST((date(?) - due_date) AS INTEGER) BETWEEN ? AND ?""",
                (business_id, today, min_days, max_days)
            ).fetchone()
        
        amount = float(result['total'] or 0)
        aging_data[range_name] = {
            'count': result['count'] or 0,
            'amount': amount,
        }
        grand_total += amount
    
    return {
        'report_type': report_type,
        'report_date': today,
        'aging': aging_data,
        'grand_total': grand_total,
    }


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3: مقاييس الأداء (Performance Metrics)
# ════════════════════════════════════════════════════════════════════════════

def calculate_performance_metrics(db: sqlite3.Connection, business_id: int,
                                 period_start: str, period_end: str) -> Dict:
    """
    حساب مقاييس الأداء:
    - DSO: Days Sales Outstanding
    - DPO: Days Payable Outstanding
    - Collection Rate: نسبة التحصيل
    """
    
    # إجمالي المبيعات
    sales = db.execute(
        """SELECT SUM(amount) as total FROM receivables_payables_transactions
           WHERE business_id=? AND transaction_type='invoice'
           AND DATE(transaction_date) BETWEEN ? AND ?""",
        (business_id, period_start, period_end)
    ).fetchone()['total'] or 0
    
    # إجمالي التحصيلات
    collections = db.execute(
        """SELECT SUM(amount) as total FROM receivables_payables_transactions
           WHERE business_id=? AND transaction_type='payment'
           AND DATE(transaction_date) BETWEEN ? AND ?""",
        (business_id, period_start, period_end)
    ).fetchone()['total'] or 0
    
    # أرصدة مدينة مفتوحة
    open_receivables = db.execute(
        """SELECT SUM(remaining_balance) as total FROM receivables_payables_transactions
           WHERE business_id=? AND status IN ('open', 'partial')
           AND transaction_type IN ('invoice', 'debit_memo')""",
        (business_id,)
    ).fetchone()['total'] or 0
    
    # الديون المعدومة
    bad_debts = db.execute(
        """SELECT SUM(amount) as total FROM bad_debt_write_offs
           WHERE business_id=? AND DATE(write_off_date) BETWEEN ? AND ?""",
        (business_id, period_start, period_end)
    ).fetchone()['total'] or 0
    
    # الحسابات
    days_in_period = (datetime.strptime(period_end, "%Y-%m-%d") -
                     datetime.strptime(period_start, "%Y-%m-%d")).days + 1
    
    dso = (open_receivables / sales * days_in_period) if sales > 0 else 0
    collection_rate = (collections / sales * 100) if sales > 0 else 0
    bad_debt_percentage = (bad_debts / sales * 100) if sales > 0 else 0
    
    return {
        'period_start': period_start,
        'period_end': period_end,
        'total_sales': float(sales),
        'total_collections': float(collections),
        'dso': round(dso, 2),
        'collection_rate': round(collection_rate, 2),
        'open_receivables': float(open_receivables),
        'bad_debt_percentage': round(bad_debt_percentage, 2),
        'bad_debts': float(bad_debts),
    }


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4: معالجة الديون المعدومة (Write-offs)
# ════════════════════════════════════════════════════════════════════════════

def write_off_bad_debt(db: sqlite3.Connection, business_id: int,
                      transaction_id: int, amount: float,
                      reason: str, expense_account_id: int,
                      user_id: int) -> int:
    """
    شطب دين معدوم (خلق قيد محاسبي وتحديث الحركة)
    """
    from .extensions import get_account_id, next_entry_number
    
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().isoformat()
    
    # إنشاء قيد محاسبي
    entry_num = next_entry_number(db, business_id)
    db.execute(
        """INSERT INTO journal_entries
           (business_id, entry_number, entry_date, description,
            reference_type, reference_id, total_debit, total_credit, is_posted, created_by, posted_at)
           VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
        (business_id, entry_num, today,
         f"شطب دين معدوم - {reason}",
         "write_off", transaction_id, amount, amount, user_id, now)
    )
    
    je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # إضافة سطري القيد
    account_id = get_account_id(db, business_id, "2102")  # ذمم دائنة
    
    if account_id and expense_account_id:
        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,1)""",
            (je_id, account_id, f"شطب - {reason}", amount, 0)
        )
        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,2)""",
            (je_id, expense_account_id, f"مصروف شطب ديون", 0, amount)
        )
    
    # تسجيل الشطب
    db.execute(
        """INSERT INTO bad_debt_write_offs
           (business_id, transaction_id, write_off_date, amount, reason,
            approved_by, approval_date, journal_entry_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        (business_id, transaction_id, today, amount, reason, user_id, today, je_id)
    )
    
    write_off_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # تحديث الحركة الأصلية
    db.execute(
        """UPDATE receivables_payables_transactions
           SET status='written_off', remaining_balance=0
           WHERE id=?""",
        (transaction_id,)
    )
    
    _log.info(f"تم شطب دين: biz={business_id}, trans={transaction_id}, "
              f"amount={amount}, reason={reason}")
    
    return write_off_id


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5: التحذيرات (Alerts)
# ════════════════════════════════════════════════════════════════════════════

def check_credit_alerts(db: sqlite3.Connection, business_id: int) -> List[Dict]:
    """
    فحص جميع التنبيهات الائتمانية
    """
    alerts = []
    
    # 1. فحص تجاوز حد الائتمان
    exceeded = db.execute(
        """SELECT c.id, c.name, cp.credit_limit, rps.current_balance
           FROM contacts c
           LEFT JOIN credit_policies cp ON c.id=cp.contact_id AND cp.business_id=?
           LEFT JOIN receivables_payables_summary rps 
             ON c.id=rps.contact_id AND rps.business_id=? AND rps.summary_type='receivable'
           WHERE c.business_id=?
           AND cp.credit_limit > 0
           AND rps.current_balance > cp.credit_limit""",
        (business_id, business_id, business_id)
    ).fetchall()
    
    for row in exceeded:
        alerts.append({
            'type': 'credit_limit_exceeded',
            'contact_id': row['id'],
            'contact_name': row['name'],
            'severity': 'critical',
            'message': f"تم تجاوز حد الائتمان: {row['current_balance']:.2f} من {row['credit_limit']:.2f}",
        })
    
    # 2. فحص الفواتير المتأخرة
    overdue = db.execute(
        """SELECT c.id, c.name, SUM(rpt.remaining_balance) as overdue_amount,
                  MAX(CAST((date('now') - rpt.due_date) AS INTEGER)) as days_overdue
           FROM contacts c
           JOIN receivables_payables_transactions rpt 
             ON c.id=rpt.contact_id AND rpt.business_id=?
           WHERE rpt.status IN ('open', 'partial') AND rpt.due_date < date('now')
           GROUP BY c.id
           HAVING days_overdue > 30""",
        (business_id,)
    ).fetchall()
    
    for row in overdue:
        alerts.append({
            'type': 'payment_overdue',
            'contact_id': row['id'],
            'contact_name': row['name'],
            'severity': 'warning',
            'message': f"فاتورة متأخرة {row['days_overdue']} يوم: {row['overdue_amount']:.2f}",
        })
    
    return alerts
