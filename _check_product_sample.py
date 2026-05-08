import sqlite3

conn = sqlite3.connect("database/central_saas.db")
c = conn.cursor()

# عرض أول منتج
sample = c.execute("SELECT * FROM products_bulk LIMIT 1").fetchone()
if sample:
    print("أول منتج:")
    cols = c.execute("PRAGMA table_info(products_bulk)").fetchall()
    for i, col in enumerate(cols):
        col_name = col[1]
        value = sample[i]
        print(f"  {col_name}: {value}")
else:
    print("لا توجد منتجات!")

conn.close()
