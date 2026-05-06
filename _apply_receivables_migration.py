#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
_apply_receivables_migration.py — تطبيق migration الذمم المتقدمة
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.config import DB_PATH

def apply_migration():
    """تطبيق migration الذمم"""
    print("=" * 80)
    print("تطبيق Migration: الذمم المتقدمة (Advanced Receivables)")
    print("=" * 80)
    
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        
        # قراءة ملف Migration
        migration_file = os.path.join(
            os.path.dirname(__file__),
            "migrations/016_advanced_receivables_payables.sql"
        )
        
        with open(migration_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # تقسيم الأوامر وتنفيذها
        statements = sql_content.split(';')
        count = 0
        
        for statement in statements:
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    db.execute(statement)
                    count += 1
                except sqlite3.OperationalError as e:
                    if 'already exists' in str(e):
                        print(f"⚠️ {e}")
                    else:
                        raise
                for statement in statements:
                    statement = statement.strip()
                    if statement and not statement.startswith('--') and not statement.startswith('PRAGMA'):
                        try:
                            db.execute(statement)
                            count += 1
                        except sqlite3.OperationalError as e:
                            error_msg = str(e).lower()
                            if 'already exists' in error_msg or 'duplicate column' in error_msg or 'no such table' in error_msg:
                                print(f"⚠️ تخطي: {e}")
                            else:
                                print(f"❌ خطأ في السطر: {statement[:50]}... -> {e}")
                                raise
        
        db.commit()
        db.close()
        
        print(f"\n✅ تم تطبيق Migration بنجاح ({count} أوامر SQL)")
        return True
        
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = apply_migration()
    sys.exit(0 if success else 1)
