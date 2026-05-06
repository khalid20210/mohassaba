#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
_apply_receivables_simple.py — تطبيق migration الذمم (نسخة مبسطة)
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.config import DB_PATH

def apply_migration():
    """تطبيق migration الذمم بشكل مباشر"""
    print("=" * 80)
    print("تطبيق جداول الذمم المتقدمة")
    print("=" * 80)
    
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    # إنشاء الجداول مباشرة
    sql_commands = [
        # 1. أرصدة الذمم
        """CREATE TABLE IF NOT EXISTS receivables_payables_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            summary_type TEXT NOT NULL CHECK(summary_type IN ('receivable', 'payable')),
            opening_balance REAL DEFAULT 0,
            current_balance REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            related_account_id INTEGER REFERENCES accounts(id),
            is_overdue INTEGER DEFAULT 0,
            days_overdue INTEGER DEFAULT 0,
            last_transaction_date TEXT,
            last_payment_date TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, contact_id, summary_type)
        )""",
        
        # 2. حركات الذمم
        """CREATE TABLE IF NOT EXISTS receivables_payables_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            transaction_type TEXT NOT NULL CHECK(transaction_type IN ('invoice', 'payment', 'credit_memo', 'debit_memo', 'write_off')),
            summary_id INTEGER REFERENCES receivables_payables_summary(id),
            reference_number TEXT,
            reference_id INTEGER,
            reference_type TEXT,
            transaction_date TEXT NOT NULL,
            due_date TEXT,
            amount REAL NOT NULL,
            paid_amount REAL DEFAULT 0,
            remaining_balance REAL DEFAULT 0,
            description TEXT,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'partial', 'paid', 'written_off', 'cancelled')),
            posted_at TEXT,
            posted_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )""",
        
        # 3. تخصيص المدفوعات
        """CREATE TABLE IF NOT EXISTS payment_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            payment_id INTEGER NOT NULL REFERENCES receivables_payables_transactions(id) ON DELETE CASCADE,
            transaction_id INTEGER NOT NULL REFERENCES receivables_payables_transactions(id) ON DELETE CASCADE,
            allocated_amount REAL NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        
        # 4. تقارير التقادم
        """CREATE TABLE IF NOT EXISTS aging_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            contact_id INTEGER REFERENCES contacts(id),
            report_type TEXT NOT NULL CHECK(report_type IN ('receivable', 'payable')),
            snapshot_date TEXT NOT NULL,
            current_0_to_30 REAL DEFAULT 0,
            overdue_31_to_60 REAL DEFAULT 0,
            overdue_61_to_90 REAL DEFAULT 0,
            overdue_over_90 REAL DEFAULT 0,
            total_balance REAL DEFAULT 0,
            number_of_transactions INTEGER DEFAULT 0,
            highest_overdue_days INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        
        # 5. سياسات الائتمان
        """CREATE TABLE IF NOT EXISTS credit_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            credit_limit REAL DEFAULT 0,
            credit_used REAL DEFAULT 0,
            available_credit REAL DEFAULT 0,
            payment_terms_days INTEGER DEFAULT 30,
            discount_rate_early REAL DEFAULT 0,
            discount_days INTEGER DEFAULT 10,
            interest_rate_overdue REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, contact_id)
        )""",
        
        # 6. مقاييس الأداء
        """CREATE TABLE IF NOT EXISTS receivables_performance_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            dso REAL DEFAULT 0,
            dpo REAL DEFAULT 0,
            collection_rate REAL DEFAULT 0,
            overdue_ratio REAL DEFAULT 0,
            bad_debt_percentage REAL DEFAULT 0,
            total_receivables REAL DEFAULT 0,
            total_payables REAL DEFAULT 0,
            total_overdue REAL DEFAULT 0,
            total_bad_debts REAL DEFAULT 0,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            snapshot_date TEXT NOT NULL DEFAULT (datetime('now')),
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        
        # 7. شطب الديون المعدومة
        """CREATE TABLE IF NOT EXISTS bad_debt_write_offs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            transaction_id INTEGER NOT NULL REFERENCES receivables_payables_transactions(id) ON DELETE CASCADE,
            write_off_date TEXT NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            approved_by INTEGER REFERENCES users(id),
            approval_date TEXT,
            expense_account_id INTEGER REFERENCES accounts(id),
            journal_entry_id INTEGER REFERENCES journal_entries(id),
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )""",
        
        # 8. التنبيهات
        """CREATE TABLE IF NOT EXISTS receivables_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            alert_type TEXT NOT NULL CHECK(alert_type IN ('credit_limit_exceeded', 'payment_overdue', 'early_warning')),
            description TEXT,
            transaction_id INTEGER REFERENCES receivables_payables_transactions(id),
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'resolved', 'dismissed')),
            severity TEXT DEFAULT 'warning' CHECK(severity IN ('info', 'warning', 'critical')),
            triggered_at TEXT DEFAULT (datetime('now')),
            resolved_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        
        # الفهارس
        "CREATE INDEX IF NOT EXISTS idx_rps_business_type ON receivables_payables_summary(business_id, summary_type)",
        "CREATE INDEX IF NOT EXISTS idx_rps_overdue ON receivables_payables_summary(business_id, is_overdue, days_overdue)",
        "CREATE INDEX IF NOT EXISTS idx_rpt_business_contact ON receivables_payables_transactions(business_id, contact_id)",
        "CREATE INDEX IF NOT EXISTS idx_rpt_status ON receivables_payables_transactions(status, due_date)",
        "CREATE INDEX IF NOT EXISTS idx_pa_payment ON payment_allocations(payment_id)",
        "CREATE INDEX IF NOT EXISTS idx_aging_business_date ON aging_snapshot(business_id, snapshot_date)",
        "CREATE INDEX IF NOT EXISTS idx_credit_policies_contact ON credit_policies(contact_id)",
        "CREATE INDEX IF NOT EXISTS idx_metrics_period ON receivables_performance_metrics(business_id, period_start, period_end)",
        "CREATE INDEX IF NOT EXISTS idx_write_offs_business ON bad_debt_write_offs(business_id, write_off_date)",
        "CREATE INDEX IF NOT EXISTS idx_alerts_active ON receivables_alerts(business_id, status, alert_type)",
    ]
    
    count = 0
    for i, sql in enumerate(sql_commands, 1):
        try:
            db.execute(sql)
            count += 1
            print(f"✅ [{i}/{len(sql_commands)}] تم بنجاح")
        except Exception as e:
            print(f"⚠️  [{i}/{len(sql_commands)}] {str(e)[:60]}")
    
    db.commit()
    db.close()
    
    print(f"\n✅ تم تطبيق جداول الذمم ({count}/{len(sql_commands)} جداول)")
    return True


if __name__ == "__main__":
    apply_migration()
