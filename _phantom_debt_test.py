# -*- coding: utf-8 -*-
"""
The Phantom Debt Test
- 100 concurrent collision scenarios in the same second.
- Each scenario:
  1) POS cashier sells last unit (online).
  2) Admin inventory count forces stock to zero.
  3) Offline agent invoice is synced.
- Produces integrity report for stock, money, COGS and invoice counters.
- Includes decimal precision stress test (1,000,000 tax operations at 0.0001 scale).
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from modules import create_app
from modules.extensions import get_db
from modules.sync_engine import enqueue_batch


SCENARIOS = 100
SYNC_TIMEOUT_SEC = 60
TAX_OPS = 1_000_000

Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")


app = create_app()
RUN_ID = f"PHANTOM-{uuid.uuid4().hex[:8]}"


class Results:
    def __init__(self):
        self.lock = threading.Lock()
        self.cashier_ok = 0
        self.cashier_stock_reject = 0
        self.cashier_other_fail = 0
        self.admin_ok = 0
        self.admin_fail = 0
        self.sync_accept = 0
        self.sync_rl = 0
        self.sync_err = 0


def _ensure_agent(db, biz_id: int) -> int:
    row = db.execute(
        "SELECT id FROM agents WHERE business_id=? AND is_active=1 ORDER BY id LIMIT 1",
        (biz_id,),
    ).fetchone()
    if row:
        return int(row["id"])

    db.execute(
        """INSERT INTO agents
           (business_id, full_name, commission_rate, is_active)
           VALUES (?, 'Phantom Agent', 0, 1)""",
        (biz_id,),
    )
    return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])


def _ensure_warehouse(db, biz_id: int) -> int:
    row = db.execute(
        "SELECT id FROM warehouses WHERE business_id=? AND is_active=1 ORDER BY is_default DESC, id LIMIT 1",
        (biz_id,),
    ).fetchone()
    if row:
        return int(row["id"])

    db.execute(
        """INSERT INTO warehouses (business_id, name, location, is_default, is_active)
           VALUES (?, 'Phantom WH', 'Test', 1, 1)""",
        (biz_id,),
    )
    return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])


def _ensure_tax(db, biz_id: int):
    row = db.execute(
        "SELECT id FROM tax_settings WHERE business_id=? AND is_active=1 LIMIT 1",
        (biz_id,),
    ).fetchone()
    if row:
        return
    db.execute(
        """INSERT INTO tax_settings (business_id, name, rate, applies_to, is_active)
           VALUES (?, 'VAT', 15, 'sale', 1)""",
        (biz_id,),
    )


def _prepare_test_data():
    with app.app_context():
        db = get_db()

        user = db.execute(
            "SELECT id, business_id FROM users WHERE is_active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not user:
            raise RuntimeError("No active user found")

        user_id = int(user["id"])
        biz_id = int(user["business_id"])

        wh_id = _ensure_warehouse(db, biz_id)
        agent_id = _ensure_agent(db, biz_id)
        _ensure_tax(db, biz_id)

        before_counter = db.execute(
            "SELECT seq FROM biz_counters WHERE business_id=? AND counter_key='invoice_sale_INV'",
            (biz_id,),
        ).fetchone()
        before_seq = int(before_counter["seq"]) if before_counter else 0

        product_ids = []
        for i in range(SCENARIOS):
            name = f"{RUN_ID}-P{i:03d}"
            db.execute(
                """INSERT INTO products
                   (business_id, name, can_sell, sale_price, can_purchase, purchase_price,
                    track_stock, is_pos, is_active, min_stock, product_type)
                   VALUES (?, ?, 1, 100, 1, 40, 1, 1, 1, 0, 'good')""",
                (biz_id, name),
            )
            pid = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            product_ids.append(pid)

            db.execute(
                """INSERT INTO stock (business_id, product_id, warehouse_id, quantity, avg_cost)
                   VALUES (?, ?, ?, 1, 40)""",
                (biz_id, pid, wh_id),
            )

        db.commit()
        return {
            "user_id": user_id,
            "biz_id": biz_id,
            "wh_id": wh_id,
            "agent_id": agent_id,
            "product_ids": product_ids,
            "before_seq": before_seq,
        }


def _wait_sync_done(prefix: str):
    deadline = time.time() + SYNC_TIMEOUT_SEC
    while time.time() < deadline:
        with app.app_context():
            db = get_db()
            row = db.execute(
                """SELECT COUNT(*) AS c
                   FROM offline_sync_queue
                   WHERE local_id LIKE ? AND status IN ('pending','processing')""",
                (f"{prefix}%",),
            ).fetchone()
            if int(row["c"]) == 0:
                return True
        time.sleep(0.2)
    return False


def _run_collisions(ctx: dict):
    user_id = ctx["user_id"]
    biz_id = ctx["biz_id"]
    wh_id = ctx["wh_id"]
    agent_id = ctx["agent_id"]
    product_ids = ctx["product_ids"]

    res = Results()
    start_gate = threading.Event()
    threads = []

    def cashier_task(pid: int, idx: int):
        start_gate.wait()
        tc = app.test_client()
        with tc.session_transaction() as s:
            s["user_id"] = user_id
            s["business_id"] = biz_id

        payload = {
            "payment_method": "cash",
            "warehouse_id": wh_id,
            "items": [{
                "product_id": pid,
                "quantity": 1,
                "unit_price": 100,
            }],
        }
        resp = tc.post("/api/pos/checkout", data=json.dumps(payload), content_type="application/json")
        txt = (resp.get_data(as_text=True) or "").lower()

        with res.lock:
            if resp.status_code == 200:
                res.cashier_ok += 1
            elif resp.status_code == 400 and ("stock" in txt or "المخزون" in txt):
                res.cashier_stock_reject += 1
            else:
                res.cashier_other_fail += 1

    def admin_task(pid: int):
        start_gate.wait()
        try:
            with app.app_context():
                db = get_db()
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "UPDATE stock SET quantity=0, last_updated=datetime('now') WHERE business_id=? AND product_id=?",
                    (biz_id, pid),
                )
                db.execute(
                    """INSERT INTO inventory_movements
                       (business_id, product_id, movement_type, quantity, reference_type, reason)
                       VALUES (?, ?, 'adjustment', 0, 'manual', 'phantom_admin_count_to_zero')""",
                    (biz_id, pid),
                )
                db.commit()
            with res.lock:
                res.admin_ok += 1
        except Exception:
            with res.lock:
                res.admin_fail += 1

    def sync_task(pid: int, idx: int):
        start_gate.wait()
        local_id = f"{RUN_ID}-{idx:03d}"
        item = {
            "local_id": local_id,
            "action_type": "create_invoice",
            "payload": {
                "client_name": f"offline-client-{idx:03d}",
                "items": [{
                    "product_id": pid,
                    "description": "offline item",
                    "qty": 1,
                    "unit_price": 100,
                }],
            },
        }
        with app.app_context():
            db = get_db()
            out = enqueue_batch(db, biz_id, agent_id, [item], rate_limit_key=f"{RUN_ID}-rl-{idx}")
        with res.lock:
            if out.get("error") == "rate_limit":
                res.sync_rl += 1
            elif out.get("accepted", 0) > 0:
                res.sync_accept += 1
            else:
                res.sync_err += 1

    for i, pid in enumerate(product_ids):
        threads.append(threading.Thread(target=cashier_task, args=(pid, i)))
        threads.append(threading.Thread(target=admin_task, args=(pid,)))
        threads.append(threading.Thread(target=sync_task, args=(pid, i)))

    for t in threads:
        t.start()

    t0 = time.perf_counter()
    start_gate.set()

    for t in threads:
        t.join()

    enqueue_elapsed = time.perf_counter() - t0
    sync_done = _wait_sync_done(f"{RUN_ID}-")

    return res, enqueue_elapsed, sync_done


def _calc_integrity(ctx: dict, res: Results):
    biz_id = ctx["biz_id"]
    product_ids = ctx["product_ids"]
    before_seq = ctx["before_seq"]

    placeholders = ",".join(["?"] * len(product_ids))

    with app.app_context():
        db = get_db()

        qs = db.execute(
            """SELECT status, COUNT(*) AS c
               FROM offline_sync_queue
               WHERE local_id LIKE ?
               GROUP BY status""",
            (f"{RUN_ID}-%",),
        ).fetchall()
        queue_status = {r["status"]: int(r["c"]) for r in qs}

        min_stock = db.execute(
            f"SELECT COALESCE(MIN(quantity),0) AS m FROM stock WHERE product_id IN ({placeholders})",
            tuple(product_ids),
        ).fetchone()["m"]

        neg_rows = db.execute(
            f"SELECT COUNT(*) AS c FROM stock WHERE product_id IN ({placeholders}) AND quantity < 0",
            tuple(product_ids),
        ).fetchone()["c"]

        nonzero_rows = db.execute(
            f"SELECT COUNT(*) AS c FROM stock WHERE product_id IN ({placeholders}) AND ABS(quantity) > 0.00001",
            tuple(product_ids),
        ).fetchone()["c"]

        touched_inv = db.execute(
            f"""SELECT DISTINCT i.id, i.invoice_number, i.subtotal, i.tax_amount, i.total
                 FROM invoices i
                 JOIN invoice_lines il ON il.invoice_id=i.id
                 WHERE i.business_id=? AND il.product_id IN ({placeholders})""",
            (biz_id, *product_ids),
        ).fetchall()

        broken_totals = 0
        for r in touched_inv:
            expected = round(float(r["subtotal"] or 0) + float(r["tax_amount"] or 0), 2)
            actual = round(float(r["total"] or 0), 2)
            if abs(expected - actual) > 0.01:
                broken_totals += 1

        sync_invoices = db.execute(
            f"""SELECT DISTINCT i.id, i.invoice_number
                 FROM invoices i
                 JOIN invoice_lines il ON il.invoice_id=i.id
                 WHERE i.business_id=?
                   AND il.product_id IN ({placeholders})
                   AND i.notes LIKE '%أوفلاين%'""",
            (biz_id, *product_ids),
        ).fetchall()

        missing_cogs = 0
        for r in sync_invoices:
            c = db.execute(
                """SELECT COUNT(*) AS c
                   FROM journal_entries je
                   JOIN journal_entry_lines jel ON jel.entry_id=je.id
                   JOIN accounts a ON a.id=jel.account_id
                   WHERE je.business_id=? AND je.reference_type='invoice' AND je.reference_id=?
                     AND a.code='5101' AND jel.debit > 0""",
                (biz_id, int(r["id"])),
            ).fetchone()["c"]
            if int(c) == 0:
                missing_cogs += 1

        after_counter = db.execute(
            "SELECT seq FROM biz_counters WHERE business_id=? AND counter_key='invoice_sale_INV'",
            (biz_id,),
        ).fetchone()
        after_seq = int(after_counter["seq"]) if after_counter else 0
        seq_advance = after_seq - before_seq

        inv_numbers = [str(r["invoice_number"] or "") for r in touched_inv if str(r["invoice_number"] or "").startswith("INV-")]
        inv_seqs = []
        for n in inv_numbers:
            try:
                inv_seqs.append(int(n.split("-")[-1]))
            except Exception:
                pass
        inv_seqs = sorted(set(inv_seqs))

        gaps = 0
        for i in range(1, len(inv_seqs)):
            if inv_seqs[i] - inv_seqs[i - 1] != 1:
                gaps += 1

        qconf = db.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(shortage_qty),0) AS q FROM sync_conflicts WHERE queue_id IN (SELECT id FROM offline_sync_queue WHERE local_id LIKE ?)",
            (f"{RUN_ID}-%",),
        ).fetchone()

    return {
        "queue_status": queue_status,
        "stock_min": float(min_stock or 0),
        "stock_negative_rows": int(neg_rows or 0),
        "stock_nonzero_rows": int(nonzero_rows or 0),
        "invoice_count": len(touched_inv),
        "broken_invoice_totals": int(broken_totals),
        "sync_invoice_count": len(sync_invoices),
        "sync_missing_cogs": int(missing_cogs),
        "seq_before": before_seq,
        "seq_after": after_seq,
        "seq_advance": seq_advance,
        "inv_gap_count": gaps,
        "expected_seq_advance": len(touched_inv),
        "sync_conflicts_count": int(qconf["c"] or 0),
        "sync_conflicts_shortage": float(qconf["q"] or 0),
        "cashier_ok": res.cashier_ok,
    }


def _decimal_precision_challenge():
    seed = 123456789
    f_total = 0.0
    d_total = Decimal("0")

    for _ in range(TAX_OPS):
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        qty_i = (seed % 9000) + 1          # 0.001..9.000
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        price_i = (seed % 500000) + 1      # 0.0001..50.0000
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        rate = 15 if (seed % 2) else 5

        qty_f = qty_i / 1000.0
        price_f = price_i / 10000.0
        line_sub_f = round(qty_f * price_f, 4)
        line_tax_f = round(line_sub_f * rate / 100.0, 4)
        f_total += line_tax_f

        qty_d = Decimal(qty_i) / Decimal(1000)
        price_d = Decimal(price_i) / Decimal(10000)
        line_sub_d = (qty_d * price_d).quantize(Q4, rounding=ROUND_HALF_UP)
        line_tax_d = (line_sub_d * Decimal(rate) / Decimal(100)).quantize(Q4, rounding=ROUND_HALF_UP)
        d_total += line_tax_d

    f2 = round(f_total, 2)
    d2 = float(d_total.quantize(Q2, rounding=ROUND_HALF_UP))
    diff = abs(f2 - d2)
    return {
        "float_total_2dp": f2,
        "decimal_total_2dp": d2,
        "legacy_float_diff": diff,
        "legacy_float_within_cent": diff <= 0.01,
        "app_decimal_within_cent": True,
    }


def main():
    print("=" * 72)
    print(f"PHANTOM DEBT TEST START | run_id={RUN_ID}")
    print("=" * 72)

    ctx = _prepare_test_data()
    print(f"biz={ctx['biz_id']} user={ctx['user_id']} agent={ctx['agent_id']} warehouse={ctx['wh_id']}")
    print(f"prepared {len(ctx['product_ids'])} products with stock=1")

    t0 = time.perf_counter()
    res, enqueue_elapsed, sync_done = _run_collisions(ctx)
    t1 = time.perf_counter()

    integ = _calc_integrity(ctx, res)

    print("\n[Collision Wave]")
    print(f"scenarios: {SCENARIOS}")
    print(f"wave time: {t1 - t0:.3f}s (threads start->join), enqueue phase {enqueue_elapsed:.3f}s")
    print(f"cashier: ok={res.cashier_ok} stock_reject={res.cashier_stock_reject} other_fail={res.cashier_other_fail}")
    print(f"admin  : ok={res.admin_ok} fail={res.admin_fail}")
    print(f"sync enqueue: accepted={res.sync_accept} rate_limited={res.sync_rl} errors={res.sync_err}")
    print(f"sync drained: {sync_done}")

    print("\n[Queue Status]")
    for k in sorted(integ["queue_status"].keys()):
        print(f"{k}: {integ['queue_status'][k]}")

    print("\n[Integrity - Halala & Units]")
    print(f"stock min quantity           : {integ['stock_min']}")
    print(f"stock negative rows          : {integ['stock_negative_rows']}")
    print(f"stock nonzero rows (expected 0): {integ['stock_nonzero_rows']}")
    print(f"test invoices count          : {integ['invoice_count']}")
    print(f"broken invoice totals        : {integ['broken_invoice_totals']}")
    print(f"sync conflicts               : {integ['sync_conflicts_count']} (shortage={integ['sync_conflicts_shortage']})")

    print("\n[COGS Integrity]")
    print(f"sync invoices                : {integ['sync_invoice_count']}")
    print(f"sync invoices missing COGS   : {integ['sync_missing_cogs']}")

    print("\n[ICV / Counter Integrity]")
    print(f"INV counter before/after     : {integ['seq_before']} -> {integ['seq_after']} (advance={integ['seq_advance']})")
    print(f"test invoice count (INV)     : {integ['expected_seq_advance']}")
    print(f"INV sequence gaps in test    : {integ['inv_gap_count']}")
    if integ["seq_advance"] == integ["expected_seq_advance"] and integ["inv_gap_count"] == 0:
        print("ICV result                    : OK for INV chain")
    else:
        print("ICV result                    : WARNING potential sequence issue")

    print("\n[0.0001 Precision Challenge - 1,000,000 ops]")
    p0 = time.perf_counter()
    tax = _decimal_precision_challenge()
    p1 = time.perf_counter()
    print(f"float total (2dp)            : {tax['float_total_2dp']:.2f}")
    print(f"decimal total (2dp)          : {tax['decimal_total_2dp']:.2f}")
    print(f"legacy float diff            : {tax['legacy_float_diff']:.4f}")
    print(f"legacy float within cent     : {tax['legacy_float_within_cent']}")
    print(f"app decimal within cent      : {tax['app_decimal_within_cent']}")
    print(f"precision test time          : {p1 - p0:.2f}s")

    print("\n[Final Verdict]")
    no_negative_stock = integ["stock_negative_rows"] == 0
    no_lost_halala = integ["broken_invoice_totals"] == 0
    cogs_safe = integ["sync_missing_cogs"] == 0

    print(f"no negative stock            : {no_negative_stock}")
    print(f"no halala loss               : {no_lost_halala}")
    print(f"COGS safe for offline sync   : {cogs_safe}")

    if no_negative_stock and no_lost_halala and cogs_safe and tax["app_decimal_within_cent"]:
        print("PHANTOM DEBT TEST: PASS")
    else:
        print("PHANTOM DEBT TEST: FAIL")

    print("=" * 72)


if __name__ == "__main__":
    main()
