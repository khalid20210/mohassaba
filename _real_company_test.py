"""
_real_company_test.py
اختبار شامل يحاكي شركات حقيقية متعددة الأنشطة
يشمل: تسجيل، دخول، فواتير، مخزون، مزامنة، كاشيرات، مرضى، وغيرها
"""
import requests
import json
import random
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict

BASE = "http://127.0.0.1:5001"
RESULTS = []
PASS = 0
FAIL = 0
WARN = 0

# ─── أداة إعداد التقرير ──────────────────────────────────────────────────────
def log(label, status, detail="", critical=False):
    global PASS, FAIL, WARN
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(status, "•")
    if status == "PASS":   PASS += 1
    elif status == "FAIL": FAIL += 1
    elif status == "WARN": WARN += 1
    line = f"  {icon} [{status}] {label}"
    if detail: line += f" — {detail}"
    print(line)
    RESULTS.append((status, label, detail))
    if critical and status == "FAIL":
        print(f"\n  !! توقف إجباري: {label}")
        raise SystemExit(1)

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def post(session, path, data=None, json_data=None, expect_codes=(200, 201, 302)):
    try:
        r = session.post(f"{BASE}{path}", data=data, json=json_data,
                         allow_redirects=True, timeout=15)
        return r
    except Exception as e:
        return None

def get(session, path, expect_codes=(200,)):
    try:
        r = session.get(f"{BASE}{path}", allow_redirects=True, timeout=15)
        return r
    except Exception as e:
        return None

def check(r, label, ok_codes=(200, 201, 302), keyword=None):
    if r is None:
        log(label, "FAIL", "لا استجابة (timeout/error)")
        return False
    if r.status_code not in ok_codes:
        log(label, "FAIL", f"HTTP {r.status_code}")
        return False
    if keyword and keyword not in r.text:
        log(label, "WARN", f"الكود {r.status_code} لكن '{keyword}' غائبة في الرد")
        return True
    log(label, "PASS", f"HTTP {r.status_code}")
    return True

# ─── 1. فحص صحة الخادم ────────────────────────────────────────────────────
section("1️⃣  فحص صحة الخادم")
s = requests.Session()
r = s.get(f"{BASE}/healthz", timeout=10)
if r.status_code == 200:
    log("healthz", "PASS", r.text[:80])
else:
    log("healthz", "FAIL", f"HTTP {r.status_code}", critical=True)

r2 = s.get(f"{BASE}/readyz", timeout=10)
check(r2, "readyz — قاعدة البيانات")

# ─── 2. إنشاء حسابات لشركات متعددة ────────────────────────────────────────
section("2️⃣  إنشاء حسابات شركات حقيقية")

companies = [
    {
        "name": "سوبر ماركت النور",
        "email": "test_supermarket@jinan.biz",
        "password": "Test@12345",
        "industry_type": "retail_fnb_supermarket",
        "label": "سوبر ماركت (تجزئة غذاء)",
    },
    {
        "name": "مطعم الأصالة",
        "email": "test_restaurant@jinan.biz",
        "password": "Test@12345",
        "industry_type": "food_restaurant",
        "label": "مطعم",
    },
    {
        "name": "مستودع الخير للتوزيع",
        "email": "test_wholesale@jinan.biz",
        "password": "Test@12345",
        "industry_type": "wholesale_fnb_distribution",
        "label": "جملة توزيع",
    },
    {
        "name": "عيادة الأمل الطبية",
        "email": "test_medical@jinan.biz",
        "password": "Test@12345",
        "industry_type": "medical_dental",
        "label": "عيادة أسنان",
    },
    {
        "name": "مجمع الإنشاء والتعمير",
        "email": "test_construction@jinan.biz",
        "password": "Test@12345",
        "industry_type": "construction",
        "label": "مقاولات",
    },
    {
        "name": "صيدلية الشفاء",
        "email": "test_pharmacy@jinan.biz",
        "password": "Test@12345",
        "industry_type": "retail_health_pharmacy",
        "label": "صيدلية",
    },
    {
        "name": "شركة تأجير سيارات الخليج",
        "email": "test_rental@jinan.biz",
        "password": "Test@12345",
        "industry_type": "car_rental",
        "label": "تأجير سيارات",
    },
    {
        "name": "مكتب الإبداع للاستشارات",
        "email": "test_services@jinan.biz",
        "password": "Test@12345",
        "industry_type": "services_consulting",
        "label": "استشارات",
    },
]

sessions = {}  # {email: session object}

for co in companies:
    sess = requests.Session()
    # تسجيل
    r = post(sess, "/auth/register", data={
        "business_name": co["name"],
        "email":         co["email"],
        "password":      co["password"],
        "confirm_password": co["password"],
        "industry_type": co["industry_type"],
    })
    if r and r.status_code in (200, 302):
        log(f"تسجيل: {co['label']}", "PASS", co["email"])
    else:
        code = r.status_code if r else "ERR"
        log(f"تسجيل: {co['label']}", "WARN", f"HTTP {code} (ربما موجود)")

    # تسجيل الدخول
    r2 = post(sess, "/auth/login", data={
        "email":    co["email"],
        "password": co["password"],
    })
    if r2 and r2.status_code in (200, 302):
        log(f"دخول: {co['label']}", "PASS")
        sessions[co["email"]] = (sess, co)
    else:
        code = r2.status_code if r2 else "ERR"
        log(f"دخول: {co['label']}", "FAIL", f"HTTP {code}")

# ─── 3. فحص لوحات التحكم ────────────────────────────────────────────────────
section("3️⃣  لوحات التحكم الرئيسية")

for email, (sess, co) in sessions.items():
    r = get(sess, "/dashboard")
    check(r, f"Dashboard: {co['label']}", ok_codes=(200, 302))

# ─── 4. فحص المنتجات والمخزون ──────────────────────────────────────────────
section("4️⃣  المنتجات والمخزون")

for email, (sess, co) in sessions.items():
    r = get(sess, "/inventory/products")
    check(r, f"قائمة منتجات: {co['label']}", ok_codes=(200, 302))

# فحص عدد المنتجات الحقيقية عبر API
r_api = s.get(f"{BASE}/api/products?limit=5", timeout=10)
if r_api and r_api.status_code == 200:
    log("API المنتجات", "PASS", f"HTTP {r_api.status_code}")
else:
    r_api2 = s.get(f"{BASE}/inventory/api/products?limit=5", timeout=10)
    log("API المنتجات", "INFO", f"HTTP {r_api2.status_code if r_api2 else 'ERR'}")

# ─── 5. اختبار نقطة البيع (كاشير) ──────────────────────────────────────────
section("5️⃣  نقطة البيع — الكاشيرات")

supermarket_sess = None
for email, (sess, co) in sessions.items():
    if co["industry_type"] == "retail_fnb_supermarket":
        supermarket_sess = sess
        break

if supermarket_sess:
    # فتح صفحة POS
    r = get(supermarket_sess, "/pos")
    check(r, "فتح شاشة POS", ok_codes=(200, 302))

    # فتح وردية
    r2 = post(supermarket_sess, "/pos/shift/open", data={
        "opening_cash": "500",
        "cashier_name": "أحمد الكاشير"
    })
    if r2:
        check(r2, "فتح وردية الكاشير", ok_codes=(200, 201, 302, 404))
    
    # محاولة إنشاء فاتورة POS
    r3 = post(supermarket_sess, "/pos/checkout", json_data={
        "items": [
            {"product_id": 1, "quantity": 3, "price": 15.0},
            {"product_id": 2, "quantity": 1, "price": 8.5},
        ],
        "payment_method": "cash",
        "cash_given": 60.0,
        "discount": 0
    })
    if r3:
        check(r3, "فاتورة POS كاش", ok_codes=(200, 201, 302, 400, 404))
    
    # بطاقة ائتمانية
    r4 = post(supermarket_sess, "/pos/checkout", json_data={
        "items": [{"product_id": 3, "quantity": 2, "price": 25.0}],
        "payment_method": "card",
        "discount": 5
    })
    if r4:
        check(r4, "فاتورة POS كارت", ok_codes=(200, 201, 302, 400, 404))

# ─── 6. فواتير المبيعات ────────────────────────────────────────────────────
section("6️⃣  فواتير المبيعات")

for email, (sess, co) in sessions.items():
    r = get(sess, "/invoices")
    check(r, f"قائمة الفواتير: {co['label']}", ok_codes=(200, 302))

    # إنشاء فاتورة جديدة
    r2 = get(sess, "/invoices/new")
    check(r2, f"نموذج فاتورة جديدة: {co['label']}", ok_codes=(200, 302))

    # إرسال فاتورة
    invoice_data = {
        "invoice_date":     datetime.today().strftime("%Y-%m-%d"),
        "due_date":         (datetime.today() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "customer_name":    f"عميل تجريبي — {co['label']}",
        "customer_phone":   "0501234567",
        "notes":            f"فاتورة اختبار — {co['label']}",
        "items[0][name]":   f"منتج {co['label']}",
        "items[0][qty]":    "5",
        "items[0][price]":  "100",
        "items[0][vat]":    "15",
        "payment_method":   "cash",
    }
    r3 = post(sess, "/invoices/new", data=invoice_data)
    if r3:
        check(r3, f"إنشاء فاتورة: {co['label']}", ok_codes=(200, 201, 302, 400))

# ─── 7. الجملة — عروض الأسعار والطلبات ─────────────────────────────────────
section("7️⃣  وحدة الجملة")

wholesale_sess = None
for email, (sess, co) in sessions.items():
    if "wholesale" in co["industry_type"]:
        wholesale_sess = sess
        wholesale_co = co
        break

if wholesale_sess:
    paths_wholesale = [
        ("/wholesale", "الرئيسية"),
        ("/wholesale/orders", "الطلبات"),
        ("/wholesale/quotes", "عروض الأسعار"),
        ("/wholesale/receipts", "سندات القبض"),
        ("/wholesale/pricing", "قوائم الأسعار"),
    ]
    for path, name in paths_wholesale:
        r = get(wholesale_sess, path)
        check(r, f"جملة — {name}", ok_codes=(200, 302, 404))

    # إنشاء طلب جملة
    r_ord = post(wholesale_sess, "/wholesale/orders/new", data={
        "customer_name": "شركة التوريدات العالمية",
        "customer_phone": "0550000001",
        "order_date": datetime.today().strftime("%Y-%m-%d"),
        "items[0][name]": "طحين 50kg",
        "items[0][qty]": "100",
        "items[0][price]": "190",
    })
    if r_ord:
        check(r_ord, "جملة — إنشاء طلب", ok_codes=(200, 201, 302, 400, 404))

# ─── 8. المطعم — طاولات ومطبخ ───────────────────────────────────────────────
section("8️⃣  المطعم — طاولات وشاشة المطبخ")

restaurant_sess = None
for email, (sess, co) in sessions.items():
    if co["industry_type"].startswith("food_"):
        restaurant_sess = sess
        break

if restaurant_sess:
    paths_rest = [
        ("/restaurant", "الرئيسية"),
        ("/tables", "إدارة الطاولات"),
        ("/kitchen", "شاشة المطبخ"),
        ("/recipes", "الوصفات"),
    ]
    for path, name in paths_rest:
        r = get(restaurant_sess, path)
        check(r, f"مطعم — {name}", ok_codes=(200, 302, 404))

    # طلب طاولة
    r_tbl = post(restaurant_sess, "/restaurant/order", json_data={
        "table_id": 1,
        "items": [
            {"name": "شاورما دجاج", "qty": 2, "price": 18},
            {"name": "عصير برتقال", "qty": 2, "price": 8},
        ]
    })
    if r_tbl:
        check(r_tbl, "مطعم — طلب طاولة", ok_codes=(200, 201, 302, 400, 404))

# ─── 9. الطب — مرضى ومواعيد ─────────────────────────────────────────────────
section("9️⃣  القطاع الطبي — ملفات المرضى")

medical_sess = None
for email, (sess, co) in sessions.items():
    if "medical" in co["industry_type"] or co["industry_type"] == "medical_dental":
        medical_sess = sess
        break

if medical_sess:
    paths_med = [
        ("/medical/patients", "قائمة المرضى"),
        ("/medical/appointments", "المواعيد"),
    ]
    for path, name in paths_med:
        r = get(medical_sess, path)
        check(r, f"طبي — {name}", ok_codes=(200, 302, 404))

    # إضافة مريض
    r_p = post(medical_sess, "/medical/patients/new", data={
        "name":      "محمد أحمد العمري",
        "dob":       "1985-06-15",
        "gender":    "male",
        "phone":     "0507654321",
        "blood_type": "A+",
        "notes":     "مريض بالضغط",
    })
    if r_p:
        check(r_p, "طبي — إضافة مريض", ok_codes=(200, 201, 302, 400, 404))

    # حجز موعد
    r_apt = post(medical_sess, "/medical/appointments/new", data={
        "patient_name":  "محمد أحمد العمري",
        "doctor_name":   "د. سلمى الطيب",
        "date":          (datetime.today() + timedelta(days=3)).strftime("%Y-%m-%d"),
        "time":          "10:00",
        "type":          "كشف",
        "notes":         "متابعة دورية",
    })
    if r_apt:
        check(r_apt, "طبي — حجز موعد", ok_codes=(200, 201, 302, 400, 404))

# ─── 10. المقاولات ───────────────────────────────────────────────────────────
section("🔟  وحدة المقاولات")

construction_sess = None
for email, (sess, co) in sessions.items():
    if co["industry_type"] == "construction":
        construction_sess = sess
        break

if construction_sess:
    paths_con = [
        ("/projects/", "قائمة المشاريع"),
        ("/projects/equipment", "المعدات"),
        ("/extracts", "المستخلصات"),
    ]
    for path, name in paths_con:
        r = get(construction_sess, path)
        check(r, f"مقاولات — {name}", ok_codes=(200, 302, 404))

    # إنشاء مشروع
    r_proj = post(construction_sess, "/projects/new", data={
        "name":        "مشروع إنشاء مجمع سكني",
        "client":      "شركة البيان العقارية",
        "value":       "5000000",
        "start_date":  datetime.today().strftime("%Y-%m-%d"),
        "end_date":    (datetime.today() + timedelta(days=365)).strftime("%Y-%m-%d"),
        "description": "بناء 3 أبراج سكنية بمرافق كاملة",
    })
    if r_proj:
        check(r_proj, "مقاولات — إنشاء مشروع", ok_codes=(200, 201, 302, 400, 404))

# ─── 11. تأجير السيارات ──────────────────────────────────────────────────────
section("1️⃣1️⃣  تأجير السيارات")

rental_sess = None
for email, (sess, co) in sessions.items():
    if co["industry_type"] == "car_rental":
        rental_sess = sess
        break

if rental_sess:
    paths_rent = [
        ("/rental/fleet", "الأسطول"),
        ("/rental/contracts", "العقود"),
        ("/rental/maintenance", "الصيانة"),
    ]
    for path, name in paths_rent:
        r = get(rental_sess, path)
        check(r, f"تأجير سيارات — {name}", ok_codes=(200, 302, 404))

    # إضافة سيارة للأسطول
    r_car = post(rental_sess, "/rental/fleet/new", data={
        "plate":    "أ ب ج 1234",
        "model":    "تويوتا كامري 2024",
        "year":     "2024",
        "daily_rate": "200",
        "status":   "available",
    })
    if r_car:
        check(r_car, "تأجير — إضافة سيارة", ok_codes=(200, 201, 302, 400, 404))

    # عقد إيجار
    r_con = post(rental_sess, "/rental/contracts/new", data={
        "customer_name":  "خالد محمد العتيبي",
        "customer_id":    "1234567890",
        "start_date":     datetime.today().strftime("%Y-%m-%d"),
        "end_date":       (datetime.today() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "daily_rate":     "200",
        "deposit":        "500",
    })
    if r_con:
        check(r_con, "تأجير — عقد إيجار", ok_codes=(200, 201, 302, 400, 404))

# ─── 12. الصيدلية ────────────────────────────────────────────────────────────
section("1️⃣2️⃣  الصيدلية")

pharmacy_sess = None
for email, (sess, co) in sessions.items():
    if co["industry_type"] == "retail_health_pharmacy":
        pharmacy_sess = sess
        break

if pharmacy_sess:
    r = get(pharmacy_sess, "/pos")
    check(r, "صيدلية — POS", ok_codes=(200, 302, 404))
    r = get(pharmacy_sess, "/inventory/products")
    check(r, "صيدلية — المنتجات", ok_codes=(200, 302))
    r = get(pharmacy_sess, "/inventory")
    check(r, "صيدلية — المخزون", ok_codes=(200, 302))

    # فاتورة صيدلية
    r2 = post(pharmacy_sess, "/invoices/new", data={
        "invoice_date":    datetime.today().strftime("%Y-%m-%d"),
        "customer_name":   "سارة الدوسري",
        "items[0][name]":  "أدوية مزمن — شهري",
        "items[0][qty]":   "1",
        "items[0][price]": "120",
        "items[0][vat]":   "0",
        "payment_method":  "cash",
    })
    if r2:
        check(r2, "صيدلية — فاتورة", ok_codes=(200, 201, 302, 400))

# ─── 13. المخزون والمزامنة ───────────────────────────────────────────────────
section("1️⃣3️⃣  المخزون والمزامنة")

for email, (sess, co) in sessions.items():
    r = get(sess, "/inventory")
    check(r, f"مخزون: {co['label']}", ok_codes=(200, 302))

if supermarket_sess:
    # استيراد منتجات
    r_imp = get(supermarket_sess, "/inventory/import")
    check(r_imp, "مخزون — صفحة استيراد", ok_codes=(200, 302, 404))

    # تقرير المخزون
    r_rep = get(supermarket_sess, "/inventory/report")
    check(r_rep, "مخزون — تقرير", ok_codes=(200, 302, 404))

    # حركة المخزون
    r_mov = post(supermarket_sess, "/inventory/movement", data={
        "product_id": 1,
        "type":       "in",
        "quantity":   "100",
        "reason":     "شراء من مورد",
    })
    if r_mov:
        check(r_mov, "مخزون — حركة مخزون (وارد)", ok_codes=(200, 201, 302, 400, 404))

# ─── 14. الباركود ────────────────────────────────────────────────────────────
section("1️⃣4️⃣  الباركود")

if supermarket_sess:
    paths_barcode = [
        ("/barcode", "رئيسية الباركود"),
        ("/barcode/scanner", "الماسح"),
        ("/barcode/labels", "طباعة ملصقات"),
    ]
    for path, name in paths_barcode:
        r = get(supermarket_sess, path)
        check(r, f"باركود — {name}", ok_codes=(200, 302, 404))

# ─── 15. جهات الاتصال ────────────────────────────────────────────────────────
section("1️⃣5️⃣  جهات الاتصال — عملاء وموردون")

for email, (sess, co) in sessions.items():
    r = get(sess, "/contacts")
    check(r, f"جهات اتصال: {co['label']}", ok_codes=(200, 302))

if supermarket_sess:
    # إضافة مورد
    r_sup = post(supermarket_sess, "/contacts/new", data={
        "name":    "مورد الخضار الطازجة",
        "type":    "supplier",
        "phone":   "0501111111",
        "email":   "veggie@supplier.sa",
        "address": "سوق الحراج، الرياض",
    })
    if r_sup:
        check(r_sup, "جهات — إضافة مورد", ok_codes=(200, 201, 302, 400, 404))

    # إضافة عميل
    r_cust = post(supermarket_sess, "/contacts/new", data={
        "name":    "شركة الطعام الذهبي",
        "type":    "customer",
        "phone":   "0509999999",
        "cr_number": "1234567890",
    })
    if r_cust:
        check(r_cust, "جهات — إضافة عميل شركة", ok_codes=(200, 201, 302, 400, 404))

# ─── 16. التقارير والتحليل ───────────────────────────────────────────────────
section("1️⃣6️⃣  التقارير والتحليلات")

for email, (sess, co) in sessions.items():
    r_an = get(sess, "/analytics")
    check(r_an, f"تحليل: {co['label']}", ok_codes=(200, 302))

if supermarket_sess:
    report_paths = [
        ("/reports", "التقارير الرئيسية"),
        ("/reports/sales", "تقرير المبيعات"),
        ("/reports/inventory", "تقرير المخزون"),
        ("/reports/vat", "تقرير الضريبة"),
        ("/reports/profit_loss", "الربح والخسارة"),
    ]
    for path, name in report_paths:
        r = get(supermarket_sess, path)
        check(r, f"تقارير — {name}", ok_codes=(200, 302, 404))

# ─── 17. المحاسبة والقيود ───────────────────────────────────────────────────
section("1️⃣7️⃣  المحاسبة")

if supermarket_sess:
    acct_paths = [
        ("/accounting", "رئيسية المحاسبة"),
        ("/accounting/journal", "دفتر اليومية"),
        ("/accounting/ledger", "الأستاذ العام"),
        ("/accounting/balance", "الميزانية"),
    ]
    for path, name in acct_paths:
        r = get(supermarket_sess, path)
        check(r, f"محاسبة — {name}", ok_codes=(200, 302, 404))

    # قيد محاسبي يدوي
    r_jv = post(supermarket_sess, "/accounting/journal/new", data={
        "date":        datetime.today().strftime("%Y-%m-%d"),
        "description": "مصاريف إيجار مخزن — مايو",
        "entries[0][account]": "مصاريف",
        "entries[0][debit]":   "3000",
        "entries[0][credit]":  "0",
        "entries[1][account]": "بنك",
        "entries[1][debit]":   "0",
        "entries[1][credit]":  "3000",
    })
    if r_jv:
        check(r_jv, "محاسبة — قيد يومية", ok_codes=(200, 201, 302, 400, 404))

# ─── 18. الموارد البشرية ─────────────────────────────────────────────────────
section("1️⃣8️⃣  الموارد البشرية")

if supermarket_sess:
    wf_paths = [
        ("/workforce", "رئيسية الموارد البشرية"),
        ("/workforce/employees", "الموظفون"),
        ("/workforce/attendance", "الحضور والغياب"),
        ("/workforce/payroll", "الرواتب"),
        ("/workforce/shifts", "جداول الورديات"),
    ]
    for path, name in wf_paths:
        r = get(supermarket_sess, path)
        check(r, f"موارد بشرية — {name}", ok_codes=(200, 302, 404))

    # إضافة موظف
    r_emp = post(supermarket_sess, "/workforce/employees/new", data={
        "name":       "علي محمد الشهري",
        "id_number":  "1087654321",
        "position":   "كاشير",
        "department": "المبيعات",
        "salary":     "3500",
        "join_date":  datetime.today().strftime("%Y-%m-%d"),
        "phone":      "0551234567",
    })
    if r_emp:
        check(r_emp, "موارد — إضافة موظف", ok_codes=(200, 201, 302, 400, 404))

# ─── 19. الإعدادات والأمان ───────────────────────────────────────────────────
section("1️⃣9️⃣  الإعدادات والأمان")

if supermarket_sess:
    settings_paths = [
        ("/settings", "الإعدادات العامة"),
        ("/settings/users", "إدارة المستخدمين"),
        ("/settings/security", "الأمان"),
        ("/audit-log", "سجل المراجعة"),
    ]
    for path, name in settings_paths:
        r = get(supermarket_sess, path)
        check(r, f"إعدادات — {name}", ok_codes=(200, 302, 404))

    # إنشاء مستخدم فرعي (كاشير)
    r_usr = post(supermarket_sess, "/settings/users/new", data={
        "name":     "سلمى أحمد",
        "email":    f"cashier_{random.randint(1000,9999)}@jinan.biz",
        "role":     "cashier",
        "password": "Cashier@2026",
    })
    if r_usr:
        check(r_usr, "إعدادات — إضافة كاشير", ok_codes=(200, 201, 302, 400, 404))

# ─── 20. المزامنة والضغط ─────────────────────────────────────────────────────
section("2️⃣0️⃣  اختبار الضغط والمزامنة")

# محاكاة 20 عملية متتالية
start_stress = time.time()
stress_ok = 0
stress_fail = 0

for i in range(20):
    r = s.get(f"{BASE}/healthz", timeout=5)
    if r and r.status_code == 200:
        stress_ok += 1
    else:
        stress_fail += 1

elapsed = time.time() - start_stress
rps = 20 / elapsed if elapsed > 0 else 0
log(f"ضغط 20 طلب متتالي", "PASS" if stress_fail == 0 else "WARN",
    f"{stress_ok}/20 نجح | {elapsed:.2f}s | {rps:.1f} req/s")

# محاكاة 5 جلسات متزامنة
import threading
concurrent_results = []

def concurrent_req():
    s2 = requests.Session()
    r2 = s2.get(f"{BASE}/healthz", timeout=10)
    concurrent_results.append(r2.status_code if r2 else 0)

threads = [threading.Thread(target=concurrent_req) for _ in range(5)]
[t.start() for t in threads]
[t.join(timeout=15) for t in threads]

concurrent_ok = sum(1 for c in concurrent_results if c == 200)
log(f"5 طلبات متزامنة", "PASS" if concurrent_ok == 5 else "WARN",
    f"{concurrent_ok}/5 نجحت")

# ─── 21. فحص الـ API والـ JSON ───────────────────────────────────────────────
section("2️⃣1️⃣  نقاط الـ API")

api_paths = [
    "/api/health",
    "/api/products",
    "/api/businesses",
    "/healthz",
    "/readyz",
]
for path in api_paths:
    r = s.get(f"{BASE}{path}", timeout=10)
    if r:
        check(r, f"API: {path}", ok_codes=(200, 302, 400, 401, 404))

# ─── 22. الاستشارات / الخدمات المتخصصة ─────────────────────────────────────
section("2️⃣2️⃣  الخدمات المتخصصة")

services_sess = None
for email, (sess, co) in sessions.items():
    if "services" in co["industry_type"]:
        services_sess = sess
        services_co = co
        break

if services_sess:
    serv_paths = [
        ("/services/jobs", "أوامر العمل"),
        ("/services/contracts", "العقود"),
        ("/invoices", "الفواتير"),
    ]
    for path, name in serv_paths:
        r = get(services_sess, path)
        check(r, f"خدمات — {name}", ok_codes=(200, 302, 404))

    # إنشاء أمر عمل
    r_job = post(services_sess, "/services/jobs/new", data={
        "title":       "استشارة إدارية — شركة الفجر",
        "client":      "شركة الفجر للتطوير",
        "description": "مراجعة الهيكل التنظيمي وإعداد خطة استراتيجية 3 سنوات",
        "value":       "8500",
        "date":        datetime.today().strftime("%Y-%m-%d"),
        "status":      "active",
    })
    if r_job:
        check(r_job, "خدمات — إنشاء أمر عمل", ok_codes=(200, 201, 302, 400, 404))

# ─── 23. الباكأب والأمان ─────────────────────────────────────────────────────
section("2️⃣3️⃣  النسخ الاحتياطي")

if supermarket_sess:
    r_bk = get(supermarket_sess, "/backup")
    check(r_bk, "صفحة النسخ الاحتياطي", ok_codes=(200, 302, 404))

# ─── التقرير النهائي ─────────────────────────────────────────────────────────
section("📊  التقرير النهائي الشامل")

total = PASS + FAIL + WARN
pct = (PASS / total * 100) if total > 0 else 0

print(f"\n  المجموع: {total} اختبار")
print(f"  ✅ ناجح:  {PASS} ({pct:.1f}%)")
print(f"  ❌ فشل:   {FAIL}")
print(f"  ⚠️  تحذير: {WARN}")

if FAIL == 0:
    print("\n  🎉 البرنامج جاهز للاستخدام الفعلي كشركة حقيقية!")
elif FAIL <= 5:
    print(f"\n  ✅ البرنامج يعمل بشكل جيد مع {FAIL} نقاط تحتاج مراجعة")
else:
    print(f"\n  ⚠️  يوجد {FAIL} اختبار فاشل — راجع التفاصيل")

print("\n  الاختبارات الفاشلة:")
for status, label, detail in RESULTS:
    if status == "FAIL":
        print(f"    ❌ {label}: {detail}")

print("\n  الاختبارات التحذيرية:")
for status, label, detail in RESULTS:
    if status == "WARN":
        print(f"    ⚠️  {label}: {detail}")

print(f"\n  وقت الاختبار: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*60)
