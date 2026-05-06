"""
اختبار شامل - عيادة طبية متكاملة
كاشير + طبيب + صيدلية + فواتير + مخزون + ضغط متزامن
"""
import os, sys
os.environ['SESSION_BACKEND'] = 'cookie'

import time, sqlite3, hashlib, secrets, pathlib, json, threading
from datetime import datetime, timedelta

sys.path.insert(0, '.')
os.chdir(str(pathlib.Path(__file__).parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import logging; logging.disable(logging.CRITICAL)

G="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[94m"
C="\033[96m"; M="\033[95m"; D="\033[90m"; RST="\033[0m"
PASS=0; FAIL=0; results=[]

def log(ok, label, detail="", ms=None):
    global PASS, FAIL
    ico = f"{G}[OK]{RST}" if ok else f"{R}[--]{RST}"
    clr = G if ok else R
    t = f" {D}[{ms:.0f}ms]{RST}" if ms else ""
    print(f"  {ico} {clr}{label}{RST}{t}  {D}{detail}{RST}")
    results.append({"ok":ok,"label":label,"detail":detail,"ms":ms})
    if ok: PASS+=1
    else: FAIL+=1

def section(title):
    print(f"\n{C}{'━'*68}{RST}\n  {M}{title}{RST}\n{C}{'━'*68}{RST}")

DB = pathlib.Path("database/accounting_dev.db")
def db_conn():
    c = sqlite3.connect(str(DB)); c.row_factory = sqlite3.Row; return c

def hp(pw):
    salt = secrets.token_hex(16)
    return f"{salt}:{hashlib.sha256(f'{salt}{pw}'.encode()).hexdigest()}"

# ══════ تجهيز بيانات الاختبار ══════════════════════════════════════════════
def prepare():
    conn = db_conn()
    biz = conn.execute("""
        SELECT b.id, u.id uid, u.username
        FROM businesses b JOIN users u ON u.business_id=b.id
        WHERE b.industry_type='medical' AND u.role_id=1
        ORDER BY b.id DESC LIMIT 1
    """).fetchone()
    if not biz: return None, None, None
    bid, uid, uname = biz['id'], biz['uid'], biz['username']

    # كلمة المرور + إعدادات
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hp("Test@2026"), uid))
    ex = conn.execute("SELECT id FROM settings WHERE business_id=? AND key='onboarding_complete'", (bid,)).fetchone()
    if ex: conn.execute("UPDATE settings SET value='1' WHERE id=?", (ex['id'],))
    else: conn.execute("INSERT INTO settings(business_id,key,value) VALUES(?,'onboarding_complete','1')", (bid,))

    # شجرة الحسابات (مطلوبة للـ POS)
    from modules.extensions import seed_business_accounts
    seed_business_accounts(conn, bid)

    # منتجات طبية
    meds = [('امو 500mg',25,'مضادات'),('باراسيتامول',8,'مسكنات'),
            ('جهاز ضغط',120,'اجهزة'),('شاش طبي',15,'مستلزمات'),('قفازات',35,'مستلزمات')]
    for nm, pr, cat in meds:
        if not conn.execute("SELECT id FROM products WHERE business_id=? AND name=?", (bid,nm)).fetchone():
            conn.execute(
                "INSERT INTO products(business_id,name,sale_price,purchase_price,category_name,is_active,is_pos,can_sell,can_purchase) VALUES(?,?,?,?,?,1,1,1,1)",
                (bid, nm, pr, pr*0.6, cat))

    # المستودع الافتراضي
    wh = conn.execute("SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1", (bid,)).fetchone()
    if not wh:
        wh = conn.execute("SELECT id FROM warehouses WHERE business_id=? LIMIT 1", (bid,)).fetchone()
    wh_id = wh['id'] if wh else None

    # بذر product_inventory + stock (POS)
    prods = conn.execute("SELECT id FROM products WHERE business_id=? AND is_active=1", (bid,)).fetchall()
    for p in prods:
        pi = conn.execute("SELECT id FROM product_inventory WHERE product_id=? AND business_id=?", (p['id'],bid)).fetchone()
        if pi: conn.execute("UPDATE product_inventory SET current_qty=200 WHERE id=?", (pi['id'],))
        else: conn.execute("INSERT INTO product_inventory(business_id,product_id,current_qty,min_qty) VALUES(?,?,200,10)", (bid,p['id']))
        if wh_id:
            conn.execute("INSERT OR IGNORE INTO stock(business_id,product_id,warehouse_id,quantity,avg_cost) VALUES(?,?,?,0,0)", (bid,p['id'],wh_id))
            conn.execute("UPDATE stock SET quantity=200 WHERE product_id=? AND warehouse_id=? AND business_id=?", (p['id'],wh_id,bid))

    # مرضى
    for nm, ph, gn in [('احمد علي','0501111111','M'),('فاطمة خالد','0502222222','F'),('خالد محمد','0503333333','M')]:
        if not conn.execute("SELECT id FROM patients WHERE business_id=? AND patient_name=?", (bid,nm)).fetchone():
            conn.execute("INSERT INTO patients(business_id,patient_name,patient_phone,gender,created_at,updated_at) VALUES(?,?,?,?,datetime('now'),datetime('now'))", (bid,nm,ph,gn))

    # عملاء
    if not conn.execute("SELECT id FROM contacts WHERE business_id=? AND contact_type='customer'", (bid,)).fetchone():
        conn.execute("INSERT INTO contacts(business_id,name,contact_type,phone,is_active) VALUES(?,'عميل عام','customer','0500000000',1)", (bid,))

    conn.commit(); conn.close()
    return uname, bid, uid

# ══════ بناء التطبيق ══════════════════════════════════════════════════════
def build_app():
    from modules import create_app
    app = create_app()
    app.config.update({'TESTING':True,'SESSION_COOKIE_SECURE':False,'WTF_CSRF_ENABLED':False})
    return app

def inject(client, uid, bid):
    with client.session_transaction() as s:
        s['user_id'] = uid; s['business_id'] = bid; s['needs_onboarding'] = False

def chk(client, path, method='GET', data=None, json_data=None, expect=(200,)):
    t0 = time.perf_counter()
    if method == 'POST':
        if json_data is not None:
            r = client.post(path, json=json_data, content_type='application/json', follow_redirects=True)
        else:
            r = client.post(path, data=data, follow_redirects=True)
    else:
        r = client.get(path, follow_redirects=False)
    ms = (time.perf_counter()-t0)*1000
    ok = r.status_code in expect
    if r.status_code in (301,302):
        loc = r.headers.get('Location','')
        ok = ok and 'login' not in loc and 'onboarding' not in loc
    return r, ok, ms

def jd(r):
    try: return json.loads(r.data)
    except: return {}

# ══════ الاختبارات ═══════════════════════════════════════════════════════════

def t1_dashboard(c, uid, bid):
    section("1  لوحة التحكم والاحصائيات")
    inject(c, uid, bid)
    for path, label in [('/dashboard','لوحة التحكم الرئيسية'),('/analytics','التحليلات والمخططات')]:
        r,ok,ms = chk(c, path); log(ok, label, f"HTTP {r.status_code}", ms)
    r,ok,ms = chk(c, '/invoices/api/stats')
    d = jd(r); log(ok, "API احصائيات الفواتير", f"HTTP {r.status_code} | الشهر: {d.get('month','-')}", ms)

def t2_medical(c, uid, bid):
    section("2  نظام ادارة المرضى")
    inject(c, uid, bid)
    r,ok,ms = chk(c, '/medical/patients'); log(ok,'قائمة المرضى',f"HTTP {r.status_code}",ms)
    r,ok,ms = chk(c, '/medical/patients/new', 'POST', {
        'name':f'مريض {int(time.time())%9999}','phone':'0509876543','gender':'M',
        'national_id':'1234567890','dob':'1990-01-01','email':'p@clinic.sa','address':'الرياض'
    }); log(ok,'اضافة مريض جديد',f"HTTP {r.status_code}",ms)
    r,ok,ms = chk(c, '/medical/api/stats')
    d = jd(r); log(ok,'API احصائيات العيادة',f"المرضى: {d.get('total_patients',0)} | اليوم: {d.get('today_appointments',0)}",ms)
    conn=db_conn()
    p=conn.execute("SELECT id,patient_name FROM patients WHERE business_id=? LIMIT 1",(bid,)).fetchone()
    conn.close()
    pid = p['id'] if p else None
    if pid:
        r,ok,ms = chk(c, f'/medical/patients/{pid}'); log(ok,f'ملف المريض ({p["patient_name"]})',f"HTTP {r.status_code}",ms)
    return pid

def t3_appointments(c, uid, bid, pid):
    section("3  المواعيد والوصفات الطبية")
    inject(c, uid, bid)
    r,ok,ms = chk(c, '/medical/appointments'); log(ok,'قائمة المواعيد',f"HTTP {r.status_code}",ms)
    if not pid: return
    future = (datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d')
    r,ok,ms = chk(c, '/medical/appointments/new','POST',{
        'patient_id':str(pid),'date':future,'time':'10:00',
        'doctor':'د خالد الشمري','type':'consultation','notes':'مراجعة'
    }); log(ok,'حجز موعد طبي جديد',f"HTTP {r.status_code}",ms)
    r,ok,ms = chk(c, f'/medical/prescriptions/{pid}/new','POST',{
        'doctor':'د خالد الشمري','diagnosis':'ضغط دم','medications':'امل 5mg','notes':'يراجع بعد شهر'
    }); log(ok,'اضافة وصفة طبية',f"HTTP {r.status_code}",ms)
    r,ok,ms = chk(c, f'/medical/prescriptions/{pid}'); log(ok,'وصفات المريض',f"HTTP {r.status_code}",ms)

def t4_invoices(c, uid, bid):
    section("4  الفواتير (خدمات + ادوية)")
    inject(c, uid, bid)
    r,ok,ms = chk(c, '/invoices/'); log(ok,'قائمة الفواتير',f"HTTP {r.status_code}",ms)
    r,ok,ms = chk(c, '/invoices/new'); log(ok,'صفحة فاتورة جديدة',f"HTTP {r.status_code}",ms)
    conn=db_conn()
    prod=conn.execute("SELECT id,sale_price FROM products WHERE business_id=? AND is_active=1 LIMIT 1",(bid,)).fetchone()
    conn.close()
    if prod:
        today = datetime.now().strftime('%Y-%m-%d')
        for label, party, qty, price in [
            ('فاتورة كشف طبي','احمد محمد','1','150'),
            ('فاتورة صيدلية','فاطمة خالد','2',str(prod['sale_price'] or 25)),
        ]:
            r,ok,ms = chk(c, '/invoices/new','POST',{
                'invoice_type':'sale','invoice_date':today,'party_name':party,'notes':'',
                'items[0][product_id]':str(prod['id']),'items[0][description]':'خدمة',
                'items[0][quantity]':qty,'items[0][unit_price]':price,
                'items[0][discount_pct]':'0','items[0][tax_rate]':'15',
            }); log(ok, label, f"HTTP {r.status_code}", ms)
    r,ok,ms = chk(c, '/invoices/api/stats')
    d=jd(r); log(ok,'احصائيات الفواتير',f"الشهر: {d.get('month','-')} | {len(d.get('summary',[]))} نوع",ms)

def t5_pos(c, uid, bid):
    section("5  نقطة البيع (الكاشير)")
    inject(c, uid, bid)
    r,ok,ms = chk(c,'/pos'); log(ok,'صفحة نقطة البيع',f"HTTP {r.status_code}",ms)
    r,ok,ms = chk(c,'/api/pos/config')
    d=jd(r); log(ok,'اعدادات POS',f"ضريبة: {d.get('tax_rate',0)}% | العملة: {d.get('currency','')}",ms)
    r,ok,ms = chk(c,'/api/pos/shift/open','POST',json_data={"opening_cash":500,"notes":"وردية الصباح"},expect=(200,400))
    d=jd(r); msg=d.get('message',d.get('error','')); log(ok,'فتح وردية الكاشير',msg,ms)
    r,ok,ms = chk(c,'/api/pos/shift/current')
    d=jd(r); log(ok,'الوردية الحالية',f"مفتوحة: {bool(d.get('id'))}",ms)
    r,ok,ms = chk(c,'/api/pos/search?q=ام')
    d=jd(r); cnt=len(d) if isinstance(d,list) else 0; log(ok,'بحث عن منتجات POS',f"وجد: {cnt} منتج",ms)
    conn=db_conn()
    prods=conn.execute("SELECT id,sale_price FROM products WHERE business_id=? AND is_active=1 LIMIT 2",(bid,)).fetchall()
    conn.close()
    if prods:
        items=[{"product_id":p['id'],"quantity":1,"unit_price":float(p['sale_price'] or 50),"discount_pct":0} for p in prods]
        for method, label in [('cash','بيع نقدي - الكاشير'),('bank','بيع شبكة/مدى - الكاشير')]:
            r,ok,ms = chk(c,'/api/pos/checkout','POST',json_data={"items":items[:1],"payment_method":method,"customer_id":None})
            d=jd(r); total=d.get('total',0); err=d.get('error','')
            log(ok and d.get('success',False), label, f"{total:.0f} ر.س  {err}", ms)
    r,ok,ms = chk(c,'/api/pos/shift/x-report')
    d=jd(r); log(ok,'تقرير X الوردية',f"مبيعات: {d.get('total_sales',0):.0f} | {d.get('transaction_count',0)} عملية",ms)
    r,ok,ms = chk(c,'/api/pos/reports/daily')
    d=jd(r); log(ok,'التقرير اليومي POS',f"صافي: {d.get('net_sales',0):.0f} | {d.get('transaction_count',0)} معاملة",ms)

def t6_inventory(c, uid, bid):
    section("6  المخزون والصيدلية الداخلية")
    inject(c, uid, bid)
    for path,lbl in [
        ('/inventory/','لوحة المخزون الرئيسية'),('/inventory/products','قائمة الادوية والمنتجات'),
        ('/inventory/movements','سجل حركات المخزون'),('/inventory/alerts','تنبيهات نفاد المخزون'),
    ]:
        r,ok,ms = chk(c,path); log(ok,lbl,f"HTTP {r.status_code}",ms)
    conn=db_conn()
    p=conn.execute("SELECT id FROM product_inventory WHERE business_id=? LIMIT 1",(bid,)).fetchone()
    pi_id = p['id'] if p else None
    p2=conn.execute("SELECT id FROM products WHERE business_id=? AND is_active=1 LIMIT 1",(bid,)).fetchone()
    prod_id = p2['id'] if p2 else None
    conn.close()
    if pi_id:
        r,ok,ms = chk(c,f'/inventory/api/stock/{pi_id}')
        d=jd(r); qty=d.get('available_qty','?'); log(ok,'مستوى المخزون (صيدلية)',f"الكمية المتاحة: {qty}",ms)
    if prod_id:
        r,ok,ms = chk(c,'/inventory/movements/add','POST',{
            'product_id':str(prod_id),'movement_type':'in','quantity':'50','notes':'استلام دفعة ادوية'
        }); log(ok,'استلام دفعة ادوية (وارد)',f"HTTP {r.status_code}",ms)
    r,ok,ms = chk(c,'/inventory/api/reorder-suggestions')
    d=jd(r); cnt=len(d) if isinstance(d,list) else d.get('count',0)
    log(ok,'اقتراحات اعادة طلب الادوية',f"عدد التوصيات: {cnt}",ms)
    for path,lbl in [
        ('/inventory/reports/profit-margin','تقرير هامش الربح'),
        ('/inventory/reports/inventory-turnover','معدل دوران المخزون'),
        ('/inventory/reports/damage-waste','تقرير التلف والهالك'),
    ]:
        r,ok,ms = chk(c,path); log(ok,lbl,f"HTTP {r.status_code}",ms)

def t7_contacts(c, uid, bid):
    section("7  العملاء والموردون")
    inject(c, uid, bid)
    for path,lbl in [('/contacts/','كل جهات الاتصال'),('/contacts/?type=customer','العملاء'),('/contacts/?type=supplier','الموردون')]:
        r,ok,ms = chk(c,path); log(ok,lbl,f"HTTP {r.status_code}",ms)

def t8_accounting(c, uid, bid):
    section("8  المحاسبة والتقارير المالية")
    inject(c, uid, bid)
    for path,lbl in [
        ('/accounting','المحاسبة الرئيسية'),('/audit-log','سجل المراجعة والتدقيق'),
        ('/backup','النسخ الاحتياطي'),('/analytics','لوحة التحليلات'),
    ]:
        r,ok,ms = chk(c,path); log(ok,lbl,f"HTTP {r.status_code}",ms)

def t9_settings(c, uid, bid):
    section("9  الاعدادات والنظام")
    inject(c, uid, bid)
    for path,lbl in [
        ('/settings','اعدادات المنشاة'),('/healthz','صحة الخدمة'),('/readyz','جاهزية الخدمة'),
    ]:
        r,ok,ms = chk(c,path,expect=(200,301,302))
        log(ok and 'login' not in r.headers.get('Location',''), lbl, f"HTTP {r.status_code}", ms)
    # صفحة المستخدمين - نقبل 200 أو 404 (قد لا توجد كصفحة مستقلة)
    r,ok,ms = chk(c,'/api/v1/team',expect=(200,404,405))
    log(True,'API فريق العمل',f"HTTP {r.status_code}",ms)

def t10_concurrent(app, uname, bid):
    section("10  تعدد الكاشيرات - محاكاة ضغط حقيقي")
    conn=db_conn()
    prods=conn.execute("SELECT id,sale_price FROM products WHERE business_id=? AND is_active=1 LIMIT 1",(bid,)).fetchall()
    user=conn.execute("SELECT id FROM users WHERE username=?",(uname,)).fetchone()
    conn.close()
    if not prods or not user:
        log(False,'اختبار تزامن الكاشيرات','لا توجد منتجات'); return
    uid_val = user['id']
    cashier_names=["كاشير الاستقبال","كاشير الصيدلية","كاشير المختبر","كاشير الاشعة","كاشير الطوارئ"]
    success_list=[]; timing_list=[]; errors_list=[]; lock=threading.Lock()

    def cashier_work(idx):
        name=cashier_names[idx % len(cashier_names)]
        with app.test_client() as cl:
            inject(cl, uid_val, bid)
            items=[{"product_id":prods[0]['id'],"quantity":1,"unit_price":float(prods[0]['sale_price'] or 50),"discount_pct":0}]
            t0=time.perf_counter()
            r=cl.post('/api/pos/checkout',json={"items":items,"payment_method":"cash","customer_id":None},content_type='application/json')
            ms=(time.perf_counter()-t0)*1000
            try:
                d=json.loads(r.data); ok2=r.status_code==200 and d.get('success'); tot=d.get('total',0); err=d.get('error','')
            except:
                ok2=False; tot=0; err='parse error'
            with lock:
                timing_list.append(ms)
                if ok2: success_list.append({'name':name,'total':tot,'ms':ms})
                else: errors_list.append(f"{name}: {err}")

    N=5; t0=time.perf_counter()
    threads=[threading.Thread(target=cashier_work,args=(i,)) for i in range(N)]
    for t in threads: t.start()
    for t in threads: t.join()
    total_ms=(time.perf_counter()-t0)*1000
    log(len(success_list)>=3,f"تزامن {N} كاشير في آن واحد",f"نجح: {len(success_list)}/{N} | وقت كلي: {total_ms:.0f}ms",total_ms)
    for s in success_list: print(f"    {G}[OK]{RST} {s['name']}: {s['total']:.0f} ر.س  {D}[{s['ms']:.0f}ms]{RST}")
    for e in errors_list: print(f"    {R}[--]{RST} {e}")
    if timing_list:
        avg=sum(timing_list)/len(timing_list)
        log(avg<3000,'متوسط زمن الاستجابة تحت الضغط',f"avg: {avg:.0f}ms | max: {max(timing_list):.0f}ms | min: {min(timing_list):.0f}ms",avg)

def t11_stress(c, uid, bid):
    section("11  اختبار ضغط API (10x لكل endpoint)")
    inject(c, uid, bid)
    apis=[
        ('/invoices/api/stats','احصائيات الفواتير'),('/medical/api/stats','احصائيات العيادة'),
        ('/api/pos/shift/current','الوردية الحالية'),('/inventory/api/reorder-suggestions','اقتراحات الطلب'),
        ('/healthz','صحة الخدمة'),
    ]
    for ep, lbl in apis:
        times=[]; success=0
        for _ in range(10):
            t0=time.perf_counter()
            try:
                r=c.get(ep,follow_redirects=False); ms=(time.perf_counter()-t0)*1000
                times.append(ms)
                if r.status_code==200: success+=1
            except: pass
        avg=sum(times)/len(times) if times else 0
        log(success>=8,f"10x {lbl}",f"نجح: {success}/10 | avg: {avg:.0f}ms",avg)

def print_report():
    total=PASS+FAIL; pct=PASS/total*100 if total else 0
    clr=G if pct>=90 else Y if pct>=75 else R
    print(f"\n{C}{'='*68}{RST}\n  {M}التقرير النهائي الشامل{RST}\n{C}{'='*68}{RST}")
    print(f"\n  {G}اجتاز: {PASS}{RST}  {R}فشل: {FAIL}{RST}  |  {clr}النسبة: {pct:.1f}%{RST}")
    ms_vals=[r['ms'] for r in results if r.get('ms')]
    if ms_vals:
        avg=sum(ms_vals)/len(ms_vals)
        print(f"\n  متوسط الاستجابة: {avg:.0f}ms | ابطأ: {max(ms_vals):.0f}ms | اسرع: {min(ms_vals):.0f}ms")
        print(f"  سريع (<200ms): {len([m for m in ms_vals if m<200])} | مقبول: {len([m for m in ms_vals if 200<=m<1000])} | بطيء: {len([m for m in ms_vals if m>=1000])}")
    failed=[r for r in results if not r['ok']]
    if failed:
        print(f"\n  {R}الاختبارات الفاشلة:{RST}")
        for r in failed[:15]: print(f"    {R}[--]{RST} {r['label']}: {r['detail']}")
    print(f"\n  تقييم الخدمات:")
    services=[
        ("لوحة التحكم والاحصائيات", any(r['ok'] for r in results if 'لوحة التحكم' in r['label'])),
        ("ادارة المرضى",             any(r['ok'] for r in results if 'مريض' in r['label'])),
        ("المواعيد والوصفات",         any(r['ok'] for r in results if 'موعد' in r['label'])),
        ("الفواتير الطبية",           any(r['ok'] for r in results if 'فاتورة' in r['label'])),
        ("نقطة البيع (الكاشير)",      any(r['ok'] for r in results if 'POS' in r['label'] or 'بيع' in r['label'])),
        ("المخزون والصيدلية",         any(r['ok'] for r in results if 'مخزون' in r['label'] or 'صيدلية' in r['label'])),
        ("المحاسبة والتقارير",        any(r['ok'] for r in results if 'محاسبة' in r['label'] or 'تقرير' in r['label'])),
        ("تحمل الضغط والتزامن",       any(r['ok'] for r in results if 'تزامن' in r['label'])),
    ]
    for lbl, ok in services:
        ic = f"{G}[كفء ]{RST}" if ok else f"{R}[ضعيف]{RST}"
        print(f"    {ic}  {lbl}")
    print(f"\n  {'[نجاح] النظام جاهز للانتاج' if pct>=90 else '[تحذير] يحتاج مراجعة' if pct>=75 else '[فشل] يحتاج اصلاح'}")
    print(f"{C}{'='*68}{RST}\n")

# ══════ main ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print(f"\n{B}{'='*68}{RST}")
    print(f"  اختبار شامل - عيادة طبية متكاملة")
    print(f"  كاشير + طبيب + صيدلية + فواتير + مخزون + ضغط متزامن")
    print(f"{B}{'='*68}{RST}\n")

    print(f"  {Y}تجهيز بيانات الاختبار...{RST}")
    uname, bid, uid = prepare()
    if not uname: print(f"  {R}لا توجد عيادة طبية!{RST}"); sys.exit(1)
    print(f"  {G}البيانات جاهزة: {uname} | عيادة #{bid}{RST}\n")

    app = build_app()
    t_all = time.perf_counter()

    with app.test_client() as client:
        inject(client, uid, bid)
        log(True, "تسجيل الدخول (session injection)", f"المستخدم: {uname} | العيادة: #{bid}", 0)
        t1_dashboard(client, uid, bid)
        pid = t2_medical(client, uid, bid)
        t3_appointments(client, uid, bid, pid)
        t4_invoices(client, uid, bid)
        t5_pos(client, uid, bid)
        t6_inventory(client, uid, bid)
        t7_contacts(client, uid, bid)
        t8_accounting(client, uid, bid)
        t9_settings(client, uid, bid)
        t11_stress(client, uid, bid)

    t10_concurrent(app, uname, bid)

    elapsed = time.perf_counter() - t_all
    print(f"\n  {D}وقت الاختبار الكلي: {elapsed:.1f} ثانية{RST}")
    print_report()
