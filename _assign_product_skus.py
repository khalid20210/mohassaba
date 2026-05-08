"""
_assign_product_skus.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
توليد وتعيين أرقام تسلسلية (SKU) لجميع المنتجات الموجودة في قاعدة البيانات.

صيغة SKU:  {BPREFIX}-{CAT_CODE}-{SEQ:04d}
مثال:       RES-MSH-0001  (مطعم - مشويات - أول منتج)
            CAF-QHW-0001  (كافيه - قهوة - أول منتج)
            WHL-HBB-0003  (جملة - حبوب - ثالث منتج)

الخوارزمية:
  - لكل منشأة (business):
    1. اجلب بادئة النشاط من settings (invoice_prefix أو industry_type)
    2. لكل منتج ليس لديه SKU تسلسلي:
       - اجلب اسم الفئة (category_name)
       - ولّد كود فئة من أول 3 أحرف (بدون حروف عربية → ترقيم بديل)
       - عيّن SKU فريد
       - حدّث product_inventory + products.barcode إذا كان فارغاً
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sqlite3
import re
import sys

DB_PATH = "database/accounting_dev.db"

# ────────────────────────────────────────────────────────────────────────────
# جدول تحويل الفئة العربية → كود قصير (3 أحرف إنجليزية)
# ────────────────────────────────────────────────────────────────────────────
CATEGORY_CODE_MAP: dict[str, str] = {
    # مطاعم وكافيهات
    "مشروبات":           "DRK",
    "مشويات":            "GRL",
    "وجبات رئيسية":     "MNL",
    "سلطات":             "SLD",
    "حلويات":            "DST",
    "إضافات":            "ADD",
    "قهوة":              "COF",
    "شاي":               "TEA",
    "مشروبات باردة":    "CLD",
    "مشروبات ساخنة":    "HOT",
    "وجبات خفيفة":      "SNK",
    "قهوة مختصة":       "SPE",
    "معسل":              "MAS",
    "فحم وأدوات":       "CHL",
    # غذائية
    "مواد غذائية":      "FOD",
    "ألبان وأجبان":     "DAI",
    "خضار وفواكه":      "VEG",
    "منظفات":           "CLN",
    "مجمدات":           "FRZ",
    "تموينات":          "GRN",
    "خبز":              "BRD",
    "مخبوزات":          "BAK",
    "كيك وتورتة":       "CAK",
    "لحوم حمراء":       "RED",
    "دواجن":            "POU",
    "أسماك":            "FSH",
    "مشتقات":           "DRV",
    "قهوة":             "COF",
    "بهارات":           "SPC",
    "مكسرات":           "NUT",
    "خضروات":           "VGT",
    "فواكه":            "FRT",
    "أعشاب وتوابل":    "HRB",
    "مجمدات خضار":     "VFZ",
    "تمور محلية":      "DAT",
    "تمور مستوردة":    "DAI",
    "منتجات تمر":      "DTP",
    "تغليف هدايا":     "GFT",
    "مياه معدنية":     "WAT",
    "عصائر":           "JUI",
    "مشروبات غازية":   "SOF",
    "مشروبات طاقة":    "ENR",
    # صيدلية وصحة
    "أدوية وصفة طبية": "RXD",
    "أدوية بدون وصفة": "OTC",
    "فيتامينات ومكملات":"VIT",
    "مستلزمات طبية":   "MED",
    "مستحضرات تجميل طبية":"DCO",
    "أطفال ورضع":      "INF",
    "بروتين":          "PRO",
    "طاقة وحرق":       "FAT",
    "صحة عامة":        "HLT",
    "أجهزة طبية":     "MDV",
    "أدوات قياس":      "MSR",
    "مستلزمات جرح وضماد":"DRS",
    "عناية بالبشرة":   "SKN",
    "مكياج":           "MKP",
    "عناية بالشعر":    "HAR",
    "عطور وبودي":      "PRF",
    "عطور رجالي":      "MPR",
    "عطور نسائي":      "FPR",
    "بخور وعود":       "OUD",
    "أدوات عطور":      "FRA",
    # ملابس
    "قمصان وبولو":     "SHR",
    "بناطيل وجينز":   "PNT",
    "ثوب سعودي":       "THB",
    "ملابس رياضية":    "SPT",
    "إكسسوارات":       "ACC",
    "فساتين":          "DRS",
    "عبايات":          "ABA",
    "بلايز وتيشيرت":  "BLZ",
    "بناطيل":          "PAN",
    "أحذية رجالي":    "MSH",
    "أحذية نسائي":    "FSH",
    "أحذية أطفال":    "KSH",
    "شنط وحقائب":     "BAG",
    "ساعات رجالي":    "MWT",
    "ساعات نسائي":    "FWT",
    "مجوهرات ذهب":    "GLD",
    "مجوهرات فضة":    "SLV",
    "حقائب نسائي":    "HNB",
    "حقائب رجالي":    "HMB",
    "حقائب سفر":      "TRB",
    "محافظ ومحافظ":   "WLT",
    "أقمشة قطنية":   "CTN",
    "أقمشة شيفون":   "CHF",
    "كتان وكاجوال":  "LNN",
    "أقمشة فاخرة":   "LUX",
    "خيوط وأزرار":   "THR",
    "أقمشة تبطين":   "LNG",
    "أدوات خياطة":   "TAL",
    "إكسسوارات خياطة":"TAC",
    "نظارات طبية":    "MGL",
    "نظارات شمسية":   "SGL",
    "عدسات لاصقة":   "CLC",
    "إكسسوارات نظارة":"GAC",
    # إلكترونيات
    "جوالات":          "MOB",
    "تابلت":           "TAB",
    "إكسسوارات جوال": "MAC",
    "سماعات":          "EAR",
    "ساعات ذكية":     "SMW",
    "لابتوب":          "LAP",
    "كمبيوتر مكتبي":  "DSK",
    "قطع وأجزاء":     "PRT",
    "شبكات":           "NET",
    "طابعات":          "PRN",
    "أجهزة مطبخ":     "KAP",
    "تكييف وتبريد":   "AIR",
    "غسيل وتنظيف":    "WSH",
    "شاشات وتلفزيون": "TLV",
    "كاميرات مراقبة": "CAM",
    "أنظمة إنذار":    "ALR",
    "أقفال ذكية":     "SLK",
    "خدمات تركيب":    "INS",
    # بناء وتشييد
    "إسمنت وجبس":     "CMT",
    "حديد وصلب":      "STL",
    "رمل وبحص":       "SND",
    "بلاط وسيراميك":  "CRM",
    "عزل":             "INS",
    "مواسير":          "PIP",
    "خلاطات":          "FCP",
    "مراحيض وأحواض":  "PLM",
    "أدوات السباكة":  "PLT",
    "كابلات وأسلاك":  "CBL",
    "قواطع وبواكس":   "BRK",
    "إضاءة":           "LGT",
    "أجهزة كهربائية": "ELC",
    "دهان داخلي":     "PNI",
    "دهان خارجي":     "PNO",
    "طلاء معادن":     "MPT",
    "ملحقات":          "ACC",
    "عدد يدوية":      "HND",
    "معدات كهربائية": "EQP",
    "مسامير وبراغي":  "SCR",
    "لوازم":           "SUP",
    "سيراميك":         "CER",
    "بورسلان":         "POR",
    "رخام":            "MRB",
    "باركيه":          "PRQ",
    "موزاييك":         "MZK",
    "إسمنت وبناء":    "CMB",
    "بلاط وسيراميك":  "TLE",
    "عزل ومواد":      "ISO",
    # سيارات
    "فلاتر":           "FLT",
    "زيوت وسوائل":    "OIL",
    "فرامل":           "BRK",
    "إضاءة":           "LGT",
    "إلكترونيات سيارة":"CAE",
    "إطارات":          "TYR",
    "بطاريات":         "BAT",
    "كهربائيات سيارات":"CEL",
    "كاميرات وشاشات": "CSC",
    "صوتيات":          "AUD",
    "تزيين خارجي":    "EXT",
    "تزيين داخلي":    "INT",
    "معدات رافعة":    "LFT",
    "أدوات تشخيص":    "DGN",
    "كمبروسر وهواء":  "AIR",
    "معدات دهان":     "PEQ",
    # أثاث ومنزليات
    "غرف نوم":        "BDR",
    "غرف معيشة":     "LVR",
    "مطابخ":          "KIT",
    "مكاتب":          "OFC",
    "ديكور":          "DCR",
    "أواني طبخ":     "CKW",
    "أجهزة مطبخ صغيرة":"SMA",
    "أدوات مائدة":   "TBL",
    "تخزين":          "STR",
    "قرطاسية مكتب":  "STN",
    "قرطاسية مدرسة": "SCH",
    "كتب ومراجع":    "BOK",
    "طباعة وتصوير":  "PRN",
    "سجاد إيراني":   "ICR",
    "سجاد تركي":     "TCR",
    "موكيت":          "CPT",
    "سجاد ممرات":    "RNR",
    # خدمية
    "خدمات هندسية":  "ENG",
    "مواد مشروع":    "PRJ",
    "معدات":          "EQP",
    "سيارات اقتصادية":"ECO",
    "سيارات فاخرة":  "LUX",
    "سيارات SUV":    "SUV",
    "كشوفات طبية":   "VIS",
    "إجراءات وعمليات":"PRO",
    "أدوية صرف":     "DSP",
    "خدمات صيانة":   "MNT",
    "خدمات تقنية":   "TEC",
    "استشارات":       "CNS",
    "خدمات عامة":    "GEN",
    "خدمات مشتركة":  "SHR",
    "خدمات المتجر":  "STO",
    "خدمات الجملة":  "WHL",
    # جملة
    "حبوب وتموينات": "GRN",
    "مشروبات":        "DRK",
    "زيوت وسمن":     "OIL",
    "معلبات":         "CAN",
    "منظفات جملة":   "WCL",
    "مواد غذائية جملة":"WFD",
    "مشروبات جملة":  "WDR",
    "تموينات جملة":  "WGR",
    "بقوليات":        "LGM",
    "بهارات جملة":   "WSP",
    "أجهزة إلكترونية":"ELC",
    "أسلاك وتوصيل":  "CBL",
    "بطاريات وشحن":  "BAT",
    "ملابس رجالي جملة":"WMC",
    "ملابس نسائي جملة":"WWC",
    "ملابس أطفال جملة":"WKC",
    "إكسسوارات جملة":"WAC",
    # متخصصة
    "معسل":            "MAS",
    "سجائر":          "CIG",
    "زهور طازجة":    "FLW",
    "زهور صناعية":   "AFL",
    "هدايا مغلفة":   "GFT",
    "ديكور زهور":    "FDC",
    "ألعاب أطفال":   "TOY",
    "ألعاب تعليمية": "EDU",
    "مجسمات وعرائس": "DLL",
    "طعام حيوانات":  "PFD",
    "لوازم عناية":   "PCT",
    "طبية بيطرية":   "VET",
    "ملابس رياضية":  "SPW",
    "معدات جيم":     "GYM",
    "رياضة مائية":   "WTR",
    "تخييم":          "CMP",
}


def _cat_to_code(cat_name: str, used_codes: set[str]) -> str:
    """تحويل اسم الفئة إلى كود 3 أحرف فريد."""
    # أولاً: من الجدول المحدد
    mapped = CATEGORY_CODE_MAP.get(cat_name)
    if mapped and mapped not in used_codes:
        return mapped

    # ثانياً: من أول 3 أحرف إنجليزية/أرقام
    ascii_only = re.sub(r'[^A-Za-z0-9]', '', cat_name)
    code = ascii_only[:3].upper() if ascii_only else "CAT"

    # ضمان التفرد
    base = code or "CAT"
    suffix = 0
    candidate = base
    while candidate in used_codes:
        suffix += 1
        candidate = base[:2] + str(suffix)
    return candidate


def generate_skus_for_business(db: sqlite3.Connection, biz_id: int, biz_name: str) -> dict:
    """يولّد SKU لجميع منتجات منشأة واحدة."""
    # البادئة من settings — أو من industry_type كبديل
    prefix_row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix' LIMIT 1",
        (biz_id,)
    ).fetchone()

    if prefix_row and prefix_row["value"] and prefix_row["value"].strip() != "PRD":
        prefix = prefix_row["value"].upper().strip()
    else:
        # استخراج بادئة من industry_type
        itype_row = db.execute(
            "SELECT industry_type FROM businesses WHERE id=? LIMIT 1", (biz_id,)
        ).fetchone()
        itype = (itype_row["industry_type"] if itype_row else "") or ""
        # خريطة industry_type → بادئة
        ITYPE_PREFIX = {
            "food_restaurant": "RES", "food_cafe": "CAF", "food_coffeeshop": "COF",
            "food_hookah": "HKH",
            "retail_fnb_supermarket": "SPM", "retail_fnb_grocery": "GRO",
            "retail_fnb_bakery": "BKR", "retail_fnb_butcher": "BUT",
            "retail_fnb_roaster": "RST", "retail_fnb_produce": "PRD",
            "retail_fnb_dates": "DAT", "retail_fnb_beverages": "BEV",
            "retail_health_pharmacy": "PHR", "retail_health_perfume": "PRF",
            "retail_health_cosmetics": "COS", "retail_health_supplements": "SUP",
            "retail_health_medical": "MDL",
            "retail_fashion_clothing_m": "MFA", "retail_fashion_clothing_f": "FFA",
            "retail_fashion_clothing_k": "KFA", "retail_fashion_shoes": "SHO",
            "retail_fashion_watches": "WTC", "retail_fashion_bags": "BAG",
            "retail_fashion_fabric": "FAB", "retail_fashion_tailoring": "TAI",
            "retail_fashion_optics": "OPT",
            "retail_electronics_mobile": "MOB", "retail_electronics_computers": "CMP",
            "retail_electronics_appliances": "APP", "retail_electronics_security": "SEC",
            "retail_auto_parts": "AUT", "retail_auto_tires": "TIR",
            "retail_auto_accessories": "ACC", "retail_auto_workshop": "WRK",
            "retail_construction_materials": "CON", "retail_construction_plumbing": "PLM",
            "retail_construction_electrical": "ELC", "retail_construction_paints": "PNT",
            "retail_construction_hardware": "HRW", "retail_construction_flooring": "FLR",
            "retail_home_furniture": "FRN", "retail_home_kitchenware": "KTC",
            "retail_home_stationery": "STN", "retail_home_carpet": "CRP",
            "retail_home_office": "OFS",
            "retail_specialized_tobacco": "TOB", "retail_specialized_flowers": "FLW",
            "retail_specialized_toys": "TOY", "retail_specialized_pets": "PET",
            "retail_specialized_sports": "SPT",
            "wholesale_fnb_distribution": "WHL", "wholesale_fnb_general": "WFG",
            "wholesale_electronics_general": "WEL", "wholesale_auto_parts": "WAP",
            "wholesale_fashion_general": "WFA", "wholesale_construction_materials": "WCM",
            "construction": "BLD", "car_rental": "RNT", "medical": "MED",
            "services": "SRV",
        }
        prefix = ITYPE_PREFIX.get(itype, "GEN")

    # جلب المنتجات
    products = db.execute(
        """SELECT p.id, p.name, p.barcode,
                  COALESCE(p.category_name, '') as cat_name,
                  pi.sku as inv_sku
           FROM products p
           LEFT JOIN product_inventory pi ON pi.product_id = p.id AND pi.business_id = p.business_id
           WHERE p.business_id = ?
           ORDER BY p.id""",
        (biz_id,)
    ).fetchall()

    # فرز SKU الموجودة
    existing_skus = {p["inv_sku"] for p in products if p["inv_sku"]}

    # آخر رقم مستخدم لهذه البادئة
    max_seq = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-[A-Z]{{3}}-(\d+)$|^{re.escape(prefix)}-(\d+)$")
    for sku in existing_skus:
        m = pattern.match(sku)
        if m:
            n = int(m.group(1) or m.group(2) or 0)
            max_seq = max(max_seq, n)

    used_cat_codes: dict[str, str] = {}
    used_codes: set[str] = set()
    updated = 0
    skipped = 0
    seq = max_seq + 1

    for p in products:
        inv_sku = p["inv_sku"] or ""

        # تخطّى المنتجات ذات SKU تسلسلي موجود بالفعل لهذه البادئة
        if inv_sku and re.match(rf"^{re.escape(prefix)}-", inv_sku):
            skipped += 1
            continue

        cat_name = p["cat_name"] or "عام"
        if cat_name not in used_cat_codes:
            code = _cat_to_code(cat_name, used_codes)
            used_cat_codes[cat_name] = code
            used_codes.add(code)
        cat_code = used_cat_codes[cat_name]

        sku_val = f"{prefix}-{cat_code}-{seq:04d}"
        seq += 1

        exists_inv = db.execute(
            "SELECT id FROM product_inventory WHERE product_id=? AND business_id=?",
            (p["id"], biz_id)
        ).fetchone()

        if exists_inv:
            db.execute(
                "UPDATE product_inventory SET sku=? WHERE product_id=? AND business_id=?",
                (sku_val, p["id"], biz_id)
            )
        else:
            db.execute(
                """INSERT OR IGNORE INTO product_inventory
                   (business_id, product_id, sku, barcode, current_qty, min_qty, max_qty,
                    unit_cost, unit_price, created_at, updated_at)
                   VALUES (?,?,?,?,0,0,9999,0,0,datetime('now'),datetime('now'))""",
                (biz_id, p["id"], sku_val, p["barcode"] or "")
            )

        updated += 1

    db.commit()
    print(f"  ✅ {biz_name[:28]:28s} | {prefix:5s} | محدَّث: {updated:4d} | موجود: {skipped:4d}")
    return {"prefix": prefix, "updated": updated, "skipped": skipped}


def main():
    print("=" * 60)
    print("  توليد أرقام تسلسلية (SKU) للمنتجات")
    print("=" * 60)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=OFF")

    businesses = db.execute(
        "SELECT id, name FROM businesses ORDER BY id"
    ).fetchall()

    if not businesses:
        print("❌ لا توجد منشآت في قاعدة البيانات")
        db.close()
        return

    total_updated = 0
    total_skipped = 0

    for biz in businesses:
        result = generate_skus_for_business(db, biz["id"], biz["name"])
        total_updated += result["updated"]
        total_skipped += result["skipped"]

    print("-" * 60)
    print(f"  إجمالي المحدَّث : {total_updated}")
    print(f"  موجود مسبقاً  : {total_skipped}")
    print("=" * 60)

    # عرض عينة
    print("\n  عينة من SKU المولّدة:")
    sample = db.execute(
        """SELECT p.name, pi.sku, p.category_name, b.name as biz_name
           FROM product_inventory pi
           JOIN products p ON p.id = pi.product_id
           JOIN businesses b ON b.id = p.business_id
           WHERE pi.sku LIKE '%-%-%'
           LIMIT 20"""
    ).fetchall()
    for row in sample:
        cat = row[2] or "—"
        print(f"    {row[1]:22s}  {row[0][:30]:30s}  [{cat}]")

    db.close()
    print("\n✅ اكتمل التوليد!")


if __name__ == "__main__":
    main()
