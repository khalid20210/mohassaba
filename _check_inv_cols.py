#!/usr/bin/env python
import sqlite3
conn = sqlite3.connect("database/accounting_dev.db")
cur = conn.cursor()
cur.execute("PRAGMA table_info(invoices)")
for col in cur.fetchall():
    print(f"{col[1]} ({col[2]})")
