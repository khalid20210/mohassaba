"""
setup_products_table.py
======================
إعداد جدول المنتجات في قاعدة البيانات المركزية
مع ربط الأنشطة والفئات
"""

import sqlite3
import sys
import io
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("\n" + "="*80)
print("  إعداد جدول المنتجات في قاعدة البيانات المركزية")
print("="*80 + "\n")

RECREATE_MODE = "--recreate" in sys.argv

conn = sqlite3.connect("database/central_saas.db")
c = conn.cursor()

try:
    table_exists = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='products_bulk'"
    ).fetchone() is not None

    if RECREATE_MODE and table_exists:
        backup_table = f"products_bulk_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        c.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM products_bulk")
        c.execute("DROP TABLE products_bulk")
        print(f"✓ تم أخذ نسخة احتياطية إلى {backup_table} ثم إعادة إنشاء الجدول")
    elif table_exists:
        print("✓ الجدول products_bulk موجود مسبقاً — لن يتم حذفه بدون --recreate")
    
    # إنشاء جدول المنتجات الجديد
    c.execute("""
        CREATE TABLE IF NOT EXISTS products_bulk (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name_ar TEXT NOT NULL,
            name_en TEXT NOT NULL,
            activity_id INTEGER,
            activity_code TEXT,
            category TEXT,
            sub_category TEXT,
            unit TEXT NOT NULL,
            price REAL DEFAULT 0,
            cost REAL DEFAULT 0,
            stock INTEGER DEFAULT 0,
            barcode TEXT,
            sku TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            synced_at TIMESTAMP,
            sync_status TEXT DEFAULT 'pending',
            
            FOREIGN KEY (activity_id) REFERENCES activities_definitions(id)
        )
    """)
    
    # إنشاء الفهارس لتسريع البحث
    c.execute("CREATE INDEX IF NOT EXISTS idx_products_code ON products_bulk(code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_products_activity ON products_bulk(activity_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products_bulk(category)")
    
    print("✓ تم إنشاء جدول products_bulk")
    print("✓ تم إنشاء الفهارس (indexes)")
    
    # إنشاء جدول سجل الأخطاء
    c.execute("""
        CREATE TABLE IF NOT EXISTS import_error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            product_id TEXT,
            error_type TEXT,
            error_details TEXT,
            row_data TEXT
        )
    """)
    
    print("✓ تم إنشاء جدول سجل الأخطاء")
    
    # إنشاء جدول إحصائيات الاستيراد
    c.execute("""
        CREATE TABLE IF NOT EXISTS import_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_rows INTEGER,
            imported_count INTEGER,
            duplicate_count INTEGER,
            error_count INTEGER,
            skipped_count INTEGER,
            success_rate REAL,
            csv_file TEXT
        )
    """)
    
    print("✓ تم إنشاء جدول إحصائيات الاستيراد")
    
    conn.commit()
    
    # عرض معلومات الجدول
    print("\n" + "="*80)
    print("  معلومات الجدول المُنشأ:")
    print("="*80 + "\n")
    
    schema = c.execute("PRAGMA table_info(products_bulk)").fetchall()
    print("📋 أعمدة جدول products_bulk:\n")
    
    for col in schema:
        col_name = col[1]
        col_type = col[2]
        is_null = "NULL" if col[3] == 0 else "NOT NULL"
        default = f" = {col[4]}" if col[4] else ""
        print(f"  • {col_name:20} {col_type:15} {is_null:15}{default}")
    
    print("\n" + "="*80)
    print("✅ تم إعداد جداول المنتجات بنجاح!")
    print("="*80 + "\n")
    
except Exception as e:
    print(f"❌ خطأ: {e}")
    conn.rollback()
finally:
    conn.close()
