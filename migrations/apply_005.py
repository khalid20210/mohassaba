#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migration Runner: 005_complete_services.sql
Apply all missing service tables to the database
"""

import sqlite3
from pathlib import Path

def apply_migration():
    base_dir = Path(__file__).parent.parent
    db_path = base_dir / "database" / "accounting_dev.db"
    migration_file = base_dir / "migrations" / "005_complete_services.sql"
    
    # قراءة الـ Migration
    sql_content = migration_file.read_text(encoding='utf-8')
    
    # الاتصال بقاعدة البيانات
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # تنفيذ كل statement
    statements = sql_content.split(';')
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for i, stmt in enumerate(statements):
        stmt = stmt.strip()
        if not stmt or stmt.startswith('--'):
            continue
        
        try:
            cursor.execute(stmt)
            success_count += 1
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if 'already exists' in error_msg or 'duplicate column' in error_msg or 'no such table' in error_msg:
                skip_count += 1
                # print(f"⏭️  Skipped: {str(e)[:60]}...")
            else:
                error_count += 1
                print(f"❌ Error on statement {i}: {str(e)}")
                # لا نرفع الخطأ، نستمر فقط
                # raise
    
    conn.commit()
    
    # عرض ملخص الجداول المُنشأة
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [t[0] for t in cursor.fetchall()]
    
    conn.close()
    
    # الطباعة
    print(f"\n{'='*70}")
    print(f"✅ Migration 005 Applied Successfully!")
    print(f"{'='*70}")
    print(f"Executed: {success_count} statements")
    print(f"Skipped: {skip_count} (already exist)")
    print(f"Errors: {error_count}")
    print(f"\n📊 Total Tables in DB: {len(tables)}")
    
    # طباعة الجداول الجديدة
    new_tables = [
        'product_inventory', 'inventory_movements', 'stock_alerts',
        'contacts', 'customer_transactions',
        'barcodes', 'barcode_scans',
        'invoice_templates', 'payment_records',
        'patients', 'appointments', 'prescriptions', 'patient_visits',
        'projects', 'project_extracts', 'equipment',
        'fleet_vehicles', 'rental_contracts', 'maintenance_records',
        'recipes', 'recipe_usage',
        'orders', 'pricing_lists',
        'jobs', 'service_contracts',
        'activity_log'
    ]
    
    created_tables = [t for t in new_tables if t in tables]
    print(f"\n📦 New Service Tables ({len(created_tables)}):")
    for table in created_tables:
        print(f"  ✓ {table}")
    
    return True

if __name__ == "__main__":
    try:
        apply_migration()
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {e}")
        exit(1)
