"""
_report_activities.py — تقرير تفصيلي لجميع الأنشطة الرسمية (190 نشاط)

يعرض لكل نشاط:
  ► العائلة والقسم
  ► الخدمات المشتركة (مشتركة لكل الأنشطة)
  ► الخدمات المتخصصة (خاصة بكل عائلة)
  ► المنتجات والتصنيفات الأولية
  ► إعدادات التشغيل (كميات، وحدات، نمط تجاري)
  ► نتيجة الاختبار الفعلي على قاعدة البيانات
"""
import sys, os, time, sqlite3, random, string, traceback
import pathlib

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from modules.industry_seeds import (
    _SEEDS, _GROUP_MAP,
    _detect_activity_family,
    _activity_profile_settings,
    _activity_service_templates,
    _shared_service_templates,
    _prepare_seed_for_activity,
    _get_seed,
    seed_industry_defaults,
)
from modules.config import INDUSTRY_TYPES

# ── ألوان ─────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"
C = "\033[96m"; B = "\033[94m"; M = "\033[95m"
BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"

# ── تسميات الأقسام ────────────────────────────────────────────────────
SECTION_LABELS = {
    "general":           f"{M}● عام / خدمات / مطاعم{RESET}",
    "retail_food":       f"{G}● تجزئة — مواد غذائية{RESET}",
    "retail_fashion":    f"{B}● تجزئة — أزياء وموضة{RESET}",
    "retail_general":    f"{C}● تجزئة — عام{RESET}",
    "wholesale_general": f"{Y}● جملة — عام{RESET}",
    "wholesale_food":    f"{Y}● جملة — مواد غذائية{RESET}",
    "wholesale_fashion": f"{Y}● جملة — أزياء{RESET}",
}

FAMILY_ARABIC = {
    "general":           "عام / خدمات / مطاعم",
    "retail_food":       "تجزئة — مواد غذائية",
    "retail_fashion":    "تجزئة — أزياء وموضة",
    "retail_general":    "تجزئة — عام",
    "wholesale_general": "جملة — عام",
    "wholesale_food":    "جملة — مواد غذائية",
    "wholesale_fashion": "جملة — أزياء",
}

# ── اختبار قاعدة البيانات ─────────────────────────────────────────────
DB_PATH = ROOT / "database" / "accounting_dev.db"
_db_results: dict[str, dict] = {}

def run_db_test(industry_type: str) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    biz_id = None
    result = {"ok": False, "categories": 0, "products": 0, "services_in_db": [], "settings_keys": [], "error": ""}
    try:
        uid = "".join(random.choices(string.ascii_lowercase, k=5))
        biz_id = conn.execute(
            "INSERT INTO businesses (name, industry_type, country_code, city, currency, country, is_active) VALUES (?,?,?,?,?,?,?)",
            (f"RTEST_{uid}", industry_type, "SA", "الرياض", "SAR", "SA", 1)
        ).lastrowid
        conn.commit()

        summary = seed_industry_defaults(conn, biz_id, industry_type)

        # خدمات في قاعدة البيانات
        svcs = conn.execute(
            "SELECT name, sale_price FROM products WHERE business_id=? AND product_type='service' ORDER BY name",
            (biz_id,)
        ).fetchall()
        result["services_in_db"] = [(r["name"], r["sale_price"]) for r in svcs]

        # تصنيفات في قاعدة البيانات
        cats = conn.execute(
            "SELECT COUNT(*) as c FROM product_categories WHERE business_id=?", (biz_id,)
        ).fetchone()["c"]

        # منتجات في قاعدة البيانات
        prods = conn.execute(
            "SELECT COUNT(*) as c FROM products WHERE business_id=? AND product_type='product'", (biz_id,)
        ).fetchone()["c"]

        # إعدادات
        skeys = [r["key"] for r in conn.execute(
            "SELECT key FROM settings WHERE business_id=? ORDER BY key", (biz_id,)
        ).fetchall()]

        result.update({
            "ok": True,
            "categories": cats,
            "products": prods,
            "settings_keys": skeys,
        })
    except Exception as e:
        result["error"] = str(e)
    finally:
        if biz_id:
            for t in ["product_inventory","products","product_categories","settings"]:
                try: conn.execute(f"DELETE FROM {t} WHERE business_id=?", (biz_id,))
                except: pass
            try: conn.execute("DELETE FROM businesses WHERE id=?", (biz_id,))
            except: pass
            conn.commit()
        conn.close()
    return result


# ── التقرير التفصيلي لنشاط واحد ─────────────────────────────────────
def report_activity(itype: str, seq: int, total: int, is_alias: bool = False):
    family  = _detect_activity_family(itype)
    profile = _activity_profile_settings(itype)
    services_tpl = _activity_service_templates(itype)
    seed    = _get_seed(itype)
    prepared = _prepare_seed_for_activity(seed, itype)

    shared_svcs  = [s for s in services_tpl if s["name"] in {"خدمة توصيل","خدمة دعم فني"}]
    special_svcs = [s for s in services_tpl if s["name"] not in {"خدمة توصيل","خدمة دعم فني"}]

    # منتجات من البذرة (غير الخدمات)
    seed_products = [p for p in prepared.get("products",[]) if p.get("product_type","product")=="product"]
    seed_services = [p for p in prepared.get("products",[]) if p.get("product_type","product")!="product"]
    categories    = prepared.get("categories",[])

    if is_alias:
        alias_str = f"{DIM}(اختصار ← {_GROUP_MAP.get(itype,'')}){RESET}"
    elif itype not in _SEEDS:
        alias_str = f"{DIM}(fallback بذور حسب prefix/افتراضي){RESET}"
    else:
        alias_str = ""

    # اختبار DB
    db_res = run_db_test(itype)
    db_icon = f"{G}✓{RESET}" if db_res["ok"] else f"{R}✗{RESET}"

    print(f"\n{'─'*72}")
    print(f"  {db_icon} [{seq:3d}/{total}] {BOLD}{itype}{RESET} {alias_str}")
    print(f"       العائلة    : {FAMILY_ARABIC.get(family, family)}")

    # إعدادات التشغيل
    print(f"       نمط التجارة: {BOLD}{profile.get('trade_mode', profile.get('activity_profile','?'))}{RESET}"
          f"  |  الكميات: {profile.get('quantity_step','?')} "
          f"(decimals={profile.get('quantity_decimals','?')})"
          f"  |  كسري={'نعم' if profile.get('allow_fractional_qty')=='1' else 'لا'}"
          f"  |  مصفوفة أحجام={'نعم' if profile.get('size_matrix_enabled')=='1' else 'لا'}")
    print(f"       وحدات مثال : {profile.get('unit_examples','—')}")

    # التصنيفات
    if categories:
        cats_str = " | ".join(categories[:6])
        more = f" +{len(categories)-6}" if len(categories)>6 else ""
        print(f"       التصنيفات : {G}{cats_str}{more}{RESET}")

    # منتجات البذرة
    if seed_products:
        pnames = [f"{p['name']} ({p['price']} ر.س)" for p in seed_products[:5]]
        more_p = f" +{len(seed_products)-5}" if len(seed_products)>5 else ""
        print(f"       منتجات    : {C}{' | '.join(pnames)}{more_p}{RESET}")

    # الخدمات المشتركة
    s_shared = [f"{s['name']} ({s['price']} ر.س/{s['unit']})" for s in shared_svcs]
    print(f"       ✦ خدمات مشتركة  : {G}{' | '.join(s_shared) if s_shared else 'لا يوجد'}{RESET}")

    # الخدمات المتخصصة
    if special_svcs:
        s_spec = [f"{s['name']} ({s['price']} ر.س/{s['unit']})" for s in special_svcs]
        print(f"       ✦ خدمات متخصصة  : {M}{' | '.join(s_spec)}{RESET}")
    else:
        print(f"       ✦ خدمات متخصصة  : {DIM}لا توجد (يستخدم الخدمات المشتركة فقط){RESET}")

    # نتيجة DB
    if db_res["ok"]:
        svc_in_db = [f"{n}({p}ر.س)" for n,p in db_res["services_in_db"]]
        print(f"       ✦ DB: {G}{db_res['categories']} تصنيف{RESET} | "
              f"{G}{db_res['products']} منتج{RESET} | "
              f"{G}{len(db_res['services_in_db'])} خدمة{RESET} → {', '.join(svc_in_db[:4])}")
        sk = [k for k in db_res["settings_keys"] if k in {
            "activity_profile","trade_mode","quantity_step",
            "allow_fractional_qty","size_matrix_enabled"
        }]
        print(f"       ✦ إعدادات محفوظة: {G}{', '.join(sk)}{RESET}")
    else:
        print(f"       ✦ DB: {R}FAIL → {db_res['error'][:80]}{RESET}")

    return db_res["ok"]


# ═══════════════════════════════════════════════════════════════════════
# التشغيل الرئيسي
# ═══════════════════════════════════════════════════════════════════════
def main():
    t0 = time.time()

    all_types = sorted({code for code, _ in INDUSTRY_TYPES})
    total = len(all_types)
    seed_count = sum(1 for t in all_types if t in _SEEDS)
    alias_count = sum(1 for t in all_types if t in _GROUP_MAP)
    fallback_count = total - seed_count - alias_count

    print(f"\n{BOLD}{C}{'═'*72}{RESET}")
    print(f"{BOLD}{C}  تقرير شامل — جميع الأنشطة مع خدماتها ومنتجاتها — Jenan Biz{RESET}")
    print(f"{BOLD}{C}  إجمالي الأنشطة الرسمية: {total} | ببذور مباشرة: {seed_count} | اختصارات: {alias_count} | fallback: {fallback_count}{RESET}")
    print(f"{BOLD}{C}{'═'*72}{RESET}")

    # تجميع حسب العائلة
    from collections import defaultdict
    by_family: dict[str, list[tuple[str,bool]]] = defaultdict(list)
    for itype in all_types:
        fam = _detect_activity_family(itype)
        is_alias = itype in _GROUP_MAP
        by_family[fam].append((itype, is_alias))

    family_order = [
        "general","retail_food","retail_fashion","retail_general",
        "wholesale_food","wholesale_fashion","wholesale_general"
    ]

    pass_count = 0; fail_count = 0; seq = 0
    family_summary: dict[str, dict] = {}

    for fam in family_order:
        items = by_family.get(fam, [])
        if not items:
            continue

        print(f"\n\n{'═'*72}")
        print(f"  {SECTION_LABELS.get(fam, fam)}   ({len(items)} نشاط)")
        print(f"{'═'*72}")

        fam_pass = 0; fam_fail = 0

        for itype, is_alias in sorted(items):
            seq += 1
            ok = report_activity(itype, seq, total, is_alias)
            if ok: fam_pass += 1; pass_count += 1
            else:  fam_fail += 1; fail_count += 1

        family_summary[fam] = {"pass": fam_pass, "fail": fam_fail, "total": len(items)}

    elapsed = time.time() - t0

    # ── الملخص النهائي ─────────────────────────────────────────────
    print(f"\n\n{'═'*72}")
    print(f"{BOLD}  الملخص النهائي الشامل{RESET}")
    print(f"{'═'*72}")
    print(f"  {'القسم / العائلة':<38} {'الكل':>5} {'نجح':>5} {'فشل':>5}")
    print(f"  {'─'*38} {'─'*5} {'─'*5} {'─'*5}")

    for fam in family_order:
        s = family_summary.get(fam)
        if not s: continue
        color = G if s["fail"]==0 else R
        fname = FAMILY_ARABIC.get(fam, fam)
        print(f"  {color}{fname:<38}{RESET} {s['total']:>5} {G}{s['pass']:>5}{RESET} {R if s['fail'] else DIM}{s['fail']:>5}{RESET}")

    print(f"  {'─'*38} {'─'*5} {'─'*5} {'─'*5}")
    overall_color = G if fail_count==0 else R
    print(f"  {BOLD}{'الإجمالي':<38}{RESET} {total:>5} {G}{BOLD}{pass_count:>5}{RESET} {overall_color}{BOLD}{fail_count:>5}{RESET}")
    print(f"\n  الزمن الكلي: {elapsed:.1f}s")
    print(f"{'═'*72}\n")

    sys.exit(0 if fail_count==0 else 1)

if __name__ == "__main__":
    main()
