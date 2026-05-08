"""
أداة تشغيل وصيانة موحدة للمنصة (CRUD + استرجاع + إدارة أنشطة/خدمات/إعدادات).

المزايا:
1) وضع آمن افتراضي (معاينة فقط) لكل العمليات المعدلة.
2) تطبيق فعلي فقط عند تمرير --apply.
3) سجل تدقيق كامل في جدول platform_change_log.
4) استرجاع دفعة تغييرات كاملة عبر batch_id.
5) أوامر عامة لأي جدول + أوامر جاهزة للأنشطة والخدمات والإعدادات.

أمثلة:
  - عرض الجداول:
      .venv\Scripts\python.exe _platform_ops.py tables

  - معاينة تحديث عام (بدون تطبيق):
      .venv\Scripts\python.exe _platform_ops.py update \
        --table businesses \
        --set '{"city":"الرياض"}' \
        --where '{"id": 2}'

  - تطبيق التحديث فعلياً:
      .venv\Scripts\python.exe _platform_ops.py update \
        --table businesses \
        --set '{"city":"الرياض"}' \
        --where '{"id": 2}' \
        --apply

  - تعديل نشاط منشأة مع تحقق من صحة الكود:
      .venv\Scripts\python.exe _platform_ops.py set-activity \
        --business-id 3 --industry-type services_consulting --apply

  - إضافة خدمة كمنتج خدمة لمنشأة:
      .venv\Scripts\python.exe _platform_ops.py add-service \
        --business-id 3 --name "خدمة صيانة دورية" --price 120 --apply

  - استرجاع دفعة:
      .venv\Scripts\python.exe _platform_ops.py rollback --batch-id <BATCH_ID> --apply
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from typing import Any

from modules.config import DB_PATH, INDUSTRY_TYPES


AUDIT_TABLE = "platform_change_log"
BACKUP_MAGIC = b"JNBK1"


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _json_loads(value: str | None, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    value = value.strip()
    if not value:
        return fallback
    return json.loads(value)


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000, dklen=32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_backup_password(explicit: str | None) -> str | None:
    return explicit or os.environ.get("PLATFORM_BACKUP_PASSWORD")


def _create_encrypted_backup(
    db_path: str,
    out_file: str,
    password: str,
    actor: str,
) -> dict[str, Any]:
    with open(db_path, "rb") as f:
        plain = f.read()

    salt = os.urandom(16)
    nonce = os.urandom(16)
    key = _derive_key(password, salt)
    stream = _keystream(key, nonce, len(plain))
    cipher = _xor_bytes(plain, stream)
    mac = hmac.new(key, salt + nonce + cipher, hashlib.sha256).digest()

    os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)
    with open(out_file, "wb") as f:
        f.write(BACKUP_MAGIC)
        f.write(salt)
        f.write(nonce)
        f.write(mac)
        f.write(cipher)

    meta = {
        "created_at": _utc_now(),
        "actor": actor,
        "source_db": db_path,
        "backup_file": out_file,
        "format": "JNBK1",
        "bytes_plain": len(plain),
        "bytes_encrypted": len(cipher),
        "sha256_plain": _sha256_hex(plain),
        "sha256_encrypted": _sha256_hex(cipher),
    }
    meta_file = out_file + ".meta.json"
    with open(meta_file, "w", encoding="utf-8") as mf:
        json.dump(meta, mf, ensure_ascii=False, indent=2)
    meta["meta_file"] = meta_file
    return meta


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            table_name TEXT NOT NULL,
            pk_json TEXT,
            before_json TEXT,
            after_json TEXT,
            changed_at TEXT NOT NULL,
            changed_by TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{AUDIT_TABLE}_batch
        ON {AUDIT_TABLE}(batch_id, id)
        """
    )


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [r["name"] for r in rows]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _quote_ident(name: str) -> str:
    if not name or '"' in name:
        raise ValueError(f"اسم غير صالح: {name}")
    return f'"{name}"'


def _table_columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cols = _table_columns(conn, table)
    pks = [c["name"] for c in cols if int(c["pk"] or 0) > 0]
    if pks:
        return pks

    idx_rows = conn.execute(f"PRAGMA index_list({_quote_ident(table)})").fetchall()
    for idx in idx_rows:
        if int(idx["unique"] or 0) != 1:
            continue
        idx_name = idx["name"]
        parts = conn.execute(f"PRAGMA index_info({_quote_ident(idx_name)})").fetchall()
        candidate = [p["name"] for p in parts]
        if candidate:
            return candidate
    return []


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _extract_pk(row: dict[str, Any], pk_cols: list[str]) -> dict[str, Any]:
    return {k: row.get(k) for k in pk_cols}


def _build_where_clause(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    if not filters:
        return "", []
    parts: list[str] = []
    params: list[Any] = []
    for k, v in filters.items():
        if v is None:
            parts.append(f"{_quote_ident(k)} IS NULL")
        else:
            parts.append(f"{_quote_ident(k)} = ?")
            params.append(v)
    return " WHERE " + " AND ".join(parts), params


def _select_rows(
    conn: sqlite3.Connection,
    table: str,
    where: dict[str, Any] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    where = where or {}
    where_clause, params = _build_where_clause(where)
    sql = f"SELECT * FROM {_quote_ident(table)}{where_clause} LIMIT ?"
    rows = conn.execute(sql, (*params, limit)).fetchall()
    return [_row_to_dict(r) for r in rows]


def _count_rows(
    conn: sqlite3.Connection,
    table: str,
    where: dict[str, Any] | None = None,
) -> int:
    where = where or {}
    where_clause, params = _build_where_clause(where)
    sql = f"SELECT COUNT(*) AS c FROM {_quote_ident(table)}{where_clause}"
    row = conn.execute(sql, params).fetchone()
    return int(row["c"] if row else 0)


def _insert_row(
    conn: sqlite3.Connection,
    table: str,
    payload: dict[str, Any],
) -> int:
    if not payload:
        raise ValueError("payload فارغ")
    cols = list(payload.keys())
    values = [payload[c] for c in cols]
    col_sql = ", ".join(_quote_ident(c) for c in cols)
    val_sql = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES ({val_sql})"
    cur = conn.execute(sql, values)
    return int(cur.lastrowid or 0)


def _update_rows(
    conn: sqlite3.Connection,
    table: str,
    set_values: dict[str, Any],
    where: dict[str, Any],
    allow_full_table: bool = False,
) -> int:
    if not set_values:
        raise ValueError("set فارغ")
    if not where and not allow_full_table:
        raise ValueError("where فارغ — ممنوع التحديث الشامل بدون شرط")

    set_parts: list[str] = []
    params: list[Any] = []
    for k, v in set_values.items():
        set_parts.append(f"{_quote_ident(k)} = ?")
        params.append(v)
    where_clause, where_params = _build_where_clause(where)
    params.extend(where_params)
    sql = f"UPDATE {_quote_ident(table)} SET {', '.join(set_parts)}{where_clause}"
    cur = conn.execute(sql, params)
    return int(cur.rowcount or 0)


def _delete_rows(
    conn: sqlite3.Connection,
    table: str,
    where: dict[str, Any],
    allow_full_table: bool = False,
) -> int:
    if not where and not allow_full_table:
        raise ValueError("where فارغ — ممنوع الحذف الشامل بدون شرط")
    where_clause, params = _build_where_clause(where)
    sql = f"DELETE FROM {_quote_ident(table)}{where_clause}"
    cur = conn.execute(sql, params)
    return int(cur.rowcount or 0)


def _audit(
    conn: sqlite3.Connection,
    batch_id: str,
    operation: str,
    table: str,
    pk: dict[str, Any] | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    actor: str,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {AUDIT_TABLE}
        (batch_id, operation, table_name, pk_json, before_json, after_json, changed_at, changed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            operation,
            table,
            _to_json(pk) if pk is not None else None,
            _to_json(before) if before is not None else None,
            _to_json(after) if after is not None else None,
            _utc_now(),
            actor,
        ),
    )


def _print_rows(rows: list[dict[str, Any]], max_items: int = 20) -> None:
    if not rows:
        print("لا توجد نتائج.")
        return
    for idx, row in enumerate(rows[:max_items], start=1):
        print(f"[{idx}] {_to_json(row)}")
    if len(rows) > max_items:
        print(f"... +{len(rows) - max_items} صف إضافي")


def cmd_tables(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    try:
        tables = _list_tables(conn)
        for t in tables:
            print(t)
        return 0
    finally:
        conn.close()


def cmd_describe(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    try:
        if not _table_exists(conn, args.table):
            print(f"الجدول غير موجود: {args.table}")
            return 1
        cols = _table_columns(conn, args.table)
        for c in cols:
            print(
                f"{c['name']} | type={c['type']} | notnull={c['notnull']} | "
                f"pk={c['pk']} | default={c['dflt_value']}"
            )
        return 0
    finally:
        conn.close()


def cmd_select(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    try:
        if not _table_exists(conn, args.table):
            print(f"الجدول غير موجود: {args.table}")
            return 1
        where = _json_loads(args.where, {})
        rows = _select_rows(conn, args.table, where=where, limit=args.limit)
        _print_rows(rows, max_items=args.limit)
        return 0
    finally:
        conn.close()


def _mutate_guard(apply_flag: bool) -> bool:
    if apply_flag:
        return True
    print("وضع المعاينة فقط. أضف --apply للتنفيذ الفعلي.")
    return False


def _check_table_mutable(table: str, root_mode: bool = False) -> None:
    if table == AUDIT_TABLE and not root_mode:
        raise ValueError(f"تعديل جدول {AUDIT_TABLE} غير مسموح")


def cmd_insert(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    batch_id = args.batch_id or str(uuid.uuid4())
    actor = args.actor
    try:
        _ensure_audit_table(conn)
        table = args.table
        _check_table_mutable(table, root_mode=args.root)
        if not _table_exists(conn, table):
            print(f"الجدول غير موجود: {table}")
            return 1

        payload = _json_loads(args.payload, {})
        if not isinstance(payload, dict):
            raise ValueError("payload يجب أن يكون JSON object")

        if not _mutate_guard(args.apply):
            print(f"[معاينة] insert into {table}: {_to_json(payload)}")
            return 0

        pk_cols = _pk_columns(conn, table)
        rowid = _insert_row(conn, table, payload)

        after: dict[str, Any] | None = None
        pk: dict[str, Any] | None = None
        if pk_cols:
            if len(pk_cols) == 1 and pk_cols[0] not in payload and rowid:
                where = {pk_cols[0]: rowid}
            else:
                where = {k: payload.get(k) for k in pk_cols}
            fetched = _select_rows(conn, table, where=where, limit=1)
            if fetched:
                after = fetched[0]
                pk = _extract_pk(after, pk_cols)
        if pk is None:
            pk = {"rowid": rowid} if rowid else None

        _audit(conn, batch_id, "insert", table, pk, None, after or payload, actor)
        conn.commit()
        print(f"تمت الإضافة بنجاح. batch_id={batch_id}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"فشل العملية: {exc}")
        return 1
    finally:
        conn.close()


def cmd_update(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    batch_id = args.batch_id or str(uuid.uuid4())
    actor = args.actor
    try:
        _ensure_audit_table(conn)
        table = args.table
        _check_table_mutable(table, root_mode=args.root)
        if not _table_exists(conn, table):
            print(f"الجدول غير موجود: {table}")
            return 1

        set_values = _json_loads(args.set_values, {})
        where = _json_loads(args.where, {})
        if not isinstance(set_values, dict) or not isinstance(where, dict):
            raise ValueError("set و where يجب أن يكونا JSON object")

        total = _count_rows(conn, table, where=where)
        if (not args.root) and total > args.limit:
            print(
                f"عدد الصفوف المستهدفة ({total}) أكبر من limit ({args.limit}). "
                "ارفع --limit لتغطية كل الصفوف قبل التطبيق."
            )
            return 1

        before_rows = _select_rows(conn, table, where=where, limit=args.limit)
        print(f"الصفوف المستهدفة: {len(before_rows)}")
        _print_rows(before_rows, max_items=min(10, args.limit))

        if not _mutate_guard(args.apply):
            print(f"[معاينة] update {table} set={_to_json(set_values)} where={_to_json(where)}")
            return 0

        pk_cols = _pk_columns(conn, table)
        changed = _update_rows(conn, table, set_values, where, allow_full_table=args.root)

        for before in before_rows:
            after = dict(before)
            after.update(set_values)
            pk = _extract_pk(before, pk_cols) if pk_cols else None
            _audit(conn, batch_id, "update", table, pk, before, after, actor)

        conn.commit()
        print(f"تم تحديث {changed} صف. batch_id={batch_id}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"فشل العملية: {exc}")
        return 1
    finally:
        conn.close()


def cmd_delete(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    batch_id = args.batch_id or str(uuid.uuid4())
    actor = args.actor
    try:
        _ensure_audit_table(conn)
        table = args.table
        _check_table_mutable(table, root_mode=args.root)
        if not _table_exists(conn, table):
            print(f"الجدول غير موجود: {table}")
            return 1

        where = _json_loads(args.where, {})
        if not isinstance(where, dict):
            raise ValueError("where يجب أن يكون JSON object")

        total = _count_rows(conn, table, where=where)
        if (not args.root) and total > args.limit:
            print(
                f"عدد الصفوف المستهدفة ({total}) أكبر من limit ({args.limit}). "
                "ارفع --limit لتغطية كل الصفوف قبل التطبيق."
            )
            return 1

        before_rows = _select_rows(conn, table, where=where, limit=args.limit)
        print(f"الصفوف المستهدفة للحذف: {len(before_rows)}")
        _print_rows(before_rows, max_items=min(10, args.limit))

        if not _mutate_guard(args.apply):
            print(f"[معاينة] delete from {table} where={_to_json(where)}")
            return 0

        pk_cols = _pk_columns(conn, table)
        changed = _delete_rows(conn, table, where, allow_full_table=args.root)

        for before in before_rows:
            pk = _extract_pk(before, pk_cols) if pk_cols else None
            _audit(conn, batch_id, "delete", table, pk, before, None, actor)

        conn.commit()
        print(f"تم حذف {changed} صف. batch_id={batch_id}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"فشل العملية: {exc}")
        return 1
    finally:
        conn.close()


def _known_industry_types() -> set[str]:
    return {k for k, _ in INDUSTRY_TYPES}


def cmd_set_activity(args: argparse.Namespace) -> int:
    known = _known_industry_types()
    if args.industry_type not in known:
        print("كود نشاط غير معروف في INDUSTRY_TYPES.")
        print("استخدم describe أو راجع modules/config.py لإضافة الكود قبل التطبيق.")
        return 1

    set_payload = {
        "industry_type": args.industry_type,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    where = {"id": args.business_id}
    ns = argparse.Namespace(
        table="businesses",
        set_values=_to_json(set_payload),
        where=_to_json(where),
        limit=5,
        apply=args.apply,
        actor=args.actor,
        batch_id=args.batch_id,
        db_path=args.db_path,
    )
    return cmd_update(ns)


def cmd_add_service(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    batch_id = args.batch_id or str(uuid.uuid4())
    actor = args.actor
    try:
        _ensure_audit_table(conn)
        if not _table_exists(conn, "products"):
            print("جدول products غير موجود")
            return 1

        business_ids: list[int] = []
        if args.all_businesses:
            rows = conn.execute("SELECT id FROM businesses ORDER BY id").fetchall()
            business_ids = [int(r["id"]) for r in rows]
        elif args.business_id is not None:
            business_ids = [args.business_id]
        else:
            print("حدد --business-id أو --all-businesses")
            return 1

        payloads: list[dict[str, Any]] = []
        for bid in business_ids:
            payloads.append(
                {
                    "business_id": bid,
                    "name": args.name,
                    "category_name": args.category,
                    "product_type": "service",
                    "can_purchase": 0,
                    "purchase_price": 0,
                    "can_sell": 1,
                    "sale_price": args.price,
                    "track_stock": 0,
                    "is_pos": 1 if args.show_in_pos else 0,
                    "is_active": 1,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        final_payloads: list[dict[str, Any]] = []
        skipped = 0
        for payload in payloads:
            if args.allow_duplicate:
                final_payloads.append(payload)
                continue
            exists = conn.execute(
                """
                SELECT id FROM products
                WHERE business_id=? AND name=? AND product_type='service'
                LIMIT 1
                """,
                (payload["business_id"], payload["name"]),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            final_payloads.append(payload)

        print(f"سيتم إضافة الخدمة إلى {len(final_payloads)} منشأة | تخطي مكرر: {skipped}")
        _print_rows(final_payloads, max_items=10)

        if not _mutate_guard(args.apply):
            return 0

        pk_cols = _pk_columns(conn, "products")
        inserted = 0
        for payload in final_payloads:
            rowid = _insert_row(conn, "products", payload)
            after = _select_rows(conn, "products", where={"id": rowid}, limit=1)
            after_row = after[0] if after else payload
            pk = _extract_pk(after_row, pk_cols) if pk_cols else {"rowid": rowid}
            _audit(conn, batch_id, "insert", "products", pk, None, after_row, actor)
            inserted += 1

        conn.commit()
        print(f"تمت إضافة {inserted} خدمة. batch_id={batch_id}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"فشل العملية: {exc}")
        return 1
    finally:
        conn.close()


def cmd_upsert_setting(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    batch_id = args.batch_id or str(uuid.uuid4())
    actor = args.actor
    try:
        _ensure_audit_table(conn)
        if not _table_exists(conn, "settings"):
            print("جدول settings غير موجود")
            return 1

        business_ids: list[int] = []
        if args.all_businesses:
            rows = conn.execute("SELECT id FROM businesses ORDER BY id").fetchall()
            business_ids = [int(r["id"]) for r in rows]
        elif args.business_id is not None:
            business_ids = [args.business_id]
        else:
            print("حدد --business-id أو --all-businesses")
            return 1

        targets: list[dict[str, Any]] = []
        for bid in business_ids:
            before = conn.execute(
                "SELECT * FROM settings WHERE business_id=? AND key=? LIMIT 1",
                (bid, args.key),
            ).fetchone()
            targets.append(
                {
                    "business_id": bid,
                    "key": args.key,
                    "before": _row_to_dict(before) if before else None,
                    "after": {"business_id": bid, "key": args.key, "value": args.value},
                }
            )

        print(f"سيتم تحديث الإعداد {args.key} لعدد {len(targets)} منشأة")
        _print_rows([{"business_id": t["business_id"], "before": t["before"], "after": t["after"]} for t in targets], max_items=10)

        if not _mutate_guard(args.apply):
            return 0

        for t in targets:
            conn.execute(
                """
                INSERT INTO settings (business_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(business_id, key) DO UPDATE SET value=excluded.value
                """,
                (t["business_id"], args.key, args.value),
            )
            after = conn.execute(
                "SELECT * FROM settings WHERE business_id=? AND key=? LIMIT 1",
                (t["business_id"], args.key),
            ).fetchone()
            after_row = _row_to_dict(after) if after else t["after"]
            _audit(
                conn,
                batch_id,
                "upsert_setting",
                "settings",
                {"business_id": t["business_id"], "key": args.key},
                t["before"],
                after_row,
                actor,
            )

        conn.commit()
        print(f"تم حفظ الإعدادات بنجاح. batch_id={batch_id}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"فشل العملية: {exc}")
        return 1
    finally:
        conn.close()


def _restore_insert(conn: sqlite3.Connection, table: str, pk: dict[str, Any]) -> None:
    if not pk:
        raise ValueError("تعذر التراجع عن insert بدون مفاتيح")
    _delete_rows(conn, table, pk)


def _restore_update(conn: sqlite3.Connection, table: str, pk: dict[str, Any], before: dict[str, Any]) -> None:
    if not before:
        return
    if not pk:
        raise ValueError("تعذر التراجع عن update بدون مفاتيح")
    _update_rows(conn, table, before, pk)


def _restore_delete(conn: sqlite3.Connection, table: str, before: dict[str, Any]) -> None:
    if not before:
        return
    _insert_row(conn, table, before)


def cmd_rollback(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    actor = args.actor
    rollback_batch = args.new_batch_id or str(uuid.uuid4())
    try:
        _ensure_audit_table(conn)
        rows = conn.execute(
            f"""
            SELECT * FROM {AUDIT_TABLE}
            WHERE batch_id=?
            ORDER BY id DESC
            """,
            (args.batch_id,),
        ).fetchall()

        if not rows:
            print("لا توجد سجلات لهذه الدفعة.")
            return 1

        print(f"سجلات الدفعة المطلوب استرجاعها: {len(rows)}")
        preview = []
        for r in rows[:10]:
            preview.append(
                {
                    "id": r["id"],
                    "operation": r["operation"],
                    "table": r["table_name"],
                    "pk": _json_loads(r["pk_json"], None),
                }
            )
        _print_rows(preview, max_items=10)

        if not _mutate_guard(args.apply):
            return 0

        restored = 0
        for r in rows:
            table = r["table_name"]
            if table == AUDIT_TABLE:
                continue
            op = r["operation"]
            pk = _json_loads(r["pk_json"], None)
            before = _json_loads(r["before_json"], None)
            after = _json_loads(r["after_json"], None)

            if op == "insert":
                _restore_insert(conn, table, pk or {})
                _audit(conn, rollback_batch, "rollback_insert", table, pk, after, None, actor)
            elif op in {"update", "upsert_setting"}:
                _restore_update(conn, table, pk or {}, before or {})
                _audit(conn, rollback_batch, "rollback_update", table, pk, after, before, actor)
            elif op == "delete":
                _restore_delete(conn, table, before or {})
                _audit(conn, rollback_batch, "rollback_delete", table, pk, None, before, actor)
            else:
                raise ValueError(f"نوع عملية غير مدعوم في الاسترجاع: {op}")

            restored += 1

        conn.commit()
        print(f"تم الاسترجاع بنجاح. rollback_batch_id={rollback_batch} | records={restored}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"فشل الاسترجاع: {exc}")
        return 1
    finally:
        conn.close()


def cmd_overview(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    try:
        tables = set(_list_tables(conn))
        print("=== نظرة شاملة على المنصة ===")
        for t in ("businesses", "users", "products", "invoices", "jobs", "service_contracts"):
            if t in tables:
                c = _count_rows(conn, t, {})
                print(f"{t}: {c}")

        print("\n=== آخر 20 تغيير (سجل التدقيق) ===")
        if AUDIT_TABLE in tables:
            rows = conn.execute(
                f"""
                SELECT id, batch_id, operation, table_name, changed_at, changed_by
                FROM {AUDIT_TABLE}
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall()
            _print_rows([_row_to_dict(r) for r in rows], max_items=20)
        else:
            print("لا يوجد سجل تدقيق بعد.")

        for log_table in ("activity_log", "usage_logs", "api_request_log", "audit_logs"):
            if log_table not in tables:
                continue
            print(f"\n=== آخر 10 من {log_table} ===")
            rows = conn.execute(
                f"SELECT * FROM {_quote_ident(log_table)} ORDER BY id DESC LIMIT 10"
            ).fetchall()
            _print_rows([_row_to_dict(r) for r in rows], max_items=10)
        return 0
    finally:
        conn.close()


def cmd_backup_create(args: argparse.Namespace) -> int:
    db_path = str(args.db_path or DB_PATH)
    password = _resolve_backup_password(args.password)
    if not password:
        print("كلمة مرور النسخة الاحتياطية مطلوبة عبر --password أو PLATFORM_BACKUP_PASSWORD")
        return 1

    output = args.output
    if not output:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = os.path.join("backups", f"secure_backup_{stamp}.db.enc")

    try:
        meta = _create_encrypted_backup(db_path=db_path, out_file=output, password=password, actor=args.actor)
        print("تم إنشاء نسخة احتياطية مشفرة بنجاح")
        print(f"backup_file: {meta['backup_file']}")
        print(f"meta_file: {meta['meta_file']}")
        print(f"sha256_plain: {meta['sha256_plain']}")
        print(f"sha256_encrypted: {meta['sha256_encrypted']}")
        return 0
    except Exception as exc:
        print(f"فشل إنشاء النسخة الاحتياطية: {exc}")
        return 1


def _export_tables(
    conn: sqlite3.Connection,
    selected_tables: list[str] | None,
    where: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    tables = _list_tables(conn)
    if selected_tables:
        targets = [t for t in selected_tables if t in tables]
    else:
        targets = tables

    out: dict[str, Any] = {}
    for table in targets:
        filters = where
        rows = _select_rows(conn, table, where=filters, limit=limit)
        out[table] = rows
    return out


def cmd_export(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    try:
        where = _json_loads(args.where, {})
        if args.business_id is not None:
            where = dict(where or {})
            where.setdefault("business_id", args.business_id)

        selected_tables = None
        if args.tables:
            selected_tables = [t.strip() for t in args.tables.split(",") if t.strip()]

        payload = {
            "meta": {
                "exported_at": _utc_now(),
                "db_path": str(args.db_path or DB_PATH),
                "actor": args.actor,
                "where": where,
                "tables": selected_tables,
                "limit": args.limit,
            },
            "data": _export_tables(conn, selected_tables, where, args.limit),
        }

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"تم التصدير بنجاح: {args.output}")
        return 0
    except Exception as exc:
        print(f"فشل التصدير: {exc}")
        return 1
    finally:
        conn.close()


def _upsert_row(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    pk_cols = _pk_columns(conn, table)
    if not pk_cols:
        _insert_row(conn, table, row)
        return

    where = {k: row.get(k) for k in pk_cols}
    exists = _select_rows(conn, table, where=where, limit=1)
    if exists:
        update_values = {k: v for k, v in row.items() if k not in pk_cols}
        if update_values:
            _update_rows(conn, table, update_values, where, allow_full_table=False)
        return
    _insert_row(conn, table, row)


def cmd_import(args: argparse.Namespace) -> int:
    conn = _connect(args.db_path)
    batch_id = args.batch_id or str(uuid.uuid4())
    actor = args.actor
    try:
        _ensure_audit_table(conn)
        if not os.path.exists(args.input):
            print(f"ملف الإدخال غير موجود: {args.input}")
            return 1

        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            print("ملف غير صالح: الحقل data غير موجود أو ليس كائناً")
            return 1

        summary: list[dict[str, Any]] = []
        for table, rows in data.items():
            if not _table_exists(conn, table):
                continue
            if not isinstance(rows, list):
                continue
            summary.append({"table": table, "rows": len(rows)})

        diff_report = _build_import_diff(conn, data, mode=args.mode, sample_limit=args.diff_sample_limit)

        print("ملخص الاستيراد:")
        _print_rows(summary, max_items=50)
        print("ملخص الفروقات المتوقعة:")
        _print_rows(diff_report.get("summary", []), max_items=50)

        if args.diff_report:
            os.makedirs(os.path.dirname(args.diff_report) or ".", exist_ok=True)
            with open(args.diff_report, "w", encoding="utf-8") as df:
                json.dump(diff_report, df, ensure_ascii=False, indent=2)
            print(f"تم حفظ تقرير الفروقات: {args.diff_report}")

        if not _mutate_guard(args.apply):
            return 0

        if args.pre_backup:
            pwd = _resolve_backup_password(args.backup_password)
            if not pwd:
                print("قبل الاستيراد يلزم كلمة مرور النسخة الاحتياطية: --backup-password أو PLATFORM_BACKUP_PASSWORD")
                return 1
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = args.backup_output or os.path.join("backups", f"pre_import_{stamp}.db.enc")
            meta = _create_encrypted_backup(
                db_path=str(args.db_path or DB_PATH),
                out_file=backup_file,
                password=pwd,
                actor=args.actor,
            )
            print(f"تم إنشاء نسخة احتياطية قبل الاستيراد: {meta['backup_file']}")
            print(f"SHA256(plain): {meta['sha256_plain']}")

        imported = 0
        for table, rows in data.items():
            if not _table_exists(conn, table):
                continue
            if not isinstance(rows, list):
                continue

            _check_table_mutable(table, root_mode=args.root)
            pk_cols = _pk_columns(conn, table)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                before = None
                pk = None
                if pk_cols:
                    pk = {k: row.get(k) for k in pk_cols}
                    existing = _select_rows(conn, table, where=pk, limit=1)
                    if existing:
                        before = existing[0]

                if args.mode == "insert":
                    _insert_row(conn, table, row)
                    _audit(conn, batch_id, "import_insert", table, pk, before, row, actor)
                else:
                    _upsert_row(conn, table, row)
                    op = "import_upsert_update" if before else "import_upsert_insert"
                    _audit(conn, batch_id, op, table, pk, before, row, actor)
                imported += 1

        conn.commit()
        print(f"تم الاستيراد بنجاح. records={imported} | batch_id={batch_id}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"فشل الاستيراد: {exc}")
        return 1
    finally:
        conn.close()


def _diff_keys(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    keys = set(before.keys()) | set(after.keys())
    changed = [k for k in keys if before.get(k) != after.get(k)]
    return sorted(changed)


def _build_import_diff(
    conn: sqlite3.Connection,
    data: dict[str, Any],
    mode: str,
    sample_limit: int,
) -> dict[str, Any]:
    summary: list[dict[str, Any]] = []
    samples: dict[str, list[dict[str, Any]]] = {}

    for table, rows in data.items():
        if not _table_exists(conn, table) or not isinstance(rows, list):
            continue

        pk_cols = _pk_columns(conn, table)
        stats = {
            "table": table,
            "incoming_rows": 0,
            "would_insert": 0,
            "would_update": 0,
            "unchanged": 0,
            "would_conflict": 0,
            "invalid": 0,
        }
        table_samples: list[dict[str, Any]] = []

        for row in rows:
            if not isinstance(row, dict):
                stats["invalid"] += 1
                continue
            stats["incoming_rows"] += 1

            before = None
            pk = None
            if pk_cols and all(col in row for col in pk_cols):
                pk = {k: row.get(k) for k in pk_cols}
                exists = _select_rows(conn, table, where=pk, limit=1)
                if exists:
                    before = exists[0]

            if mode == "insert":
                if before is not None:
                    stats["would_conflict"] += 1
                else:
                    stats["would_insert"] += 1
                continue

            if before is None:
                stats["would_insert"] += 1
                if len(table_samples) < sample_limit:
                    table_samples.append({"type": "insert", "pk": pk, "after": row})
                continue

            changed_fields = _diff_keys(before, row)
            if changed_fields:
                stats["would_update"] += 1
                if len(table_samples) < sample_limit:
                    table_samples.append(
                        {
                            "type": "update",
                            "pk": pk,
                            "changed_fields": changed_fields,
                            "before": before,
                            "after": row,
                        }
                    )
            else:
                stats["unchanged"] += 1

        summary.append(stats)
        if table_samples:
            samples[table] = table_samples

    return {
        "generated_at": _utc_now(),
        "mode": mode,
        "summary": summary,
        "samples": samples,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="أداة إدارة موحدة للمنصة: CRUD + استرجاع + إدارة نشاط/خدمات/إعدادات"
    )
    parser.add_argument("--db-path", default=None, help="مسار قاعدة البيانات (اختياري)")
    parser.add_argument("--actor", default="_platform_ops.py", help="اسم المنفذ في سجل التدقيق")
    parser.add_argument("--root", action="store_true", help="وضع صلاحية كاملة بدون قيود حماية")

    sub = parser.add_subparsers(dest="command", required=True)

    p_tables = sub.add_parser("tables", help="عرض كل الجداول")
    p_tables.set_defaults(func=cmd_tables)

    p_desc = sub.add_parser("describe", help="عرض أعمدة جدول")
    p_desc.add_argument("--table", required=True)
    p_desc.set_defaults(func=cmd_describe)

    p_select = sub.add_parser("select", help="استعلام صفوف")
    p_select.add_argument("--table", required=True)
    p_select.add_argument("--where", default="{}", help="JSON filters")
    p_select.add_argument("--limit", type=int, default=100)
    p_select.set_defaults(func=cmd_select)

    p_overview = sub.add_parser("overview", help="عرض شامل للنشاط والعمليات")
    p_overview.set_defaults(func=cmd_overview)

    p_backup = sub.add_parser("backup-create", help="نسخة احتياطية مشفرة مع SHA256")
    p_backup.add_argument("--output", default=None)
    p_backup.add_argument("--password", default=None, help="كلمة مرور التشفير")
    p_backup.set_defaults(func=cmd_backup_create)

    p_insert = sub.add_parser("insert", help="إضافة صف")
    p_insert.add_argument("--table", required=True)
    p_insert.add_argument("--payload", required=True, help="JSON object")
    p_insert.add_argument("--batch-id", default=None)
    p_insert.add_argument("--apply", action="store_true")
    p_insert.set_defaults(func=cmd_insert)

    p_update = sub.add_parser("update", help="تحديث صفوف")
    p_update.add_argument("--table", required=True)
    p_update.add_argument("--set", dest="set_values", required=True, help="JSON object")
    p_update.add_argument("--where", required=True, help="JSON object")
    p_update.add_argument("--limit", type=int, default=200)
    p_update.add_argument("--batch-id", default=None)
    p_update.add_argument("--apply", action="store_true")
    p_update.set_defaults(func=cmd_update)

    p_delete = sub.add_parser("delete", help="حذف صفوف")
    p_delete.add_argument("--table", required=True)
    p_delete.add_argument("--where", required=True, help="JSON object")
    p_delete.add_argument("--limit", type=int, default=200)
    p_delete.add_argument("--batch-id", default=None)
    p_delete.add_argument("--apply", action="store_true")
    p_delete.set_defaults(func=cmd_delete)

    p_activity = sub.add_parser("set-activity", help="تعديل نشاط منشأة")
    p_activity.add_argument("--business-id", type=int, required=True)
    p_activity.add_argument("--industry-type", required=True)
    p_activity.add_argument("--batch-id", default=None)
    p_activity.add_argument("--apply", action="store_true")
    p_activity.set_defaults(func=cmd_set_activity)

    p_service = sub.add_parser("add-service", help="إضافة خدمة كمنتج خدمة")
    p_service.add_argument("--business-id", type=int, default=None)
    p_service.add_argument("--all-businesses", action="store_true")
    p_service.add_argument("--name", required=True)
    p_service.add_argument("--price", type=float, required=True)
    p_service.add_argument("--category", default="خدمات مخصصة")
    p_service.add_argument("--show-in-pos", action="store_true")
    p_service.add_argument("--allow-duplicate", action="store_true")
    p_service.add_argument("--batch-id", default=None)
    p_service.add_argument("--apply", action="store_true")
    p_service.set_defaults(func=cmd_add_service)

    p_setting = sub.add_parser("upsert-setting", help="إضافة/تحديث إعداد")
    p_setting.add_argument("--business-id", type=int, default=None)
    p_setting.add_argument("--all-businesses", action="store_true")
    p_setting.add_argument("--key", required=True)
    p_setting.add_argument("--value", required=True)
    p_setting.add_argument("--batch-id", default=None)
    p_setting.add_argument("--apply", action="store_true")
    p_setting.set_defaults(func=cmd_upsert_setting)

    p_rb = sub.add_parser("rollback", help="استرجاع دفعة كاملة من سجل التدقيق")
    p_rb.add_argument("--batch-id", required=True)
    p_rb.add_argument("--new-batch-id", default=None)
    p_rb.add_argument("--apply", action="store_true")
    p_rb.set_defaults(func=cmd_rollback)

    p_export = sub.add_parser("export", help="تصدير بيانات JSON")
    p_export.add_argument("--tables", default=None, help="قائمة جداول مفصولة بفاصلة")
    p_export.add_argument("--where", default="{}", help="JSON filters")
    p_export.add_argument("--business-id", type=int, default=None)
    p_export.add_argument("--limit", type=int, default=50000)
    p_export.add_argument("--output", required=True)
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="استيراد بيانات JSON")
    p_import.add_argument("--input", required=True)
    p_import.add_argument("--mode", choices=["upsert", "insert"], default="upsert")
    p_import.add_argument("--diff-report", default=None, help="مسار حفظ تقرير الفروقات")
    p_import.add_argument("--diff-sample-limit", type=int, default=50)
    p_import.add_argument("--pre-backup", action="store_true", help="إنشاء نسخة احتياطية مشفرة قبل الاستيراد")
    p_import.add_argument("--backup-password", default=None, help="كلمة مرور نسخة ما قبل الاستيراد")
    p_import.add_argument("--backup-output", default=None, help="ملف النسخة قبل الاستيراد")
    p_import.add_argument("--batch-id", default=None)
    p_import.add_argument("--apply", action="store_true")
    p_import.set_defaults(func=cmd_import)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except json.JSONDecodeError as exc:
        print(f"JSON غير صالح: {exc}")
        return 1
    except Exception as exc:
        print(f"خطأ غير متوقع: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
