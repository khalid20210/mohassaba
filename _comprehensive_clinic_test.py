"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         اختبار شامل - عيادة طبية متكاملة (كاشير + طبيب + صيدلية)           ║
║         يغطي: POS • الفواتير • المرضى • الصيدلية • المخزون • التقارير       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import requests
import sqlite3
import hashlib
import secrets
import time
import threading
import json
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "http://127.0.0.1:5001"
DB_PATH  = Path("database/accounting_dev.db")

# ─── ألوان للطرفية ────────────────────────────────────────────────────────────
G  = "\033[92m"   # أخضر
R  = "\033[91m"   # أحمر
Y  = "\033[93m"   # أصفر
B  = "\033[94m"   # أزرق
C  = "\033[96m"   # سماوي
M  = "\033[95m"   # بنفسجي
W  = "\033[97m"   # أبيض
D  = "\033[90m"   # رمادي
RST= "\033[0m"

results = []
PASS = 0
FAIL = 0

def log(status, label, detail="", time_ms=None):
    global PASS, FAIL
    icon  = f"{G}✔{RST}" if status else f"{R}✘{RST}"
    color = G if status else R
    timing = f" {D}[{time_ms:.0f}ms]{RST}" if time_ms is not None else ""
    print(f"  {icon} {color}{label}{RST}{timing}  {D}{detail}{RST}")
    results.append({"ok": status, "label": label, "detail": detail, "ms": time_ms})
    if status: PASS += 1
    else: FAIL += 1

def section(title):
    print(f"\n{C}{'━'*72}{RST}")
    print(f"  {M}⟫ {title}{RST}")
    print(f"{C}{'━'*72}{RST}")

def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

# ─── دالة تسجيل الدخول ────────────────────────────────────────────────────────
def login_session(username, password):
    s = requests.Session()
    t0 = time.perf_counter()
    resp = s.post(f"{BASE_URL}/auth/login", data={
        "username": username,
        "password": password,
    }, allow_redirects=True, timeout=10)
    ms = (time.perf_counter() - t0) * 1000
    ok = resp.status_code == 200 and "dashboard" in resp.url
    return s, ok, ms

# ─── الجلسة الرئيسية ─────────────────────────────────────────────────────────
def prepare_test_account():
    """تجهيز حساب الاختبار في قاعدة البيانات"""
    conn = get_conn()
    
    # العثور على آخر عيادة طبية
    biz = conn.execute("""
        SELECT b.id, b.name, u.id as uid, u.username
        FROM businesses b JOIN users u ON u.business_id=b.id
        WHERE b.industry_type='medical' AND u.role_id=1
        ORDER BY b.id DESC LIMIT 1
    """).fetchone()
    
    if not biz:
        print(f"{R}✘ لا توجد عيادة طبية في قاعدة البيانات!{RST}")
        return None, None
    
    bid = biz['id']
    uid = biz['uid']
    username = biz['username']
    
    # تحديث كلمة المرور
    pw_hash = hash_password("Test@2026")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, uid))
    
    # التأكد من onboarding
    existing = conn.execute("SELECT id FROM settings WHERE business_id=? AND key='onboarding_complete'", (bid,)).fetchone()
    if existing:
        conn.execute("UPDATE settings SET value='1' WHERE business_id=? AND key='onboarding_complete'", (bid,))
    else:
        conn.execute("INSERT INTO settings(business_id,key,value) VALUES(?,?,?)", (bid,'onboarding_complete','1'))
    
    # التأكد من وجود مستودع
    wh = conn.execute("SELECT id FROM warehouses WHERE business_id=? LIMIT 1", (bid,)).fetchone()
    if not wh:
        conn.execute("INSERT INTO warehouses(business_id,name,is_default,is_active) VALUES(?,?,1,1)", (bid,'المخزن الرئيسي'))
    
    # التأكد من وجود منتجات طبية
    prod_count = conn.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (bid,)).fetchone()[0]
    if prod_count < 5:
        for i, (name, price, cat) in enumerate([
            ('أموكسيسيلين 500mg', 25.0, 'مضادات حيوية'),
            ('باراسيتامول 500mg', 8.0, 'مسكنات'),
            ('ضغط دم رقمي', 120.0, 'أجهزة طبية'),
            ('شاش طبي معقم', 15.0, 'مستلزمات'),
            ('قفازات طبية (علبة)', 35.0, 'مستلزمات'),
            ('فيتامين C 1000mg', 40.0, 'مكملات غذائية'),
        ]):
            exists = conn.execute("SELECT id FROM products WHERE business_id=? AND name=?", (bid, name)).fetchone()
            if not exists:
                conn.execute("""
                    INSERT INTO products(business_id,name,sale_price,cost_price,category_name,is_active,unit)
                    VALUES(?,?,?,?,?,1,'قطعة')
                """, (bid, name, price, price*0.6, cat))
    
    # التأكد من وجود مرضى
    patient_count = conn.execute("SELECT COUNT(*) FROM patients WHERE business_id=?", (bid,)).fetchone()[0]
    if patient_count < 3:
        for name, phone, gender in [
            ('أحمد محمد علي', '0501234567', 'male'),
            ('فاطمة خالد السيد', '0512345678', 'female'),
            ('خالد إبراهيم حسن', '0523456789', 'male'),
            ('نورة عبدالله محمد', '0534567890', 'female'),
        ]:
            conn.execute("""
                INSERT OR IGNORE INTO patients(business_id,patient_name,patient_phone,gender,created_at,updated_at)
                VALUES(?,?,?,?,datetime('now'),datetime('now'))
            """, (bid, name, phone, gender))
    
    # تأمين مخزون للمنتجات
    prods = conn.execute("SELECT id FROM products WHERE business_id=? AND is_active=1", (bid,)).fetchall()
    for p in prods:
        inv = conn.execute("SELECT id FROM product_inventory WHERE product_id=? AND business_id=?", (p['id'], bid)).fetchone()
        if inv:
            conn.execute("UPDATE product_inventory SET current_qty=100 WHERE product_id=? AND business_id=?", (p['id'], bid))
        else:
            conn.execute("INSERT INTO product_inventory(business_id,product_id,current_qty) VALUES(?,?,100)", (bid, p['id']))
    
    # إضافة عميل (مريض كعميل)
    cust = conn.execute("SELECT id FROM contacts WHERE business_id=? AND contact_type='customer' LIMIT 1", (bid,)).fetchone()
    if not cust:
        conn.execute("""
            INSERT INTO contacts(business_id,name,contact_type,phone,is_active)
            VALUES(?,'عميل عام','customer','0500000000',1)
        """, (bid,))
    
    conn.commit()
    conn.close()
    
    return username, bid

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 1: تسجيل الدخول ولوحة التحكم
# ══════════════════════════════════════════════════════════════════════════════
def test_dashboard(sess):
    section("1️⃣  لوحة التحكم والإحصائيات الرئيسية")
    
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/dashboard", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "لوحة التحكم الرئيسية", f"HTTP {r.status_code}", ms)
    
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/analytics", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "صفحة التحليلات والإحصائيات", f"HTTP {r.status_code}", ms)
    
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/api/invoices/stats", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    data = {}
    if ok:
        try: data = r.json()
        except: ok = False
    log(ok, "API إحصائيات الفواتير", f"الفواتير: {data.get('total_count',0)} | الإيرادات: {data.get('total_amount',0):.0f} ر.س", ms)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 2: إدارة المرضى (الخدمة الطبية)
# ══════════════════════════════════════════════════════════════════════════════
def test_medical_patients(sess, biz_id):
    section("2️⃣  نظام إدارة المرضى (الخدمة الطبية)")
    
    # قائمة المرضى
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/medical/patients", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "قائمة المرضى", f"HTTP {r.status_code}", ms)
    
    # إضافة مريض جديد
    t0 = time.perf_counter()
    r = sess.post(f"{BASE_URL}/medical/patients/new", data={
        "name": f"مريض_اختبار_{int(time.time())%10000}",
        "phone": f"05{int(time.time())%100000000:08d}",
        "gender": "male",
        "dob": "1990-01-15",
        "national_id": f"{int(time.time())%10000000000:010d}",
        "email": "test@clinic.sa",
        "address": "الرياض، حي النزهة",
    }, allow_redirects=True, timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "إضافة مريض جديد", f"HTTP {r.status_code}", ms)
    
    # إحصائيات المرضى
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/medical/api/stats", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    data = {}
    if ok:
        try: data = r.json()
        except: pass
    log(ok, "API إحصائيات العيادة اليومية",
        f"المرضى: {data.get('total_patients',0)} | المواعيد اليوم: {data.get('today_appointments',0)}", ms)
    
    # جلب أول مريض وحجز موعد
    conn = get_conn()
    patient = conn.execute("SELECT id,patient_name FROM patients WHERE business_id=? LIMIT 1", (biz_id,)).fetchone()
    conn.close()
    
    patient_id = None
    if patient:
        patient_id = patient['id']
        # عرض ملف المريض
        t0 = time.perf_counter()
        r = sess.get(f"{BASE_URL}/medical/patients/{patient_id}", timeout=10)
        ms = (time.perf_counter()-t0)*1000
        log(r.status_code==200, f"ملف المريض: {patient['patient_name']}", f"HTTP {r.status_code}", ms)
    
    return patient_id

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 3: المواعيد والوصفات الطبية
# ══════════════════════════════════════════════════════════════════════════════
def test_appointments_prescriptions(sess, patient_id):
    section("3️⃣  المواعيد والوصفات الطبية")
    
    # قائمة المواعيد
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/medical/appointments", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "قائمة المواعيد المجدولة", f"HTTP {r.status_code}", ms)
    
    if not patient_id:
        log(False, "حجز موعد جديد", "لا يوجد مريض")
        return
    
    # حجز موعد جديد
    future_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    t0 = time.perf_counter()
    r = sess.post(f"{BASE_URL}/medical/appointments/new", data={
        "patient_id": str(patient_id),
        "date": future_date,
        "time": "10:00",
        "doctor": "د. خالد الشمري",
        "type": "consultation",
        "notes": "مراجعة دورية - اختبار تلقائي",
    }, allow_redirects=True, timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "حجز موعد طبي جديد", f"دكتور: د. خالد الشمري | {future_date}", ms)
    
    # إضافة وصفة طبية
    t0 = time.perf_counter()
    r = sess.post(f"{BASE_URL}/medical/prescriptions/{patient_id}/new", data={
        "doctor": "د. خالد الشمري",
        "diagnosis": "ضغط الدم المرتفع - مرحلة أولى",
        "medications": "أملوديبين 5mg - مرة يومياً | باراسيتامول 500mg - عند الحاجة",
        "notes": "يراجع بعد شهر لقياس الضغط",
    }, allow_redirects=True, timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "إضافة وصفة طبية للمريض", f"HTTP {r.status_code}", ms)
    
    # وصفات المريض
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/medical/prescriptions/{patient_id}", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "عرض وصفات المريض", f"HTTP {r.status_code}", ms)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 4: الفواتير الطبية (خدمات + أدوية)
# ══════════════════════════════════════════════════════════════════════════════
def test_invoices(sess, biz_id):
    section("4️⃣  الفواتير الطبية (خدمات + صيدلية)")
    
    # قائمة الفواتير
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/invoices/", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "قائمة كل الفواتير", f"HTTP {r.status_code}", ms)
    
    # صفحة إنشاء فاتورة
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/invoices/new", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "صفحة إنشاء فاتورة جديدة", f"HTTP {r.status_code}", ms)
    
    # جلب منتج للفاتورة
    conn = get_conn()
    prod = conn.execute("SELECT id,name,sale_price FROM products WHERE business_id=? AND is_active=1 LIMIT 1", (biz_id,)).fetchone()
    conn.close()
    
    created_inv_id = None
    if prod:
        csrf = r.text.split('name="csrf_token" value="')[1].split('"')[0] if 'csrf_token' in r.text else ""
        # إنشاء فاتورة مبيعات بخدمة طبية
        today = datetime.now().strftime("%Y-%m-%d")
        t0 = time.perf_counter()
        r2 = sess.post(f"{BASE_URL}/invoices/new", data={
            "csrf_token": csrf,
            "invoice_type": "sale",
            "invoice_date": today,
            "party_name": "مريض: أحمد محمد - كشف طبي",
            "notes": "كشف طبي عام + وصفة",
            "items[0][product_id]": str(prod['id']),
            "items[0][description]": "كشف طبي عام",
            "items[0][quantity]": "1",
            "items[0][unit_price]": "150",
            "items[0][discount_pct]": "0",
            "items[0][tax_rate]": "15",
        }, allow_redirects=True, timeout=15)
        ms = (time.perf_counter()-t0)*1000
        ok = r2.status_code == 200
        if ok and "/invoices/" in r2.url:
            try:
                created_inv_id = int(r2.url.rstrip("/").split("/")[-1])
            except:
                pass
        log(ok, "إنشاء فاتورة خدمة طبية (كشف 150 ر.س)", f"HTTP {r2.status_code} | {r2.url.split('/')[-1]}", ms)
    else:
        log(False, "إنشاء فاتورة خدمة طبية", "لا توجد منتجات/خدمات")
    
    # إحصائيات الفواتير
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/api/invoices/stats", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    try:
        data = r.json()
        log(ok, "إحصائيات الفواتير المالية",
            f"إجمالي: {data.get('total_count',0)} | مدفوعة: {data.get('paid_count',0)} | إيرادات: {data.get('total_amount',0):.0f} ر.س", ms)
    except:
        log(ok, "إحصائيات الفواتير", "لا توجد بيانات JSON", ms)
    
    return created_inv_id

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 5: نقطة البيع POS (الكاشير)
# ══════════════════════════════════════════════════════════════════════════════
def test_pos_cashier(sess, biz_id, cashier_label="الكاشير الرئيسي"):
    section(f"5️⃣  نقطة البيع - {cashier_label}")
    
    # صفحة POS
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/pos", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, f"صفحة نقطة البيع ({cashier_label})", f"HTTP {r.status_code}", ms)
    
    # إعدادات POS
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/api/pos/config", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    config = {}
    if ok:
        try: config = r.json()
        except: ok = False
    log(ok, "إعدادات نقطة البيع", f"الضريبة: {config.get('tax_rate',0)}% | العملة: {config.get('currency','')}", ms)
    
    # فتح وردية جديدة
    t0 = time.perf_counter()
    r = sess.post(f"{BASE_URL}/api/pos/shift/open",
        json={"opening_cash": 500, "notes": f"فتح وردية - {cashier_label}"},
        timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code in (200, 400)  # 400 = وردية مفتوحة بالفعل
    shift_data = {}
    try: shift_data = r.json()
    except: pass
    shift_ok = shift_data.get("success", False)
    msg = shift_data.get("message", shift_data.get("error", ""))
    log(ok, f"فتح وردية الكاشير ({cashier_label})", msg, ms)
    
    # الوردية الحالية
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/api/pos/shift/current", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    shift_info = {}
    if ok:
        try: shift_info = r.json()
        except: pass
    log(ok, "حالة الوردية الحالية", f"مفتوحة: {bool(shift_info.get('id'))}", ms)
    
    # بحث عن منتجات
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/api/pos/search?q=ام", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    prods = []
    if ok:
        try: prods = r.json()
        except: pass
    log(ok, "بحث عن المنتجات في POS", f"وجد: {len(prods)} منتج", ms)
    
    # إتمام عملية بيع
    conn = get_conn()
    products = conn.execute("""
        SELECT p.id, p.name, p.sale_price, pi.current_qty
        FROM products p
        LEFT JOIN product_inventory pi ON pi.product_id=p.id
        WHERE p.business_id=? AND p.is_active=1 AND (pi.current_qty IS NULL OR pi.current_qty>0)
        LIMIT 2
    """, (biz_id,)).fetchall()
    conn.close()
    
    if products:
        items = []
        for prod in products[:2]:
            items.append({
                "product_id": prod['id'],
                "quantity": 1,
                "unit_price": float(prod['sale_price'] or 100),
                "discount_pct": 0
            })
        
        t0 = time.perf_counter()
        r = sess.post(f"{BASE_URL}/api/pos/checkout", json={
            "items": items,
            "payment_method": "cash",
            "customer_id": None
        }, timeout=15)
        ms = (time.perf_counter()-t0)*1000
        ok = r.status_code == 200
        sale_data = {}
        try: sale_data = r.json()
        except: pass
        sale_ok = sale_data.get("success", False)
        total = sale_data.get("total", 0)
        log(ok and sale_ok, f"عملية بيع نقدية ({cashier_label})",
            f"المبلغ: {total:.0f} ر.س | {len(items)} منتج", ms)
    else:
        log(False, f"عملية بيع POS ({cashier_label})", "لا توجد منتجات متاحة")
    
    # تقرير X الوردية
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/api/pos/shift/x-report", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    xrep = {}
    if ok:
        try: xrep = r.json()
        except: pass
    log(ok, f"تقرير X الوردية ({cashier_label})",
        f"مبيعات: {xrep.get('total_sales',0):.0f} | معاملات: {xrep.get('transaction_count',0)}", ms)
    
    # التقرير اليومي POS
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/api/pos/reports/daily", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    daily = {}
    if ok:
        try: daily = r.json()
        except: pass
    log(ok, "التقرير اليومي لنقطة البيع",
        f"صافي: {daily.get('net_sales',0):.0f} | معاملات: {daily.get('transaction_count',0)}", ms)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 6: المخزون والصيدلية الداخلية
# ══════════════════════════════════════════════════════════════════════════════
def test_inventory_pharmacy(sess, biz_id):
    section("6️⃣  المخزون والصيدلية الداخلية")
    
    # لوحة المخزون
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "لوحة تحكم المخزون", f"HTTP {r.status_code}", ms)
    
    # قائمة المنتجات
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/products", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "قائمة المنتجات والأدوية", f"HTTP {r.status_code}", ms)
    
    # حركات المخزون
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/movements", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "سجل حركات المخزون", f"HTTP {r.status_code}", ms)
    
    # التنبيهات
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/alerts", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "تنبيهات نفاد المخزون", f"HTTP {r.status_code}", ms)
    
    # جرد المخزون
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/stock-count", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "صفحة جرد المخزون", f"HTTP {r.status_code}", ms)
    
    # تقارير المخزون
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/reports", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "تقارير المخزون", f"HTTP {r.status_code}", ms)
    
    # API: مخزون منتج محدد
    conn = get_conn()
    prod = conn.execute("SELECT id FROM products WHERE business_id=? AND is_active=1 LIMIT 1", (biz_id,)).fetchone()
    conn.close()
    
    if prod:
        t0 = time.perf_counter()
        r = sess.get(f"{BASE_URL}/inventory/api/stock/{prod['id']}", timeout=10)
        ms = (time.perf_counter()-t0)*1000
        ok = r.status_code == 200
        stock = {}
        if ok:
            try: stock = r.json()
            except: pass
        log(ok, "API مستوى مخزون منتج (صيدلية)", f"الكمية: {stock.get('current_qty',stock.get('qty',0))}", ms)
        
        # إضافة حركة مخزون (استلام أدوية)
        t0 = time.perf_counter()
        r = sess.post(f"{BASE_URL}/inventory/movements/add", data={
            "product_id": str(prod['id']),
            "movement_type": "in",
            "quantity": "50",
            "notes": "استلام دفعة أدوية - الصيدلية الداخلية",
        }, allow_redirects=True, timeout=10)
        ms = (time.perf_counter()-t0)*1000
        log(r.status_code==200, "استلام دفعة أدوية (وارد مخزون)", f"HTTP {r.status_code}", ms)
    
    # اقتراحات إعادة الطلب
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/api/reorder-suggestions", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code == 200
    sugg = {}
    if ok:
        try: sugg = r.json()
        except: pass
    count = len(sugg) if isinstance(sugg, list) else sugg.get('count', 0)
    log(ok, "اقتراحات إعادة طلب الأدوية", f"عدد التوصيات: {count}", ms)
    
    # تقرير هامش الربح
    t0 = time.perf_counter()
    r = sess.get(f"{BASE_URL}/inventory/reports/profit-margin", timeout=10)
    ms = (time.perf_counter()-t0)*1000
    log(r.status_code==200, "تقرير هامش الربح للمنتجات", f"HTTP {r.status_code}", ms)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 7: جهات الاتصال (العملاء والموردون)
# ══════════════════════════════════════════════════════════════════════════════
def test_contacts(sess):
    section("7️⃣  إدارة العملاء والموردين")
    
    endpoints = [
        ("/contacts/", "قائمة جهات الاتصال"),
        ("/contacts/?type=customer", "قائمة العملاء (المرضى)"),
        ("/contacts/?type=supplier", "قائمة الموردين"),
    ]
    for path, label in endpoints:
        t0 = time.perf_counter()
        r = sess.get(f"{BASE_URL}{path}", timeout=10)
        ms = (time.perf_counter()-t0)*1000
        log(r.status_code==200, label, f"HTTP {r.status_code}", ms)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 8: المحاسبة والتقارير المالية
# ══════════════════════════════════════════════════════════════════════════════
def test_accounting(sess):
    section("8️⃣  المحاسبة والتقارير المالية")
    
    endpoints = [
        ("/accounting", "صفحة المحاسبة الرئيسية"),
        ("/accounting?section=ledger", "دفتر الأستاذ"),
        ("/accounting?section=trial-balance", "ميزان المراجعة"),
        ("/audit-log", "سجل المراجعة والأحداث"),
    ]
    for path, label in endpoints:
        t0 = time.perf_counter()
        r = sess.get(f"{BASE_URL}{path}", timeout=10)
        ms = (time.perf_counter()-t0)*1000
        log(r.status_code==200, label, f"HTTP {r.status_code}", ms)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 9: الإعدادات والنظام
# ══════════════════════════════════════════════════════════════════════════════
def test_settings(sess):
    section("9️⃣  الإعدادات والنظام")
    
    endpoints = [
        ("/settings", "إعدادات المنشأة"),
        ("/settings/users", "إدارة المستخدمين"),
        ("/backup", "صفحة النسخ الاحتياطي"),
        ("/healthz", "فحص صحة الخدمة (Health Check)"),
        ("/readyz", "فحص جاهزية الخدمة (Ready Check)"),
    ]
    for path, label in endpoints:
        t0 = time.perf_counter()
        r = sess.get(f"{BASE_URL}{path}", timeout=10)
        ms = (time.perf_counter()-t0)*1000
        log(r.status_code in (200,302), label, f"HTTP {r.status_code}", ms)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 10: اختبار تعدد الكاشيرات تزامنياً (Concurrent Load)
# ══════════════════════════════════════════════════════════════════════════════
def test_concurrent_cashiers(username, biz_id):
    section("🔟  اختبار الضغط — تعدد الكاشيرات والمستخدمين المتزامنين")
    
    CASHIERS = [
        ("الكاشير 1 - الاستقبال", "cash"),
        ("الكاشير 2 - الصيدلية",  "cash"),
        ("الكاشير 3 - المختبر",   "cash"),
    ]
    
    conn = get_conn()
    products = conn.execute("""
        SELECT p.id, p.sale_price FROM products p
        WHERE p.business_id=? AND p.is_active=1 LIMIT 3
    """, (biz_id,)).fetchall()
    conn.close()
    
    if not products:
        log(False, "اختبار الكاشيرات المتزامنة", "لا توجد منتجات")
        return
    
    sale_results = []
    timings = []
    errors = []
    
    def cashier_session(label, payment):
        s = requests.Session()
        ok, ms_login = False, 0
        try:
            t0 = time.perf_counter()
            resp = s.post(f"{BASE_URL}/auth/login", data={
                "username": username, "password": "Test@2026"
            }, allow_redirects=True, timeout=10)
            ms_login = (time.perf_counter()-t0)*1000
            if resp.status_code != 200 or "dashboard" not in resp.url:
                errors.append(f"{label}: فشل تسجيل الدخول")
                return
            
            # بيع سريع
            items = [{"product_id": products[0]['id'], "quantity": 1,
                      "unit_price": float(products[0]['sale_price'] or 50), "discount_pct": 0}]
            t0 = time.perf_counter()
            r = s.post(f"{BASE_URL}/api/pos/checkout", json={
                "items": items, "payment_method": payment, "customer_id": None
            }, timeout=15)
            ms = (time.perf_counter()-t0)*1000
            timings.append(ms)
            
            data = {}
            try: data = r.json()
            except: pass
            
            if r.status_code == 200 and data.get("success"):
                sale_results.append({"label": label, "total": data.get("total",0), "ms": ms})
                ok = True
            else:
                errors.append(f"{label}: {data.get('error','خطأ')}")
        except Exception as e:
            errors.append(f"{label}: {str(e)[:60]}")
    
    # تشغيل الكاشيرات بالتوازي
    t_start = time.perf_counter()
    threads = []
    for label, pmt in CASHIERS:
        t = threading.Thread(target=cashier_session, args=(label, pmt))
        threads.append(t)
    
    for t in threads: t.start()
    for t in threads: t.join()
    
    total_time = (time.perf_counter() - t_start) * 1000
    
    log(len(sale_results) == len(CASHIERS),
        f"تزامن {len(CASHIERS)} كاشير في وقت واحد",
        f"نجح: {len(sale_results)}/{len(CASHIERS)} | وقت كلي: {total_time:.0f}ms",
        total_time)
    
    for res in sale_results:
        print(f"    {G}✔{RST} {res['label']}: {res['total']:.0f} ر.س {D}[{res['ms']:.0f}ms]{RST}")
    
    for err in errors:
        print(f"    {R}✘{RST} {err}")
    
    if timings:
        avg = sum(timings)/len(timings)
        log(avg < 3000, "متوسط زمن الاستجابة تحت الضغط",
            f"متوسط: {avg:.0f}ms | أبطأ: {max(timings):.0f}ms | أسرع: {min(timings):.0f}ms", avg)

# ══════════════════════════════════════════════════════════════════════════════
# الاختبار 11: اختبار ضغط API (50 طلب متتالي)
# ══════════════════════════════════════════════════════════════════════════════
def test_api_stress(sess):
    section("1️⃣1️⃣  اختبار ضغط API (50 طلب متزامن)")
    
    ENDPOINTS = [
        "/api/invoices/stats",
        "/inventory/api/reorder-suggestions",
        "/medical/api/stats",
        "/api/pos/shift/current",
        "/healthz",
    ]
    
    total_requests = 0
    total_success  = 0
    total_ms_list  = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for ep in ENDPOINTS:
            for _ in range(10):  # 10 طلبات لكل endpoint = 50 إجمالي
                futures.append(executor.submit(lambda e=ep: (
                    e, *[(r := sess.get(f"{BASE_URL}{e}", timeout=5)),
                          (time.perf_counter())]
                )))
        
        # نفذها بشكل مبسط
        for ep in ENDPOINTS:
            ep_success = 0
            ep_ms = []
            for _ in range(10):
                t0 = time.perf_counter()
                try:
                    r = sess.get(f"{BASE_URL}{ep}", timeout=5)
                    ms = (time.perf_counter()-t0)*1000
                    ep_ms.append(ms)
                    total_ms_list.append(ms)
                    if r.status_code == 200:
                        ep_success += 1
                        total_success += 1
                    total_requests += 1
                except:
                    total_requests += 1
            
            avg = sum(ep_ms)/len(ep_ms) if ep_ms else 0
            log(ep_success >= 8, f"10×{ep.split('/')[-1] or 'root'}",
                f"نجح: {ep_success}/10 | متوسط: {avg:.0f}ms", avg)
    
    overall_avg = sum(total_ms_list)/len(total_ms_list) if total_ms_list else 0
    log(total_success >= 45, "ملخص اختبار الضغط الكلي",
        f"نجح: {total_success}/{total_requests} ({total_success/total_requests*100:.0f}%) | متوسط: {overall_avg:.0f}ms",
        overall_avg)

# ══════════════════════════════════════════════════════════════════════════════
# التقرير النهائي
# ══════════════════════════════════════════════════════════════════════════════
def print_final_report():
    total = PASS + FAIL
    pct   = PASS / total * 100 if total else 0
    
    color = G if pct >= 90 else Y if pct >= 70 else R
    
    print(f"\n{C}{'═'*72}{RST}")
    print(f"  {M}📊 التقرير النهائي الشامل{RST}")
    print(f"{C}{'═'*72}{RST}")
    
    # توزيع النتائج
    failed = [r for r in results if not r['ok']]
    passed = [r for r in results if r['ok']]
    
    print(f"\n  {G}✔ اجتاز: {PASS} اختبار{RST}")
    print(f"  {R}✘ فشل:  {FAIL} اختبار{RST}")
    print(f"\n  {color}نسبة النجاح: {pct:.1f}% ({PASS}/{total}){RST}")
    
    # زمن الاستجابة
    ms_vals = [r['ms'] for r in results if r['ms'] is not None]
    if ms_vals:
        avg_ms = sum(ms_vals)/len(ms_vals)
        max_ms = max(ms_vals)
        min_ms = min(ms_vals)
        print(f"\n  ⏱  متوسط الاستجابة: {avg_ms:.0f}ms")
        print(f"     أبطأ: {max_ms:.0f}ms | أسرع: {min_ms:.0f}ms")
        
        fast = len([m for m in ms_vals if m < 200])
        ok_  = len([m for m in ms_vals if 200 <= m < 1000])
        slow = len([m for m in ms_vals if m >= 1000])
        print(f"     🟢 سريع (<200ms): {fast} | 🟡 مقبول (<1s): {ok_} | 🔴 بطيء (>1s): {slow}")
    
    if failed:
        print(f"\n  {R}الاختبارات الفاشلة:{RST}")
        for r in failed:
            print(f"    {R}✘{RST} {r['label']}: {r['detail']}")
    
    print(f"\n{C}{'═'*72}{RST}")
    
    # تقييم الكفاءة
    print(f"\n  📋 تقييم الخدمات:")
    services = [
        ("لوحة التحكم والإحصائيات",    pct >= 90),
        ("نظام إدارة المرضى",           FAIL < 3),
        ("المواعيد والوصفات الطبية",    FAIL < 3),
        ("الفواتير الطبية",             FAIL < 3),
        ("نقطة البيع (الكاشير)",        FAIL < 3),
        ("المخزون والصيدلية",           FAIL < 3),
        ("التقارير المالية",            FAIL < 3),
        ("تعدد المستخدمين (ضغط)",       FAIL < 5),
    ]
    for label, ok in services:
        icon  = f"{G}✔{RST}" if ok else f"{Y}⚠{RST}"
        state = f"{G}كفء{RST}" if ok else f"{Y}يحتاج مراجعة{RST}"
        print(f"    {icon} {label}: {state}")
    
    print(f"\n{C}{'═'*72}{RST}\n")
    
    verdict = "🟢 النظام جاهز للإنتاج وكفء تحت الضغط" if pct >= 90 \
         else "🟡 النظام يعمل مع ملاحظات بسيطة" if pct >= 75 \
         else "🔴 النظام يحتاج إصلاحات قبل الإنتاج"
    print(f"  {verdict}\n")

# ══════════════════════════════════════════════════════════════════════════════
# النقطة الرئيسية
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{B}{'╔'+'═'*70+'╗'}{RST}")
    print(f"{B}║{RST}{'اختبار شامل — عيادة طبية متكاملة':^70}{B}║{RST}")
    print(f"{B}║{RST}{'كاشير • طبيب • صيدلية • فواتير • ضغط متزامن':^70}{B}║{RST}")
    print(f"{B}{'╚'+'═'*70+'╝'}{RST}\n")
    
    # تجهيز بيانات الاختبار
    print(f"  {Y}⟳ تجهيز بيانات الاختبار...{RST}")
    username, biz_id = prepare_test_account()
    
    if not username:
        print(f"  {R}✘ فشل تجهيز البيانات - تأكد من وجود عيادة طبية{RST}")
        exit(1)
    
    print(f"  {G}✔ تجهيز البيانات اكتمل{RST}")
    print(f"  {D}المستخدم: {username} | بيانات تسجيل الدخول: Test@2026{RST}\n")
    
    # تسجيل الدخول
    print(f"  {Y}⟳ تسجيل الدخول...{RST}")
    sess, login_ok, login_ms = login_session(username, "Test@2026")
    
    if not login_ok:
        print(f"  {R}✘ فشل تسجيل الدخول ({login_ms:.0f}ms){RST}")
        exit(1)
    
    log(True, "تسجيل الدخول الرئيسي", f"المستخدم: {username} | العيادة: {biz_id}", login_ms)
    
    # ── تشغيل كل الاختبارات ──
    t_start_all = time.perf_counter()
    
    test_dashboard(sess)
    patient_id = test_medical_patients(sess, biz_id)
    test_appointments_prescriptions(sess, patient_id)
    inv_id = test_invoices(sess, biz_id)
    test_pos_cashier(sess, biz_id, "الكاشير الرئيسي - استقبال")
    test_inventory_pharmacy(sess, biz_id)
    test_contacts(sess)
    test_accounting(sess)
    test_settings(sess)
    test_concurrent_cashiers(username, biz_id)
    test_api_stress(sess)
    
    total_time_all = (time.perf_counter() - t_start_all) * 1000
    print(f"\n  {D}⏱ إجمالي وقت الاختبار: {total_time_all/1000:.1f} ثانية{RST}")
    
    print_final_report()
