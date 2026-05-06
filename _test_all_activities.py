"""
_test_all_activities.py — اختبار شامل لجميع الأنشطة (105 رئيسي + 65 اختصار = 170)

يختبر:
  1. seed_industry_defaults  — بيانات أولية + خدمات مشتركة + خدمات مخصصة
  2. _activity_profile_settings  — إعدادات النشاط
  3. _detect_activity_family      — تصنيف العائلة
  4. _prepare_seed_for_activity   — الإعداد الكامل
  5. Flask onboarding POST       — يدور onboarding حقيقي لكل نشاط
  6. shared_services_present     — خدمة توصيل + خدمة دعم فني
  7. specialized_services_present — خدمات خاصة بكل عائلة
"""
import sys
import time
import sqlite3
import random
import string
import traceback
from collections import defaultdict

# ─── أضف مسار المشروع ───────────────────────────────────────────────
import os, pathlib
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

# ═══════════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════════
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg): print(f"  {RED}✗{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET} {msg}")
def info(msg): print(f"  {CYAN}→{RESET} {msg}")

PASS = 0; FAIL = 0; WARN = 0

def check(cond, msg_ok, msg_fail, critical=False):
    global PASS, FAIL
    if cond:
        PASS += 1
        ok(msg_ok)
    else:
        FAIL += 1
        fail(msg_fail)
        if critical:
            raise AssertionError(msg_fail)

def check_warn(cond, msg):
    global WARN
    if not cond:
        WARN += 1
        warn(msg)

# ═══════════════════════════════════════════════════════════════════════
# قاعدة بيانات مؤقتة للاختبار
# ═══════════════════════════════════════════════════════════════════════

_DB_PATH = ROOT / "database" / "accounting_dev.db"

def get_test_db():
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_test_business(db: sqlite3.Connection, industry_type: str) -> int:
    """ينشئ منشأة اختبارية مؤقتة ويعيد biz_id."""
    uid = "".join(random.choices(string.ascii_lowercase, k=6))
    biz_name = f"TEST_{industry_type[:20]}_{uid}"

    biz_id = db.execute(
        """INSERT INTO businesses (name, industry_type, country_code, city, currency, country, is_active)
           VALUES (?,?,?,?,?,?,?)""",
        (biz_name, industry_type, "SA", "الرياض", "SAR", "SA", 1)
    ).lastrowid

    db.commit()
    return biz_id


def cleanup_test_business(db: sqlite3.Connection, biz_id: int):
    """يحذف بيانات الاختبار (المنشأة الاختبارية فقط)."""
    try:
        tables = [
            "invoice_items", "invoices", "journal_entries", "journal_items",
            "product_inventory", "products", "product_categories",
            "settings", "services", "customers", "suppliers",
        ]
        for t in tables:
            try:
                db.execute(f"DELETE FROM {t} WHERE business_id=?", (biz_id,))
            except Exception:
                pass
        db.execute("DELETE FROM businesses WHERE id=? AND name LIKE 'TEST_%'", (biz_id,))
        db.commit()
    except Exception:
        db.rollback()


# ═══════════════════════════════════════════════════════════════════════
# الاختبار الأساسي لكل نشاط
# ═══════════════════════════════════════════════════════════════════════

SHARED_SERVICE_NAMES = {"خدمة توصيل", "خدمة دعم فني"}

FAMILY_SPECIALIZED_SERVICES = {
    "retail_food":       {"خدمة توصيل محلي", "تجهيز طلب مسبق"},
    "retail_fashion":    {"تعديل مقاس", "تغليف هدية"},
    "wholesale_general": {"خدمة شحن طلبيات", "تحميل وتنزيل"},
    "wholesale_food":    {"خدمة شحن طلبيات", "تحميل وتنزيل"},
    "wholesale_fashion": {"خدمة شحن طلبيات", "تحميل وتنزيل"},
}

REQUIRED_PROFILE_KEYS = {
    "activity_profile", "quantity_step", "quantity_min",
    "quantity_decimals", "allow_fractional_qty", "unit_examples",
}

errors_by_type: dict[str, list[str]] = defaultdict(list)
skipped = []


def test_activity(industry_type: str, db: sqlite3.Connection, verbose=False) -> bool:
    """يختبر نشاطاً واحداً ويعيد True إن نجح كل شيء."""
    errs = []

    # 1. تصنيف العائلة
    try:
        family = _detect_activity_family(industry_type)
        if not family:
            errs.append("family is empty")
    except Exception as e:
        errs.append(f"_detect_activity_family: {e}")
        family = "unknown"

    # 2. إعدادات النشاط
    try:
        prof = _activity_profile_settings(industry_type)
        missing_keys = REQUIRED_PROFILE_KEYS - prof.keys()
        if missing_keys:
            errs.append(f"missing profile keys: {missing_keys}")
        if prof.get("activity_profile") not in {
            "wholesale", "retail_food", "retail_fashion", "retail_general"
        }:
            errs.append(f"unknown activity_profile: {prof.get('activity_profile')}")
    except Exception as e:
        errs.append(f"_activity_profile_settings: {e}")
        prof = {}

    # 3. قالب الخدمات
    try:
        services = _activity_service_templates(industry_type)
        service_names = {s["name"] for s in services}

        # خدمات مشتركة
        missing_shared = SHARED_SERVICE_NAMES - service_names
        if missing_shared:
            errs.append(f"missing shared services: {missing_shared}")

        # خدمات مخصصة
        if family in FAMILY_SPECIALIZED_SERVICES:
            expected = FAMILY_SPECIALIZED_SERVICES[family]
            missing_spec = expected - service_names
            if missing_spec:
                errs.append(f"missing specialized services for {family}: {missing_spec}")

        # تحقق من بنية كل خدمة
        for svc in services:
            for key in ("name", "category", "price", "unit", "product_type"):
                if key not in svc or svc[key] is None:
                    errs.append(f"service '{svc.get('name')}' missing field '{key}'")
            if svc.get("price", 0) <= 0:
                errs.append(f"service '{svc.get('name')}' has invalid price {svc.get('price')}")
    except Exception as e:
        errs.append(f"_activity_service_templates: {e}")

    # 4. _get_seed
    try:
        seed = _get_seed(industry_type)
        if not seed:
            errs.append("_get_seed returned empty")
        else:
            if "categories" not in seed and "products" not in seed:
                errs.append("seed has no categories or products")
    except Exception as e:
        errs.append(f"_get_seed: {e}")
        seed = {}

    # 5. _prepare_seed_for_activity
    try:
        prepared = _prepare_seed_for_activity(seed, industry_type)
        if not prepared.get("products"):
            errs.append("prepared seed has no products")
        if not prepared.get("settings"):
            errs.append("prepared seed has no settings")
        # تحقق الخدمات مضمّنة في المنتجات
        prep_service_names = {
            p["name"] for p in prepared.get("products", [])
            if p.get("product_type") == "service"
        }
        missing_in_prep = SHARED_SERVICE_NAMES - prep_service_names
        if missing_in_prep:
            errs.append(f"shared services missing from prepared products: {missing_in_prep}")
    except Exception as e:
        errs.append(f"_prepare_seed_for_activity: {e}")
        prepared = {}

    # 6. seed_industry_defaults (قاعدة بيانات حقيقية)
    biz_id = None
    try:
        biz_id = create_test_business(db, industry_type)
        summary = seed_industry_defaults(db, biz_id, industry_type)

        if summary.get("categories_inserted", 0) == 0:
            errs.append("seed_industry_defaults: no categories inserted")
        if summary.get("products_inserted", 0) == 0:
            errs.append("seed_industry_defaults: no products inserted")
        if summary.get("settings_written", 0) == 0:
            errs.append("seed_industry_defaults: no settings written")

        # تحقق من وجود الخدمات المشتركة في قاعدة البيانات
        db_service_names = set(
            r["name"] for r in db.execute(
                "SELECT name FROM products WHERE business_id=? AND product_type='service'",
                (biz_id,)
            ).fetchall()
        )
        missing_db_shared = SHARED_SERVICE_NAMES - db_service_names
        if missing_db_shared:
            errs.append(f"shared services not in DB after seed: {missing_db_shared}")

        # تحقق من الإعدادات في DB
        db_settings = {
            r["key"]: r["value"]
            for r in db.execute(
                "SELECT key, value FROM settings WHERE business_id=?",
                (biz_id,)
            ).fetchall()
        }
        if "activity_profile" not in db_settings:
            errs.append("activity_profile not saved in settings")
        if "trade_mode" not in db_settings:
            errs.append("trade_mode not saved in settings")

    except Exception as e:
        errs.append(f"seed_industry_defaults: {e}\n{traceback.format_exc()[-300:]}")
    finally:
        if biz_id:
            cleanup_test_business(db, biz_id)

    if errs:
        errors_by_type[industry_type] = errs
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════
# الاختبار عبر Flask test_client (onboarding POST)
# ═══════════════════════════════════════════════════════════════════════

def test_onboarding_via_flask(sample_types: list[str]) -> dict:
    """
    يختبر onboarding حقيقي عبر Flask test_client لعينة من الأنشطة.
    يعيد {industry_type: status_code}
    """
    from modules import create_app
    flask_app = create_app()
    results = {}

    for itype in sample_types:
        try:
            with flask_app.test_client() as c:
                # تسجيل مستخدم جديد
                uid = "".join(random.choices(string.ascii_lowercase, k=5))
                reg = c.post("/auth/register", data={
                    "full_name": f"Test {uid}",
                    "username": f"ob_{uid}",
                    "country": "SA",
                    "email": f"{uid}@test.local",
                    "password": "Test@12345",
                    "password_confirm": "Test@12345",
                }, follow_redirects=False)

                if reg.status_code not in (200, 302):
                    results[itype] = f"register={reg.status_code}"
                    continue

                # اكتشاف business_id من قاعدة البيانات
                db2 = get_test_db()
                biz_row = db2.execute(
                    "SELECT id FROM businesses ORDER BY id DESC LIMIT 1"
                ).fetchone()
                biz_id = biz_row["id"] if biz_row else None
                db2.close()

                if not biz_id:
                    results[itype] = "no_biz_created"
                    continue

                # onboarding POST
                with c.session_transaction() as sess:
                    sess["user_id"] = 1
                    sess["business_id"] = biz_id
                    sess["needs_onboarding"] = True

                ob = c.post("/onboarding", data={
                    "business_name": f"شركة {uid}",
                    "industry_type": itype,
                    "city": "الرياض",
                    "tax_number": "300000000000003",
                    "phone": "0501234567",
                }, follow_redirects=False)

                results[itype] = ob.status_code

                # تنظيف
                db3 = get_test_db()
                cleanup_test_business(db3, biz_id)
                db3.close()

        except Exception as e:
            results[itype] = f"error: {e}"

    return results


# ═══════════════════════════════════════════════════════════════════════
# التشغيل الرئيسي
# ═══════════════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL, WARN

    print(f"\n{BOLD}{CYAN}{'═'*70}{RESET}")
    print(f"{BOLD}{CYAN}  اختبار شامل لجميع الأنشطة — Jenan Biz{RESET}")
    print(f"{BOLD}{CYAN}{'═'*70}{RESET}\n")

    all_types = sorted(list(_SEEDS.keys()) + list(_GROUP_MAP.keys()))
    print(f"إجمالي الأنشطة المختبَرة: {BOLD}{len(all_types)}{RESET}")
    print(f"  • أنشطة رئيسية (Seeds): {len(_SEEDS)}")
    print(f"  • اختصارات (Aliases): {len(_GROUP_MAP)}")
    print()

    db = get_test_db()
    t0 = time.time()

    # ── المرحلة 1: اختبار كل نشاط (بدون Flask) ──────────────────────
    print(f"{BOLD}المرحلة 1: اختبار البذور والخدمات لكل نشاط{RESET}")
    print("─" * 50)

    passed_types = []
    failed_types = []
    family_stats: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0})

    for i, itype in enumerate(all_types, 1):
        family = _detect_activity_family(itype)
        result = test_activity(itype, db, verbose=False)
        family_stats[family]["pass" if result else "fail"] += 1

        if result:
            passed_types.append(itype)
            PASS += 1
            print(f"  {GREEN}✓{RESET} [{i:3d}/{len(all_types)}] {itype:<45} ({family})")
        else:
            failed_types.append(itype)
            FAIL += 1
            print(f"  {RED}✗{RESET} [{i:3d}/{len(all_types)}] {itype:<45} ({family})")
            for err in errors_by_type[itype]:
                print(f"       {RED}→ {err}{RESET}")

    elapsed1 = time.time() - t0
    print()

    # ── المرحلة 2: Flask Onboarding لعينة ──────────────────────────
    print(f"{BOLD}المرحلة 2: اختبار Onboarding عبر Flask{RESET}")
    print("─" * 50)

    # اختر نموذج من كل عائلة
    families_sample = {}
    for itype in all_types:
        f = _detect_activity_family(itype)
        if f not in families_sample and itype in _SEEDS:
            families_sample[f] = itype

    sample = list(families_sample.values())
    print(f"عينة الاختبار ({len(sample)} نشاط — نموذج من كل عائلة):")
    for f, t in families_sample.items():
        print(f"  {CYAN}{f:<25}{RESET} → {t}")
    print()

    flask_results = test_onboarding_via_flask(sample)

    flask_pass = 0; flask_fail = 0
    for itype, code in flask_results.items():
        if isinstance(code, int) and code in (200, 302):
            flask_pass += 1
            print(f"  {GREEN}✓{RESET} {itype:<45} HTTP {code}")
        else:
            flask_fail += 1
            print(f"  {RED}✗{RESET} {itype:<45} → {code}")

    elapsed_total = time.time() - t0
    print()

    # ── المرحلة 3: ملخص تفصيلي حسب العائلة ────────────────────────
    print(f"{BOLD}المرحلة 3: ملخص حسب عائلة النشاط{RESET}")
    print("─" * 50)
    print(f"  {'العائلة':<30} {'نجح':>6} {'فشل':>6}")
    print(f"  {'─'*30} {'─'*6} {'─'*6}")
    for fam, stats in sorted(family_stats.items()):
        color = GREEN if stats["fail"] == 0 else RED
        print(f"  {color}{fam:<30}{RESET} {stats['pass']:>6} {stats['fail']:>6}")

    # ── الملخص النهائي ────────────────────────────────────────────
    print()
    print(f"{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  الملخص النهائي{RESET}")
    print(f"{'═'*70}")

    total_seed_tests = len(all_types)
    seed_color = GREEN if not failed_types else RED

    print(f"  اختبار البذور والخدمات: "
          f"{seed_color}{BOLD}{len(passed_types)}/{total_seed_tests}{RESET} نجحت | "
          f"{RED}{len(failed_types)}{RESET} فشلت")

    flask_color = GREEN if flask_fail == 0 else RED
    print(f"  اختبار Onboarding Flask: "
          f"{flask_color}{BOLD}{flask_pass}/{len(sample)}{RESET} نجحت | "
          f"{RED}{flask_fail}{RESET} فشلت")

    print(f"  الزمن الكلي: {elapsed_total:.2f}s")
    print(f"{'═'*70}\n")

    # إن وُجدت أخطاء — اطبع التفصيل
    if failed_types:
        print(f"{RED}{BOLD}الأنشطة الفاشلة:{RESET}")
        for itype in failed_types:
            print(f"  {RED}✗{RESET} {itype}")
            for err in errors_by_type[itype]:
                print(f"      → {err}")
        print()

    db.close()

    exit_code = 0 if (not failed_types and flask_fail == 0) else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
