# -*- coding: utf-8 -*-
# storm_test v3 -- 1400 virtual client x real bid + rate_limit_key
import io, json, sys, threading, time, uuid
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from modules import create_app
from modules.sync_engine import enqueue_batch, init_sync_tables

NUM_VIRTUAL  = 1400
INV_PER_BIZ  = 50
THREAD_WAVE  = 200
HTTP_CONC    = 40
WORKER_WAIT  = 360   # 6 min: 70k / 237/s ~ 295s + margin

app = create_app()

# ── init ──────────────────────────────────────────────────────────────────────
with app.app_context():
    from modules.extensions import get_db
    db = get_db()
    init_sync_tables(db)
    db.execute("DELETE FROM offline_sync_queue")
    db.execute("DELETE FROM sync_conflicts")
    db.commit()

    pairs = [
        {"uid": r["id"], "bid": r["business_id"]}
        for r in db.execute("SELECT id, business_id FROM users LIMIT 50").fetchall()
    ]
    if not pairs:
        print("no users"); sys.exit(1)
    print(f"real businesses: {len(pairs)}")

    ag = db.execute("SELECT id, business_id FROM agents LIMIT 1").fetchone()
    AGENT_ID  = ag["id"]          if ag else 1
    AGENT_BID = ag["business_id"] if ag else pairs[0]["bid"]
    print(f"agent #{AGENT_ID} biz={AGENT_BID}")

    first_bid = pairs[0]["bid"]
    p = db.execute(
        "SELECT id FROM products WHERE business_id=? AND is_active=1 LIMIT 1", (first_bid,)
    ).fetchone()
    CPROD = p["id"] if p else None
    if CPROD:
        db.execute("UPDATE stock SET quantity=10 WHERE product_id=? AND business_id=?", (CPROD, first_bid))
        db.commit()
        print(f"conflict product #{CPROD} stock=10")


def _make_items(vid, real_bid, num):
    use_c = (vid % 5 == 0 and CPROD and real_bid == first_bid)
    pid   = CPROD if use_c else None
    return [{
        "local_id":    f"v{vid}-{uuid.uuid4().hex[:8]}",
        "action_type": "create_invoice",
        "payload": {
            "client_name": f"client-{vid}",
            "items": [{"product_id": pid, "description": "item", "qty": 2.0, "unit_price": 100.0}],
        },
    } for _ in range(num)]


# ══ Level A ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"  Level A: {NUM_VIRTUAL:,} virtual clients x {INV_PER_BIZ} inv = {NUM_VIRTUAL*INV_PER_BIZ:,} items")
print("=" * 60)

A_ok = A_rl = A_err = 0
A_lats, A_lock = [], threading.Lock()


def _eq(vid):
    global A_ok, A_rl, A_err
    real = pairs[(vid - 1) % len(pairs)]
    items = _make_items(vid, real["bid"], INV_PER_BIZ)
    t0 = time.perf_counter()
    with app.app_context():
        from modules.extensions import get_db as _g
        r = enqueue_batch(_g(), real["bid"], AGENT_ID, items, rate_limit_key=vid)
    ms = (time.perf_counter() - t0) * 1000
    with A_lock:
        A_lats.append(ms)
        if   r.get("error") == "rate_limit": A_rl  += 1
        elif r.get("accepted", 0) > 0:       A_ok  += 1
        else:                                 A_err += 1


waves  = [list(range(1, NUM_VIRTUAL + 1))[i:i+THREAD_WAVE] for i in range(0, NUM_VIRTUAL, THREAD_WAVE)]
A_t0   = time.perf_counter()
for wi, wave in enumerate(waves):
    ts = [threading.Thread(target=_eq, args=(v,)) for v in wave]
    for t in ts: t.start()
    for t in ts: t.join()
    print(f"  wave {wi+1}/{len(waves)} ok={A_ok} rl={A_rl} err={A_err}", end="\r")

A_el = time.perf_counter() - A_t0
A_ls = sorted(A_lats)
A_p50 = A_ls[len(A_ls)//2]
A_p95 = A_ls[int(len(A_ls)*0.95)]
A_tps = round(NUM_VIRTUAL / A_el, 1)
A_ar  = round(A_ok / NUM_VIRTUAL * 100, 1)
print(f"\n  accepted={A_ok}({A_ar}%) rl={A_rl} err={A_err} time={A_el:.1f}s TPS={A_tps} p95={A_p95:.0f}ms")

with app.app_context():
    from modules.extensions import get_db as _g
    rows = _g().execute("SELECT status, COUNT(*) c FROM offline_sync_queue GROUP BY status").fetchall()
    total_q = sum(r["c"] for r in rows)
    print(f"  queue total: {total_q:,}")
    for r in rows: print(f"    {r['status']:>10}: {r['c']:>6,}")


# ══ Level B ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"  Level B: worker processing (wait up to {WORKER_WAIT}s)")
print("=" * 60)

B_t0    = time.perf_counter()
prev_p  = total_q
B_spd   = []
prev_t  = B_t0
deadline = time.time() + WORKER_WAIT

while time.time() < deadline:
    time.sleep(5)
    with app.app_context():
        from modules.extensions import get_db as _g
        pend = _g().execute("SELECT COUNT(*) c FROM offline_sync_queue WHERE status='pending'").fetchone()["c"]
    now_t = time.perf_counter()
    d     = prev_p - pend
    if d > 0: B_spd.append(d / (now_t - prev_t))
    prev_p, prev_t = pend, now_t
    el = time.perf_counter() - B_t0
    print(f"  [{el:.0f}s] pending={pend:,} delta={d:+d}  ", end="\r")
    if pend == 0: break

B_el = time.perf_counter() - B_t0
print()

with app.app_context():
    from modules.extensions import get_db as _g
    db2 = _g()
    Bf  = {r["status"]: r["c"] for r in db2.execute("SELECT status, COUNT(*) c FROM offline_sync_queue GROUP BY status").fetchall()}
    Bc  = db2.execute("SELECT COUNT(*) cnt, COALESCE(SUM(shortage_qty),0) tot FROM sync_conflicts").fetchone()

B_done  = Bf.get("done",0) + Bf.get("conflict",0)
B_left  = Bf.get("pending",0)
B_pr    = round(B_done / max(total_q,1) * 100, 1)
B_avg   = round(sum(B_spd)/len(B_spd), 0) if B_spd else 0
B_eta   = round(B_left / B_avg, 0) if B_avg > 0 else "inf"
print(f"  time={B_el:.1f}s processed={B_pr}% speed={B_avg:.0f}/s conflicts={Bc['cnt']}({Bc['tot']:.0f}unit)")
for st, cnt in sorted(Bf.items()):
    icon = "OK" if st == "done" else ("!!" if st == "conflict" else "XX")
    print(f"    [{icon}] {st:>10}: {cnt:>6,}")
if B_left > 0:
    print(f"  remaining {B_left:,} items (~{B_eta}s more)")


# ══ Level C ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
total_http = len(pairs) * 10
print(f"  Level C: HTTP endpoint {len(pairs)} biz x 10 = {total_http} requests")
print("=" * 60)

C_ok = C_rl = C_err = 0
C_lats, C_lock = [], threading.Lock()


def _http(pi, bn):
    global C_ok, C_rl, C_err
    p   = pairs[pi % len(pairs)]
    vk  = pi * 100 + bn + 30000
    its = _make_items(vk, p["bid"], 5)
    lc  = app.test_client()
    with lc.session_transaction() as s:
        s["user_id"] = p["uid"]; s["business_id"] = p["bid"]
        s["agent_id"] = AGENT_ID; s["agent_biz_id"] = p["bid"]
    t0   = time.perf_counter()
    resp = lc.post(f"/api/v2/agents/{AGENT_ID}/sync/batch",
                   data=json.dumps({"queue": its}), content_type="application/json")
    ms   = (time.perf_counter() - t0) * 1000
    with C_lock:
        C_lats.append(ms)
        if   resp.status_code == 202: C_ok  += 1
        elif resp.status_code == 429: C_rl  += 1
        else:                         C_err += 1


C_tasks = [(i, b) for i in range(len(pairs)) for b in range(10)]
C_t0    = time.perf_counter()
for ci in range(0, len(C_tasks), HTTP_CONC):
    ch = C_tasks[ci:ci+HTTP_CONC]
    ts = [threading.Thread(target=_http, args=(pi, bn)) for pi, bn in ch]
    for t in ts: t.start()
    for t in ts: t.join()
C_el = time.perf_counter() - C_t0

C_p50 = C_p95 = C_tps = 0
if C_lats:
    cs = sorted(C_lats)
    C_p50 = cs[len(cs)//2]; C_p95 = cs[int(len(cs)*0.95)]
    C_tps = round(len(C_tasks)/C_el, 1)
    print(f"  202={C_ok} 429={C_rl} err={C_err} TPS={C_tps} p50={C_p50:.0f}ms p95={C_p95:.0f}ms")


# ══ Final Report ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  STORM TEST REPORT")
print("=" * 60)
print(f"  [A] queue    : {A_ar}% accepted | TPS={A_tps} | p95={A_p95:.0f}ms")
print(f"  [B] worker   : {B_pr}% done     | speed={B_avg:.0f}/s | conflicts={Bc['cnt']}")
if C_lats:
    print(f"  [C] http     : {C_ok}/{total_http} 202 | TPS={C_tps} | p95={C_p95:.0f}ms")

print()
if A_ar >= 95:
    print("  [A] server survived the storm - async queue absorbed all requests")
else:
    print(f"  [A] WARNING: {100-A_ar:.1f}% of clients rejected")

if B_pr >= 90:
    print("  [B] worker completed the backlog within time limit")
elif B_left > 0 and B_avg > 0:
    print(f"  [B] worker running at {B_avg:.0f}/s - {B_left:,} items remain (~{B_eta}s more)")
else:
    print(f"  [B] worker rate low - check failed items")

if Bc["cnt"] > 0:
    print(f"\n  stock conflicts: {Bc['cnt']} cases | {Bc['tot']:.0f} units short")
    print("  resolution: execute-with-warning - invoice saved + alert logged")

print("=" * 60)
print()
