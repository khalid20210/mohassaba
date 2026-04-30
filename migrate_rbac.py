"""تهجير قاعدة البيانات: إضافة RBAC كامل"""
import sqlite3, json

db = sqlite3.connect('database/accounting.db')
db.row_factory = sqlite3.Row

# 1. إضافة branch_id لجدول users
try:
    db.execute('ALTER TABLE users ADD COLUMN branch_id INTEGER REFERENCES warehouses(id)')
    print('✓ added branch_id to users')
except Exception as e:
    print(f'  branch_id: {e}')

# 2. إضافة level لجدول users (owner | manager | cashier)
try:
    db.execute("ALTER TABLE users ADD COLUMN level TEXT NOT NULL DEFAULT 'manager'")
    print('✓ added level to users')
except Exception as e:
    print(f'  level: {e}')

# 3. تحديث صلاحيات الأدوار الموجودة
ROLE_PERMS = {
    'مدير':       {'all': True},
    'مدير فرع':  {'sales':True,'pos':True,'reports':True,'accounting':True,
                   'purchases':True,'warehouse':True,'analytics':True,
                   'contacts':True,'settings':False},
    'كاشير':     {'pos':True,'sales':True},
    'محاسب':     {'accounting':True,'reports':True,'sales':True,
                   'purchases':True,'analytics':True,'contacts':True},
    'أمين مخزن': {'warehouse':True,'purchases':True,'inventory':True},
}
for name, perms in ROLE_PERMS.items():
    db.execute('UPDATE roles SET permissions=? WHERE name=?',
               (json.dumps(perms, ensure_ascii=False), name))
    print(f'✓ updated role: {name}')

# 4. تحديث level للمستخدمين الحاليين بناءً على اسم الدور
db.execute("""
    UPDATE users SET level = (
        SELECT CASE r.name
            WHEN 'مدير'     THEN 'owner'
            WHEN 'مدير فرع' THEN 'manager'
            WHEN 'كاشير'    THEN 'cashier'
            ELSE 'manager'
        END
        FROM roles r WHERE r.id = users.role_id
    )
""")
print('✓ updated user levels')

# 5. إنشاء الأدوار الافتراضية لكل منشأة لا تملكها بعد
businesses = db.execute('SELECT id FROM businesses').fetchall()
for biz in businesses:
    biz_id = biz['id']
    existing = [r['name'] for r in db.execute(
        'SELECT name FROM roles WHERE business_id=?', (biz_id,)).fetchall()]
    defaults = [
        ('مدير',       json.dumps({'all': True}, ensure_ascii=False),          'owner'),
        ('مدير فرع',  json.dumps({'sales':True,'pos':True,'reports':True,
                                   'accounting':True,'purchases':True,
                                   'warehouse':True,'analytics':True,
                                   'contacts':True,'settings':False},
                                   ensure_ascii=False),                         'manager'),
        ('كاشير',     json.dumps({'pos':True,'sales':True},
                                   ensure_ascii=False),                         'cashier'),
        ('محاسب',     json.dumps({'accounting':True,'reports':True,'sales':True,
                                   'purchases':True,'analytics':True,
                                   'contacts':True}, ensure_ascii=False),       'manager'),
        ('أمين مخزن', json.dumps({'warehouse':True,'purchases':True,
                                   'inventory':True}, ensure_ascii=False),      'manager'),
    ]
    for name, perms, _lvl in defaults:
        if name not in existing:
            db.execute(
                'INSERT INTO roles (business_id, name, permissions, is_system) VALUES (?,?,?,1)',
                (biz_id, name, perms)
            )
            print(f'  + role "{name}" for business {biz_id}')

db.commit()
db.close()
print('\nمهاجرة RBAC اكتملت بنجاح ✓')
