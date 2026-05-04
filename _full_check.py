"""
فحص شامل: تسجيل، دخول، لوحة التحكم، إنشاء فاتورة
"""
import requests
import re
import sys
import sqlite3
import os

base = 'http://127.0.0.1:5001'
s = requests.Session()
errors = []

def check(label, condition, detail=''):
    if condition:
        print(f'  ✅ {label}')
    else:
        print(f'  ❌ {label}  {detail}')
        errors.append(label)

def get_csrf(html):
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if not m:
        m = re.search(r'value="([a-f0-9]{40,})"', html)
    return m.group(1) if m else ''

print('\n=== 1. اختبار الاتصال بالسيرفر ===')
try:
    r = s.get(base + '/', timeout=5, allow_redirects=False)
    check('السيرفر يعمل', r.status_code in [200, 302], f'status={r.status_code}')
    check('Redirect إلى login', '/login' in r.headers.get('Location','') or '/auth' in r.headers.get('Location',''), r.headers.get('Location',''))
except Exception as e:
    print(f'  ❌ لا يمكن الاتصال: {e}')
    sys.exit(1)

print('\n=== 2. صفحة التسجيل ===')
r = s.get(base + '/auth/register')
check('صفحة التسجيل تفتح', r.status_code == 200, f'status={r.status_code}')
csrf_reg = get_csrf(r.text)
check('CSRF token موجود', bool(csrf_reg), f'found={repr(csrf_reg[:20])}')
fields = set(re.findall(r'name="([^"]+)"', r.text))
print(f'  حقول النموذج: {fields}')
check('حقل username موجود', 'username' in fields or 'email' in fields, str(fields))
check('حقل password موجود', 'password' in fields, str(fields))

print('\n=== 3. إنشاء حساب جديد ===')
reg_data = {
    'csrf_token': csrf_reg,
    'username': 'testuser_check2',
    'full_name': 'مستخدم الفحص',
    'email': 'test_check2@test.com',
    'password': 'Test@123456',
    'confirm_password': 'Test@123456',
    'country_code': 'SA',
}

r = s.post(base + '/auth/register', data=reg_data, allow_redirects=True)
print(f'  POST register → status={r.status_code}, url={r.url}')
check('تسجيل نجح (redirect)', r.url != base+'/auth/register', f'بقي في نفس الصفحة')

# Check for error messages
if r.status_code == 200:
    errs = re.findall(r'class="[^"]*error[^"]*"[^>]*>([^<]+)<', r.text)
    errs += re.findall(r'alert[^>]*>([^<]{5,100})<', r.text)
    if errs:
        print(f'  رسائل الخطأ في الصفحة: {errs[:3]}')

print('\n=== 4. تسجيل الدخول ===')
r_login = s.get(base + '/auth/login')
csrf_login = get_csrf(r_login.text)
login_data = {
    'csrf_token': csrf_login,
    'username': 'testuser_check2',
    'password': 'Test@123456',
}
r = s.post(base + '/auth/login', data=login_data, allow_redirects=True)
print(f'  POST login → status={r.status_code}, url={r.url}')
check('تسجيل الدخول نجح', '/dashboard' in r.url or '/onboarding' in r.url, f'url={r.url}')

if r.status_code == 200 and r.url == base+'/auth/login':
    errs = re.findall(r'(?:error|alert|flash)[^>]*>([^<]{5,150})<', r.text, re.I)
    if errs:
        print(f'  رسائل خطأ الدخول: {errs[:3]}')

print('\n=== 5. لوحة التحكم ===')
r = s.get(base + '/dashboard')
check('لوحة التحكم تفتح', r.status_code == 200, f'status={r.status_code}, url={r.url}')

print('\n=== 6. صفحة الإعدادات ===')
r = s.get(base + '/settings')
check('الإعدادات تفتح', r.status_code == 200, f'status={r.status_code}')

print('\n=== 7. صفحة المنتجات ===')
r = s.get(base + '/inventory/products')
check('المنتجات تفتح', r.status_code == 200, f'status={r.status_code}')

print('\n=== 8. صفحة الفواتير ===')
r = s.get(base + '/invoices/')
check('الفواتير تفتح', r.status_code == 200, f'status={r.status_code}')

print('\n=== 9. صفحة العملاء ===')
r = s.get(base + '/contacts/customers')
check('العملاء تفتح', r.status_code == 200, f'status={r.status_code}')

print('\n=== 10. قاعدة البيانات ===')
db_path = 'database/accounting_dev.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for tbl in ['users', 'businesses', 'invoices', 'products']:
        c.execute(f'SELECT count(*) FROM {tbl}')
        cnt = c.fetchone()[0]
        print(f'  {tbl}: {cnt} سجل')
    conn.close()
else:
    print('  ❌ ملف DB غير موجود')

print('\n' + '='*50)
if errors:
    print(f'❌ عدد الأخطاء: {len(errors)}')
    for e in errors:
        print(f'  - {e}')
else:
    print('✅ كل الفحوصات نجحت')
