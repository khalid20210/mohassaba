# -*- coding: utf-8 -*-
"""Load test: 500 concurrent POS checkouts"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import threading
import time
import statistics
import json
from modules import create_app
from modules.extensions import get_db

# ─── إعداد التطبيق ──────────────────────────────────────────────────
app = create_app()

with app.app_context():
    db = get_db()
    user = db.execute(
        "SELECT id, business_id FROM users ORDER BY id LIMIT 1"
    ).fetchone()
    if not user:
        print("❌ لا يوجد مستخدمون في قاعدة البيانات")
        raise SystemExit(1)
    user_id = int(user["id"])
    biz_id  = int(user["business_id"])

    # نفضل منتجاً لا يتتبع المخزون (track_stock=0) لتجنب رفض بسبب نقص الكمية
    product = db.execute(
        "SELECT id, sale_price FROM products WHERE business_id=? AND is_active=1 AND track_stock=0 LIMIT 1",
        (biz_id,)
    ).fetchone()
    if not product:
        product = db.execute(
            "SELECT id, sale_price FROM products WHERE business_id=? AND is_active=1 LIMIT 1",
            (biz_id,)
        ).fetchone()
    if not product:
        print("❌ لا يوجد منتجات في قاعدة البيانات")
        raise SystemExit(1)

    product_id    = int(product["id"])
    product_price = float(product["sale_price"] or 10.0)

    # تأكد من وجود مستودع وكمية كافية للاختبار
    wh = db.execute(
        "SELECT id FROM warehouses WHERE business_id=? AND is_active=1 LIMIT 1", (biz_id,)
    ).fetchone()
    if wh:
        db.execute(
            "INSERT OR IGNORE INTO stock (business_id,product_id,warehouse_id,quantity,avg_cost) VALUES (?,?,?,999999,0)",
            (biz_id, product_id, wh["id"])
        )
        db.execute(
            "UPDATE stock SET quantity=999999 WHERE product_id=? AND warehouse_id=?",
            (product_id, wh["id"])
        )
        db.commit()

print(f"✅ المستخدم: {user_id} | المنشأة: {biz_id} | المنتج: {product_id} (سعر: {product_price})")

# ─── إعداد العميل ───────────────────────────────────────────────────
client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"]     = user_id
    sess["business_id"] = biz_id

CHECKOUT_PAYLOAD = json.dumps({
    "items": [{"product_id": product_id, "quantity": 1, "unit_price": product_price}],
    "payment_method": "cash"
})

# ─── دوال القياس ────────────────────────────────────────────────────
results_lock = threading.Lock()
latencies    = []
statuses     = []

def do_checkout():
    """كل thread يفتح test_client مستقلاً لتجنب تعارض الـ connections."""
    local_client = app.test_client()
    with local_client.session_transaction() as sess:
        sess["user_id"]     = user_id
        sess["business_id"] = biz_id
    t0 = time.perf_counter()
    try:
        resp = local_client.post(
            "/api/pos/checkout",
            data=CHECKOUT_PAYLOAD,
            content_type="application/json",
        )
        status = resp.status_code
        ok     = (status == 200)
    except Exception:
        status = -1
        ok     = False
    elapsed_ms = (time.perf_counter() - t0) * 1000
    with results_lock:
        latencies.append(elapsed_ms)
        statuses.append(ok)

# ─── دوال الاختبار ──────────────────────────────────────────────────
def run_wave(concurrency: int, label: str):
    """تشغيل موجة من العمليات المتزامنة وقياس النتائج."""
    latencies.clear()
    statuses.clear()

    threads = [threading.Thread(target=do_checkout) for _ in range(concurrency)]
    wave_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wave_elapsed = (time.perf_counter() - wave_start)

    total      = len(statuses)
    success    = sum(statuses)
    failures   = total - success
    tps        = round(total / wave_elapsed, 1)
    p50        = round(statistics.median(latencies), 1)
    p95        = round(sorted(latencies)[int(0.95 * len(latencies))], 1)
    p99        = round(sorted(latencies)[int(0.99 * len(latencies))], 1) if len(latencies) >= 100 else round(max(latencies), 1)
    avg        = round(statistics.mean(latencies), 1)

    passed = (failures == 0) and (p95 <= 200)

    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(f"  طلبات:          {total}  (نجح: {success} | فشل: {failures})")
    print(f"  مدة الموجة:     {round(wave_elapsed, 3)} ثانية")
    print(f"  TPS (فعلي):     {tps} عملية/ثانية")
    print(f"  Latency p50:    {p50} ms")
    print(f"  Latency p95:    {p95} ms  {'✅' if p95 <= 200 else '⚠️'}")
    print(f"  Latency p99:    {p99} ms")
    print(f"  متوسط:          {avg} ms")
    print(f"  النتيجة:        {'✅ اجتاز' if passed else '❌ لم يجتز'}")
    return {"tps": tps, "p95": p95, "success": success, "failures": failures, "passed": passed}


# ─── تشغيل الاختبارات ───────────────────────────────────────────────
print("\n" + "═"*60)
print("  🚀 اختبار الضغط العالي - POS Checkout")
print("  المعيار: p95 < 200ms | معدل النجاح 100%")
print("═"*60)

# المرحلة 1: إحماء (10 عمليات)
run_wave(10,  "المرحلة 1 — إحماء (10 طلبات متزامنة)")

# المرحلة 2: ضغط متوسط (50 عملية)
r2 = run_wave(50, "المرحلة 2 — ضغط متوسط (50 طلبات متزامنة)")

# المرحلة 3: ضغط عالي (100 عملية)
r3 = run_wave(100, "المرحلة 3 — ضغط عالي (100 طلبات متزامنة)")

# المرحلة 4: ضغط قصوى (500 عملية) — الاختبار الحاسم
r4 = run_wave(500, "المرحلة 4 — ضغط قصوى (500 طلبات متزامنة) 🔥")

# ─── الملخص النهائي ──────────────────────────────────────────────────
print(f"\n{'═'*60}")
print("  📊 الملخص النهائي")
print(f"{'═'*60}")

all_passed = r3["passed"] and r4["passed"]
if all_passed:
    print("  ✅ النظام اجتاز اختبار Enterprise Grade!")
    print(f"  - 100 TPS: p95={r3['p95']}ms | فشل={r3['failures']}")
    print(f"  - 500 TPS: p95={r4['p95']}ms | فشل={r4['failures']}")
else:
    print("  ⚠️  النظام يحتاج تحسين:")
    if not r3["passed"]:
        print(f"  - 100 TPS: p95={r3['p95']}ms (المطلوب < 200ms) | فشل={r3['failures']}")
    if not r4["passed"]:
        print(f"  - 500 TPS: p95={r4['p95']}ms (المطلوب < 200ms) | فشل={r4['failures']}")

print(f"{'═'*60}\n")
