import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = "database/central_saas.db"
OUT_PATH = "تقرير_الانشطة_الرئيسية_والفرعية.md"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT code, name_ar, category, sub_category
        FROM activities_definitions
        WHERE is_active = 1
        ORDER BY category, sub_category, name_ar
        """
    ).fetchall()

    conn.close()

    by_category = defaultdict(list)
    for r in rows:
        category = (r["category"] or "other").strip()
        by_category[category].append(r)

    lines = []
    lines.append("# تقرير أسماء الأنشطة الرئيسية والأنشطة الفرعية")
    lines.append("")
    lines.append(f"إجمالي الأنشطة النشطة: {len(rows)}")
    lines.append(f"عدد الأنشطة الرئيسية: {len(by_category)}")
    lines.append("")

    for category in sorted(by_category.keys()):
        category_rows = by_category[category]
        lines.append(f"## النشاط الرئيسي: {category} ({len(category_rows)})")

        by_sub_category = defaultdict(list)
        for r in category_rows:
            sub_cat = (r["sub_category"] or "غير مصنف").strip()
            by_sub_category[sub_cat].append(r)

        for sub_cat in sorted(by_sub_category.keys()):
            sub_rows = by_sub_category[sub_cat]
            lines.append(f"### مجموعة فرعية: {sub_cat} ({len(sub_rows)})")
            for item in sub_rows:
                lines.append(f"- {item['name_ar']} | الكود: {item['code']}")
            lines.append("")

    Path(OUT_PATH).write_text("\n".join(lines), encoding="utf-8")
    print(f"تم إنشاء التقرير: {OUT_PATH}")


if __name__ == "__main__":
    main()
