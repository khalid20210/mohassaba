#!/usr/bin/env python3
import sqlite3
import sys

try:
    db = sqlite3.connect('database/accounting_dev.db')
    db.row_factory = sqlite3.Row
    c = db.cursor()
    
    print("=" * 80)
    print("USERS TABLE SCHEMA")
    print("=" * 80)
    schema = c.execute("PRAGMA table_info(users)").fetchall()
    for col in schema:
        print(col)
    
    print("\n" + "=" * 80)
    print("USERS IN DATABASE")
    print("=" * 80)
    users = c.execute('SELECT * FROM users LIMIT 20').fetchall()
    if users:
        for u in users:
            print(dict(u))
    else:
        print("No users found!")
    
    print("\n" + "=" * 80)
    print("ROLES")
    print("=" * 80)
    roles = c.execute('SELECT * FROM roles').fetchall()
    if roles:
        for r in roles:
            print(dict(r))
    else:
        print("No roles found!")
    
    print("\n" + "=" * 80)
    print("BUSINESSES (OWNERS)")
    print("=" * 80)
    biz = c.execute('SELECT * FROM businesses LIMIT 10').fetchall()
    if biz:
        for b in biz:
            print(dict(b))
    else:
        print("No businesses found!")
    
    db.close()
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
