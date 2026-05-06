"""
setup_centralized_db.py
=======================
إعداد قاعدة البيانات المركزية (PostgreSQL) لنظام المؤسسات
يُشغّل هذا السكريبت مرة واحدة على الخادم المركزي فقط

المعمارية:
  Central DB (PostgreSQL)
    ├─ system_config (إعدادات النظام العام)
    ├─ tenants (500+ منشأة)
    ├─ tenant_databases (معلومات قاعدة بيانات كل منشأة)
    ├─ activities_definitions (196 نشاط + تعريفاتهم)
    ├─ sync_queue (مزامنة الأجهزة)
    └─ audit_log (سجل العمليات)
"""

import os
import sys
import json
from datetime import datetime

# ─── اتصال مركزي (PostgreSQL) ──────────────────────────────────────
def init_central_db():
    """إنشاء قاعدة البيانات المركزية"""
    
    # في الإنتاج الفعلي، استخدم PostgreSQL
    # هنا نستخدم SQLite للتطوير السريع
    import sqlite3
    
    central_db = "database/central_saas.db"
    conn = sqlite3.connect(central_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    c = conn.cursor()
    
    print("=" * 80)
    print("  إعداد نظام المؤسسات SaaS — قاعدة البيانات المركزية")
    print("=" * 80 + "\n")
    
    # ─── 1. إعدادات النظام العام ───────────────────────────────────
    print("[1/5] إنشاء جداول نظام الإدارة المركزية...")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # إدراج إعدادات افتراضية
    default_config = {
        "system_version": "1.0.0-saas",
        "max_tenants": "500",
        "max_pricings_per_item": "5",
        "sync_interval_seconds": "300",
        "offline_cache_days": "30",
        "vat_rates_supported": "[5,10,15,20]",
        "supported_currencies": "[SAR,AED,EGP,KWD]",
    }
    
    for key, val in default_config.items():
        c.execute(
            "INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)",
            (key, val)
        )
    
    conn.commit()
    print("   ✓ إعدادات النظام العام")
    
    # ─── 2. جدول المنشآت (Tenants) ────────────────────────────────
    print("[2/5] إنشاء هيكل جدول المنشآت...")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_key TEXT UNIQUE NOT NULL,  -- معرّف فريد (مثل: biz-001, biz-002)
            name TEXT NOT NULL,
            name_en TEXT,
            country_code TEXT DEFAULT 'SA',
            currency TEXT DEFAULT 'SAR',
            vat_rate REAL DEFAULT 15.0,
            subscription_tier TEXT DEFAULT 'starter',  -- starter, professional, enterprise
            max_users INTEGER DEFAULT 10,
            max_pos_terminals INTEGER DEFAULT 5,
            max_agents INTEGER DEFAULT 20,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS tenant_databases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER UNIQUE NOT NULL,
            db_type TEXT DEFAULT 'sqlite',  -- sqlite | postgresql | mysql
            db_host TEXT,
            db_port INTEGER,
            db_name TEXT,
            db_user TEXT,
            db_password TEXT,  -- مشفرة في الإنتاج
            db_path TEXT,  -- للـ SQLite المحلي
            is_initialized BOOLEAN DEFAULT 0,
            last_sync TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    print("   ✓ جدول المنشآت (Tenants)")
    
    # ─── 3. تعريفات الأنشطة الـ 196 ──────────────────────────────────
    print("[3/5] إنشاء مستودع الأنشطة والخدمات (196 نشاط)...")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS activities_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,  -- مثل: retail_fnb_general, medical_clinic, etc
            name_ar TEXT NOT NULL,
            name_en TEXT,
            category TEXT,  -- retail, services, medical, construction, etc
            sub_category TEXT,
            vat_applicable BOOLEAN DEFAULT 1,
            default_tax_rate REAL DEFAULT 15.0,
            products_template TEXT,  -- JSON: قالب المنتجات الافتراضي
            services_template TEXT,  -- JSON: قالب الخدمات الافتراضية
            accounting_template TEXT,  -- JSON: قالب الحسابات المحاسبية
            pos_enabled BOOLEAN DEFAULT 1,
            inventory_enabled BOOLEAN DEFAULT 1,
            agent_portal_enabled BOOLEAN DEFAULT 1,
            offline_sync_enabled BOOLEAN DEFAULT 1,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # إدراج 196 نشاط (من قاعدة البيانات الموجودة)
    from modules.terminology import _SECTOR_TERMS
    
    activity_count = 0
    for activity_code, activity_data in _SECTOR_TERMS.items():
        c.execute("""
            INSERT OR IGNORE INTO activities_definitions 
            (code, name_ar, name_en, category, sub_category)
            VALUES (?, ?, ?, ?, ?)
        """, (
            activity_code,
            activity_data.get("name_ar", activity_code),
            activity_data.get("name_en", activity_code),
            activity_data.get("category", "other"),
            activity_data.get("sub_category", ""),
        ))
        activity_count += 1
    
    conn.commit()
    print(f"   ✓ أضيف {activity_count} نشاط في مستودع الأنشطة")
    
    # ─── 4. جدول المزامنة ─────────────────────────────────────────
    print("[4/5] إنشاء نظام المزامنة...")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            device_id TEXT NOT NULL,  -- معرّف الجهاز (POS / Cashier / Agent)
            sync_type TEXT NOT NULL,  -- push | pull | bidirectional
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,  -- INSERT | UPDATE | DELETE
            record_id INTEGER,
            data_json TEXT,  -- البيانات المراد مزامنتها
            status TEXT DEFAULT 'pending',  -- pending | processing | completed | failed
            attempt_count INTEGER DEFAULT 0,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY(tenant_id) REFERENCES tenants(id)
        )
    """)
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_tenant_status 
        ON sync_queue(tenant_id, status)
    """)
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_sync_device 
        ON sync_queue(device_id, created_at)
    """)
    
    conn.commit()
    print("   ✓ نظام المزامنة")
    
    # ─── 5. سجل التدقيق ───────────────────────────────────────────
    print("[5/5] إنشاء سجل التدقيق...")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            user_id INTEGER,
            action TEXT NOT NULL,  -- login | logout | create | update | delete | sync
            resource TEXT,  -- invoice | product | customer | agent
            resource_id INTEGER,
            details TEXT,  -- JSON
            ip_address TEXT,
            status TEXT DEFAULT 'success',  -- success | failed
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tenant_id) REFERENCES tenants(id)
        )
    """)
    
    conn.commit()
    print("   ✓ سجل التدقيق\n")
    
    # ─── إدراج نموذج منشأة تجريبي ─────────────────────────────────
    print("=" * 80)
    print("  إدراج نموذج منشأة تجريبي...")
    print("=" * 80 + "\n")
    
    # أضف منشأة تجريبية
    c.execute("""
        INSERT OR IGNORE INTO tenants 
        (tenant_key, name, name_en, country_code, currency, vat_rate, subscription_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "biz-001",
        "شركة الجنان التجارية",
        "Al-Jinan Trading Co.",
        "SA",
        "SAR",
        15.0,
        "professional"
    ))
    
    demo_tenant = c.execute(
        "SELECT id FROM tenants WHERE tenant_key='biz-001'"
    ).fetchone()
    
    if demo_tenant:
        demo_tenant_id = demo_tenant["id"]
        print(f"✓ منشأة تجريبية: biz-001 (ID: {demo_tenant_id})\n")
        
        # إنشاء قاعدة بيانات محلية للمنشأة التجريبية
        c.execute("""
            INSERT OR IGNORE INTO tenant_databases 
            (tenant_id, db_type, db_name, db_path)
            VALUES (?, 'sqlite', 'tenant_biz001', 'database/tenant_biz001.db')
        """, (demo_tenant_id,))
        
        conn.commit()
        print(f"✓ قاعدة بيانات محلية: database/tenant_biz001.db\n")
    
    print("=" * 80)
    print("  المعلومات الأساسية:")
    print("=" * 80)
    print(f"""
قاعدة البيانات المركزية: {central_db}

جداول رئيسية:
  • system_config .......... إعدادات النظام العام
  • tenants ............... قائمة المنشآت (500+ منشأة)
  • tenant_databases ...... معلومات قاعدة بيانات كل منشأة
  • activities_definitions . تعريفات 196 نشاط
  • sync_queue ............ قائمة المزامنة
  • audit_log ............ سجل التدقيق

الاتصال:
  Type: SQLite (للتطوير) / PostgreSQL (للإنتاج)
  Path: {central_db}
  Mode: WAL (Write-Ahead Logging) ✓

التالي:
  1. تشغيل setup_tenant_local.py على كل جهاز (POS/Cashier/Agent)
  2. تشغيل app.py متعدد المنشآت
  3. اختبار المزامنة الأوفلاين/الأونلاين
""")
    
    conn.close()
    return True


if __name__ == "__main__":
    try:
        result = init_central_db()
        if result:
            print("✅ تم إعداد النظام المركزي بنجاح!")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
