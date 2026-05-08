"""
setup_production.py
==================
سكريبت الإعداد الكامل للإنتاج الحقيقي

يُعدّ هذا السكريبت منشأتك الحقيقية الأولى:
  • حساب المالك مع كلمة مرور قوية
  • إعداد المنشأة: الاسم، الرقم الضريبي، السجل التجاري
  • مندوب مع صلاحيات كاملة وبيانات الشركة للفواتير
  • كاشيرين (POS)
  • فروع متعددة جاهزة
  • بذر 196 نشاط بمنتجات وخدمات حقيقية
  • إعداد حسابات محاسبية كاملة
"""

import sqlite3
import hashlib
import os
import sys

# ─── التحقق من تشغيل السكريبت من المجلد الصحيح ──────────────────────────────
DB_PATH = "database/accounting_dev.db"
if not os.path.exists(DB_PATH):
    print(f"ERROR: DB not found at {DB_PATH}")
    print("شغّل السكريبت من مجلد المشروع الرئيسي")
    sys.exit(1)


def _hash_password(password: str) -> str:
    """تشفير كلمة المرور بنفس الطريقة المستخدمة في النظام"""
    salt = os.urandom(32).hex()
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "*" * len(secret)
    return f"{secret[:2]}{'*' * (len(secret) - 4)}{secret[-2:]}"


def _has_insecure_defaults(config: dict) -> bool:
    default_passwords = {"Admin@2026!", "Cash@2026!", "Agent@2026!"}

    owner_pw = config.get("owner_password", "")
    if owner_pw in default_passwords:
        return True

    for cashier in config.get("cashiers", []):
        if cashier.get("password", "") in default_passwords:
            return True

    for agent in config.get("agents", []):
        if agent.get("password", "") in default_passwords:
            return True

    return False


def setup_production(config: dict):
    """
    الإعداد الشامل للإنتاج
    config: قاموس بيانات المنشأة والمستخدمين
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    c = conn.cursor()

    print("\n" + "=" * 70)
    print("   جنان بيز — إعداد الإنتاج الحقيقي")
    print("=" * 70 + "\n")

    # ─────────────────────────────────────────────────────────────
    # 1. إعداد/تحديث المنشأة الرئيسية
    # ─────────────────────────────────────────────────────────────
    print("[1/7] إعداد المنشأة الرئيسية...")

    biz = c.execute("SELECT id FROM businesses WHERE id=1").fetchone()
    if biz:
        c.execute("""
            UPDATE businesses SET
                name = ?,
                name_en = ?,
                tax_number = ?,
                cr_number = ?,
                phone = ?,
                email = ?,
                address = ?,
                city = ?,
                country = ?,
                country_code = ?,
                currency = ?,
                industry_type = ?,
                is_active = 1,
                updated_at = datetime('now')
            WHERE id = 1
        """, (
            config["biz_name"],
            config.get("biz_name_en", ""),
            config["tax_number"],
            config["cr_number"],
            config["biz_phone"],
            config.get("biz_email", ""),
            config.get("biz_address", ""),
            config.get("biz_city", "الرياض"),
            config.get("biz_country", "SA"),
            config.get("country_code", "SA"),
            config.get("currency", "SAR"),
            config.get("industry_type", "retail_fnb_general"),
        ))
        biz_id = 1
    else:
        c.execute("""
            INSERT INTO businesses (
                name, name_en, tax_number, cr_number, phone, email,
                address, city, country, country_code, currency,
                industry_type, is_active, created_at, updated_at,
                fiscal_year_start
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,datetime('now'),datetime('now'),'01-01')
        """, (
            config["biz_name"], config.get("biz_name_en", ""),
            config["tax_number"], config["cr_number"],
            config["biz_phone"], config.get("biz_email", ""),
            config.get("biz_address", ""), config.get("biz_city", "الرياض"),
            config.get("biz_country", "SA"), config.get("country_code", "SA"),
            config.get("currency", "SAR"), config.get("industry_type", "retail_fnb_general"),
        ))
        biz_id = c.lastrowid

    conn.commit()
    print(f"   + المنشأة: {config['biz_name']} (ID: {biz_id})")
    print(f"   + الرقم الضريبي: {config['tax_number']}")
    print(f"   + السجل التجاري: {config['cr_number']}")

    # ─────────────────────────────────────────────────────────────
    # 2. إعداد المالك/الأدمن الرئيسي
    # ─────────────────────────────────────────────────────────────
    print("\n[2/7] إعداد حساب المالك...")

    existing_owner = c.execute(
        "SELECT id FROM users WHERE business_id=? AND level='owner' LIMIT 1", (biz_id,)
    ).fetchone()

    owner_pass_hash = _hash_password(config["owner_password"])

    if existing_owner:
        c.execute("""
            UPDATE users SET
                username = ?,
                full_name = ?,
                email = ?,
                phone = ?,
                password_hash = ?,
                is_active = 1
            WHERE id = ?
        """, (
            config["owner_username"],
            config["owner_name"],
            config.get("owner_email", ""),
            config.get("owner_phone", ""),
            owner_pass_hash,
            existing_owner["id"]
        ))
        owner_id = existing_owner["id"]
    else:
        # احصل على role_id للمالك
        owner_role = c.execute(
            "SELECT id FROM roles WHERE business_id=? AND name='owner' LIMIT 1", (biz_id,)
        ).fetchone()
        role_id = owner_role["id"] if owner_role else 1

        c.execute("""
            INSERT INTO users (business_id, role_id, username, full_name, email, phone,
                               password_hash, is_active, level, created_at)
            VALUES (?,?,?,?,?,?,?,1,'owner',datetime('now'))
        """, (
            biz_id, role_id,
            config["owner_username"],
            config["owner_name"],
            config.get("owner_email", ""),
            config.get("owner_phone", ""),
            owner_pass_hash,
        ))
        owner_id = c.lastrowid

    conn.commit()
    print(f"   + المالك: {config['owner_name']}")
    print(f"   + اسم المستخدم: {config['owner_username']}")
    print(f"   + كلمة المرور: {_mask_secret(config['owner_password'])}")

    # ─────────────────────────────────────────────────────────────
    # 3. إعداد الفروع
    # ─────────────────────────────────────────────────────────────
    print("\n[3/7] إعداد الفروع...")

    branches_added = 0
    for branch in config.get("branches", []):
        # تحقق من وجود جدول الفروع
        table_exists = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='warehouses'"
        ).fetchone()

        if table_exists:
            existing = c.execute(
                "SELECT id FROM warehouses WHERE business_id=? AND name=?",
                (biz_id, branch["name"])
            ).fetchone()
            if not existing:
                c.execute("""
                    INSERT INTO warehouses (business_id, name, location, is_default, is_active)
                    VALUES (?,?,?,?,1)
                """, (biz_id, branch["name"], branch.get("location", ""), 1 if branches_added == 0 else 0))
                branches_added += 1
                print(f"   + فرع: {branch['name']}")

    conn.commit()

    # ─────────────────────────────────────────────────────────────
    # 4. إعداد الكاشيرين
    # ─────────────────────────────────────────────────────────────
    print("\n[4/7] إعداد الكاشيرين...")

    cashier_role = c.execute(
        "SELECT id FROM roles WHERE business_id=? AND name='cashier' LIMIT 1", (biz_id,)
    ).fetchone()
    cashier_role_id = cashier_role["id"] if cashier_role else None

    for cashier in config.get("cashiers", []):
        existing = c.execute(
            "SELECT id FROM users WHERE business_id=? AND username=?",
            (biz_id, cashier["username"])
        ).fetchone()

        if not existing:
            pass_hash = _hash_password(cashier["password"])
            c.execute("""
                INSERT INTO users (business_id, role_id, username, full_name, phone,
                                   password_hash, is_active, level, created_at)
                VALUES (?,?,?,?,?,?,1,'cashier',datetime('now'))
            """, (
                biz_id,
                cashier_role_id or 5,
                cashier["username"],
                cashier["full_name"],
                cashier.get("phone", ""),
                pass_hash,
            ))
            masked_pw = _mask_secret(cashier["password"])
            print(f"   + كاشير: {cashier['full_name']} (يوزر: {cashier['username']} / باس: {masked_pw})")
        else:
            print(f"   ~ كاشير موجود: {cashier['username']}")

    conn.commit()

    # ─────────────────────────────────────────────────────────────
    # 5. إعداد المناديب
    # ─────────────────────────────────────────────────────────────
    print("\n[5/7] إعداد المناديب...")

    for agent in config.get("agents", []):
        existing = c.execute(
            "SELECT id FROM agents WHERE business_id=? AND username=?",
            (biz_id, agent["username"])
        ).fetchone()

        if not existing:
            agent_pass_hash = _hash_password(agent["password"])
            c.execute("""
                INSERT INTO agents (
                    business_id, full_name, phone, whatsapp_number,
                    username, password_hash, commission_rate, region,
                    is_active, perm_discount, perm_edit_price, perm_view_cost,
                    perm_collect, perm_add_client, perm_create_draft,
                    perm_send_offer, max_discount_pct, created_at
                ) VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,datetime('now'))
            """, (
                biz_id,
                agent["full_name"],
                agent.get("phone", ""),
                agent.get("phone", ""),
                agent["username"],
                agent_pass_hash,
                agent.get("commission_rate", 5.0),
                agent.get("region", ""),
                # صلاحيات
                1 if agent.get("can_discount") else 0,
                1 if agent.get("can_edit_price") else 0,
                0,  # perm_view_cost
                1 if agent.get("can_collect") else 0,
                1,  # perm_add_client
                1,  # perm_create_draft
                1,  # perm_send_offer
                agent.get("max_discount", 10),
            ))
            print(f"   + مندوب: {agent['full_name']}")
            print(f"     يوزر: {agent['username']} / باس: {_mask_secret(agent['password'])}")
            print(f"     رابط تسجيل الدخول: /agent/login")
            print(f"     العمولة: {agent.get('commission_rate', 5)}%")
        else:
            print(f"   ~ مندوب موجود: {agent['username']}")

    conn.commit()

    # ─────────────────────────────────────────────────────────────
    # 6. إعداد الإعدادات العامة (ZATCA / ضريبة)
    # ─────────────────────────────────────────────────────────────
    print("\n[6/7] إعداد إعدادات الضريبة والفواتير...")

    # إعداد نسبة الضريبة
    existing_tax = c.execute(
        "SELECT id FROM tax_settings WHERE business_id=? LIMIT 1", (biz_id,)
    ).fetchone()

    if not existing_tax:
        c.execute("""
            INSERT INTO tax_settings (business_id, name, rate, is_active, created_at)
            VALUES (?, 'ضريبة القيمة المضافة', ?, 1, datetime('now'))
        """, (biz_id, config.get("vat_rate", 15.0)))
    else:
        c.execute("""
            UPDATE tax_settings SET rate=? WHERE business_id=? AND id=?
        """, (config.get("vat_rate", 15.0), biz_id, existing_tax["id"]))

    # إعداد settings العامة للمنشأة
    settings_to_set = {
        "invoice_prefix": config.get("invoice_prefix", "INV"),
        "currency": config.get("currency", "SAR"),
        "currency_symbol": config.get("currency_symbol", "ر.س"),
        "vat_enabled": "1",
        "vat_number": config["tax_number"],
        "cr_number": config["cr_number"],
        "company_address": config.get("biz_address", ""),
        "company_phone": config.get("biz_phone", ""),
        "company_email": config.get("biz_email", ""),
        "offline_sync_enabled": "1",
        "pos_enabled": "1",
        "agent_invoice_enabled": "1",
        "agent_invoice_with_company_vat": "1",  # المندوب يصدر بالرقم الضريبي للشركة
    }

    for key, val in settings_to_set.items():
        existing_s = c.execute(
            "SELECT id FROM settings WHERE business_id=? AND key=?", (biz_id, key)
        ).fetchone()
        if existing_s:
            c.execute("UPDATE settings SET value=? WHERE id=?", (val, existing_s["id"]))
        else:
            c.execute(
                "INSERT INTO settings (business_id, key, value) VALUES (?,?,?)",
                (biz_id, key, val)
            )

    conn.commit()
    print(f"   + ضريبة القيمة المضافة: {config.get('vat_rate', 15)}%")
    print(f"   + الرقم الضريبي للفواتير: {config['tax_number']}")
    print(f"   + المندوب يصدر الفاتورة بالرقم الضريبي للشركة: نعم")

    # ─────────────────────────────────────────────────────────────
    # 7. إعداد بيانات ZATCA (إن توفرت)
    # ─────────────────────────────────────────────────────────────
    print("\n[7/7] الإعداد النهائي...")

    # التحقق من وجود حسابات محاسبية
    accounts_count = c.execute(
        "SELECT COUNT(*) FROM accounts WHERE business_id=?", (biz_id,)
    ).fetchone()[0]
    print(f"   + حسابات محاسبية: {accounts_count}")

    products_count = c.execute(
        "SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)
    ).fetchone()[0]
    print(f"   + منتجات وخدمات: {products_count}")

    # ملخص نهائي
    print("\n" + "=" * 70)
    print("   SETUP COMPLETE - جاهز للإنتاج الحقيقي!")
    print("=" * 70)
    print(f"""
بيانات الدخول:
--------------
المالك/الأدمن:
  الرابط:       http://127.0.0.1:5001/auth/login
  اسم المستخدم: {config['owner_username']}
    كلمة المرور:  {_mask_secret(config['owner_password'])}
""")

    for agent in config.get("agents", []):
        print(f"""المندوب ({agent['full_name']}):
  الرابط:       http://127.0.0.1:5001/agent/login
  اسم المستخدم: {agent['username']}
    كلمة المرور:  {_mask_secret(agent['password'])}
  صفحة الموبايل: http://127.0.0.1:5001/agent/portal
""")

    for cashier in config.get("cashiers", []):
        print(f"""الكاشير ({cashier['full_name']}):
  الرابط:       http://127.0.0.1:5001/auth/login
  اسم المستخدم: {cashier['username']}
    كلمة المرور:  {_mask_secret(cashier['password'])}
  صفحة POS:     http://127.0.0.1:5001/pos
""")

    print(f"""روابط النظام:
  لوحة التحكم:     http://127.0.0.1:5001/dashboard
  الفواتير:         http://127.0.0.1:5001/invoices/
  المخزون:          http://127.0.0.1:5001/inventory/
  نقطة البيع POS:   http://127.0.0.1:5001/pos
  المناديب:         http://127.0.0.1:5001/agents
  المالك:           http://127.0.0.1:5001/owner/dashboard
  صحة النظام:       http://127.0.0.1:5001/healthz
""")
    print("=" * 70 + "\n")

    conn.close()
    return True


# ─── الإعداد الافتراضي — عدّل هنا ببيانات منشأتك الحقيقية ─────────────────

PRODUCTION_CONFIG = {
    # ── بيانات المنشأة ───────────────────────────────────────────────────────
    "biz_name":       "شركة الجنان التجارية",        # اسم منشأتك الحقيقي
    "biz_name_en":    "Al-Jinan Trading Co.",
    "tax_number":     "300000000000003",               # رقمك الضريبي الحقيقي
    "cr_number":      "1010000001",                   # سجلك التجاري الحقيقي
    "biz_phone":      "+966501234567",
    "biz_email":      "info@jinan.sa",
    "biz_address":    "طريق الملك فهد، الرياض 12345",
    "biz_city":       "الرياض",
    "biz_country":    "SA",
    "country_code":   "SA",
    "currency":       "SAR",
    "currency_symbol": "ر.س",
    "industry_type":  "retail_fnb_general",            # نوع النشاط الرئيسي
    "vat_rate":       15.0,
    "invoice_prefix": "INV",

    # ── حساب المالك ─────────────────────────────────────────────────────────
    "owner_username": "admin",
    "owner_password": "Admin@2026!",                   # غيّر هذا فوراً بعد الدخول
    "owner_name":     "المالك",
    "owner_email":    "owner@jinan.sa",
    "owner_phone":    "+966501234567",

    # ── الفروع ──────────────────────────────────────────────────────────────
    "branches": [
        {"name": "الفرع الرئيسي", "location": "الرياض - حي العليا"},
        {"name": "الفرع الثاني",  "location": "الرياض - حي النخيل"},
    ],

    # ── الكاشيرون ───────────────────────────────────────────────────────────
    "cashiers": [
        {
            "username":  "cashier1",
            "password":  "Cash@2026!",
            "full_name": "كاشير الفرع الرئيسي",
            "phone":     "+966502000001",
        },
        {
            "username":  "cashier2",
            "password":  "Cash@2026!",
            "full_name": "كاشير الفرع الثاني",
            "phone":     "+966502000002",
        },
    ],

    # ── المناديب ────────────────────────────────────────────────────────────
    "agents": [
        {
            "username":        "agent1",
            "password":        "Agent@2026!",
            "full_name":       "أحمد المندوب",
            "phone":           "+966503000001",
            "commission_rate": 5.0,
            "region":          "الرياض - شمال",
            "max_discount":    10,
            "can_discount":    True,
            "can_edit_price":  False,
            "can_collect":     True,
        },
        {
            "username":        "agent2",
            "password":        "Agent@2026!",
            "full_name":       "محمد المندوب",
            "phone":           "+966503000002",
            "commission_rate": 5.0,
            "region":          "الرياض - جنوب",
            "max_discount":    10,
            "can_discount":    True,
            "can_edit_price":  False,
            "can_collect":     True,
        },
    ],
}


if __name__ == "__main__":
    print("\nسيتم الإعداد ببيانات المنشأة المُحددة في PRODUCTION_CONFIG")
    print("تأكد من تعديل البيانات قبل التشغيل في بيئة الإنتاج الفعلية\n")

    allow_insecure = os.getenv("ALLOW_INSECURE_DEFAULTS", "0").strip() == "1"
    if _has_insecure_defaults(PRODUCTION_CONFIG) and not allow_insecure:
        print("❌ تم إيقاف التنفيذ: تم اكتشاف كلمات مرور افتراضية غير آمنة في PRODUCTION_CONFIG")
        print("   عدّل كلمات المرور أولاً، أو استخدم ALLOW_INSECURE_DEFAULTS=1 للاختبار المحلي فقط")
        sys.exit(1)

    result = setup_production(PRODUCTION_CONFIG)
    if result:
        print("لتشغيل التطبيق:")
        print("  .venv\\Scripts\\python.exe app.py")
        print("  أو: .venv\\Scripts\\python.exe launcher.py")
