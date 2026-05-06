import sqlite3
import json

conn = sqlite3.connect('accounting_dev.db')
c = conn.cursor()

tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

result = {
    'total_tables': len(tables),
    'tables': [t[0] for t in tables],
    'product_related': []
}

for table in tables:
    name = table[0]
    if 'product' in name.lower() or 'item' in name.lower() or 'stock' in name.lower():
        cols = c.execute(f"PRAGMA table_info({name})").fetchall()
        result['product_related'].append({
            'table_name': name,
            'columns': [col[1] for col in cols]
        })

with open('_tables_info.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("OK")
conn.close()
