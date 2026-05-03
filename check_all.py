"""فحص شامل — يتحقق من صحة كل شيء"""
import sqlite3, sys

# ── 1. عدد الأنشطة ───────────────────────────────────────────────────
from modules.config import INDUSTRY_TYPES, get_sidebar_key
retail    = [c for c,_ in INDUSTRY_TYPES if c.startswith("retail_")]
wholesale = [c for c,_ in INDUSTRY_TYPES if c.startswith("wholesale_")]
equal = len(retail) == len(wholesale)
print(f"[1] تجزئة={len(retail)}  جملة={len(wholesale)}  متساوية={'نعم' if equal else 'لا'}")
assert equal, "عدد الأنشطة غير متساوٍ!"

# ── 2. كل نشاط له بذرة مخصصة ─────────────────────────────────────────
from modules.industry_seeds import _SEEDS, seed_industry_defaults
missing = [c for c in retail + wholesale if c not in _SEEDS]
print(f"[2] أنشطة بدون بذرة مخصصة: {len(missing)}")
assert not missing, f"ناقصة: {missing}"

# ── 3. كل بذرة فيها تصنيفات + منتجات ────────────────────────────────
bad_seeds = []
for code in retail + wholesale:
    s = _SEEDS[code]
    if not s.get("categories") or not s.get("products"):
        bad_seeds.append(code)
print(f"[3] بذور بدون تصنيفات/منتجات: {len(bad_seeds)}")
assert not bad_seeds, f"ناقصة: {bad_seeds}"

# ── 4. كل منتج فيه وحدة + سعر + تصنيف ───────────────────────────────
bad_products = []
for code, seed in _SEEDS.items():
    if not code.startswith(("retail_", "wholesale_")):
        continue
    for p in seed.get("products", []):
        if not p.get("unit") or not p.get("price") or not p.get("category"):
            bad_products.append((code, p.get("name", "?")))
print(f"[4] منتجات ناقصة بيانات: {len(bad_products)}")
assert not bad_products, f"ناقصة: {bad_products[:5]}"

# ── 5. get_sidebar_key يعمل ──────────────────────────────────────────
bad_keys = [c for c in retail + wholesale if get_sidebar_key(c) not in ("retail", "wholesale")]
print(f"[5] أنشطة بمفتاح sidebar خاطئ: {len(bad_keys)}")
assert not bad_keys, f"خاطئة: {bad_keys}"

# ── 6. seed_industry_defaults يعمل على DB حقيقية ─────────────────────
db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE product_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER, name TEXT
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER, name TEXT,
    category_id INTEGER, category_name TEXT,
    price REAL, sale_price REAL, purchase_price REAL,
    unit TEXT, product_type TEXT, is_pos INTEGER,
    track_stock INTEGER, is_active INTEGER
);
CREATE TABLE business_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER, key TEXT, value TEXT
);
CREATE TABLE warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER, is_default INTEGER
);
""")
errors = []
for code in retail + wholesale:
    try:
        seed_industry_defaults(db, 1, code)
        db.execute("DELETE FROM product_categories WHERE business_id=1")
        db.execute("DELETE FROM products WHERE business_id=1")
        db.execute("DELETE FROM business_settings WHERE business_id=1")
    except Exception as e:
        errors.append((code, str(e)))
db.close()
print(f"[6] seed_industry_defaults اختبار DB: {len(errors)} أخطاء")
assert not errors, f"أخطاء: {errors[:3]}"

# ── 7. فحص وحدات الجملة ──────────────────────────────────────────────
WHOLESALE_UNITS = {"كرتون","باليت","صندوق","كيس","رولة","دستة","ربطة","بكرة","طن","متر مكعب","لفة","حزمة"}
retail_units_in_wholesale = []
for code in wholesale:
    for p in _SEEDS[code].get("products", []):
        unit = p.get("unit","")
        if unit in ("قطعة",) and p.get("price", 0) < 100:
            retail_units_in_wholesale.append((code, p["name"], unit))
# تحذير فقط لا assertion (بعض أنشطة الجملة قد تبيع قطعاً مفردة)
if retail_units_in_wholesale:
    print(f"[7] تحذير: {len(retail_units_in_wholesale)} منتج جملة بوحدة قطعة وسعر منخفض")
else:
    print("[7] وحدات الجملة: جميعها مناسبة")

print()
print("=" * 40)
print("كل شيء مكتمل وصحيح ويعمل بكفاءة حقيقية")
print("=" * 40)
print(f"  - {len(retail)} نشاط تجزئة — كل واحد له بذرة مخصصة")
print(f"  - {len(wholesale)} نشاط جملة  — كل واحد له بذرة مخصصة")
print(f"  - {sum(len(_SEEDS[c]['products']) for c in retail+wholesale)} منتج نموذجي جاهز")
print(f"  - {sum(len(_SEEDS[c]['categories']) for c in retail+wholesale)} تصنيف جاهز")
