import sys

sys.path.insert(0, '.')

from app import create_app
from security_status_report import report_status


def main() -> None:
    report_status("فحص المنتجات والوحدات", "جاري التنفيذ...", "بدء تحميل التطبيق")
    app = create_app()

    with app.app_context():
        from modules.db_adapter import get_db_adapter

        db = get_db_adapter()
        product_columns = {
            row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()
        }

        report_status("فحص الجداول", "جاري التنفيذ...", "قراءة جداول sqlite_master")
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        table_names = [t[0] for t in tables]
        print('الجداول:', table_names)
        report_status("فحص الجداول", "نجاح ✅", f"تم العثور على {len(table_names)} جدول")

        report_status("فحص عدد المنتجات", "جاري التنفيذ...", "التحقق من جدول products")
        products_row = db.execute('SELECT COUNT(*) FROM products').fetchone()
        products_count = products_row[0] if products_row else 0
        print('إجمالي المنتجات:', products_count if products_row else 'لا يوجد')
        report_status("فحص عدد المنتجات", "نجاح ✅", f"إجمالي المنتجات = {products_count}")

        report_status("فحص توزيع الأنشطة", "جاري التنفيذ...", "تجميع المنتجات حسب activity_type")
        activity_rows = []
        group_column = None
        for candidate in ("activity_type", "product_type", "category_name"):
            if candidate in product_columns:
                group_column = candidate
                break
        if group_column:
            activity_rows = db.execute(
                f'SELECT {group_column}, COUNT(*) FROM products GROUP BY {group_column}'
            ).fetchall()
            print('توزيع الأنشطة:')
            for row in activity_rows:
                print(' ', row[0] or 'NULL', ':', row[1])
            report_status("فحص توزيع الأنشطة", "نجاح ✅", f"الحقل المستخدم = {group_column} | عدد القيم = {len(activity_rows)}")
        else:
            print('توزيع الأنشطة: لا يوجد حقل تصنيف مناسب في جدول products')
            report_status("فحص توزيع الأنشطة", "تجاوز ⚠️", "لا يوجد activity_type ولا product_type ولا category_name")

        report_status("فحص الوحدات المستخدمة", "جاري التنفيذ...", "قراءة الوحدات المميزة من المنتجات")
        unit_values = []
        unit_column = None
        for candidate in ("unit", "unit_name", "measurement_unit"):
            if candidate in product_columns:
                unit_column = candidate
                break
        if unit_column:
            units_rows = db.execute(f'SELECT DISTINCT {unit_column} FROM products').fetchall()
            unit_values = [x[0] for x in units_rows]
            print('الوحدات المستخدمة:', unit_values)
            report_status("فحص الوحدات المستخدمة", "نجاح ✅", f"الحقل المستخدم = {unit_column} | عدد الوحدات = {len(unit_values)}")
        else:
            print('الوحدات المستخدمة: لا يوجد عمود وحدة مباشر في جدول products')
            report_status("فحص الوحدات المستخدمة", "تجاوز ⚠️", "لا يوجد unit ولا unit_name ولا measurement_unit")

        report_status("فحص إعدادات الوحدات والبلد", "جاري التنفيذ...", "قراءة business_settings")
        settings_rows = []
        if "business_settings" in table_names:
            settings_rows = db.execute(
                "SELECT key, value FROM business_settings WHERE key LIKE '%unit%' OR key LIKE '%country%' OR key LIKE '%market%'"
            ).fetchall()
            print('إعدادات الوحدات/البلد:')
            for row in settings_rows:
                print(' ', row[0], ':', row[1])
            report_status("فحص إعدادات الوحدات والبلد", "نجاح ✅", f"عدد الإعدادات = {len(settings_rows)}")
        elif "settings" in table_names:
            settings_rows = db.execute(
                "SELECT key, value FROM settings WHERE key LIKE '%unit%' OR key LIKE '%country%' OR key LIKE '%market%'"
            ).fetchall()
            print('إعدادات الوحدات/البلد:')
            for row in settings_rows:
                print(' ', row[0], ':', row[1])
            report_status("فحص إعدادات الوحدات والبلد", "نجاح ✅", f"تمت القراءة من settings | عدد الإعدادات = {len(settings_rows)}")
        else:
            print('إعدادات الوحدات/البلد: لا يوجد business_settings ولا settings')
            report_status("فحص إعدادات الوحدات والبلد", "تجاوز ⚠️", "لا يوجد business_settings ولا settings")

        report_status("عرض عينة المنتجات", "جاري التنفيذ...", "قراءة أول 20 منتج")
        sample_unit_expr = unit_column if unit_column else "NULL"
        sample_group_expr = group_column if group_column else "NULL"
        sample_rows = db.execute(
            f'SELECT id, name, {sample_unit_expr}, {sample_group_expr} FROM products LIMIT 20'
        ).fetchall()
        print('\nعينة المنتجات:')
        for row in sample_rows:
            print(f'  [{row[0]}] {row[1]} | وحدة={row[2]} | نشاط={row[3]}')
        report_status("عرض عينة المنتجات", "نجاح ✅", f"تم عرض {len(sample_rows)} سجل")

        report_status("فحص جداول الوحدات", "جاري التنفيذ...", "البحث عن جداول تحتوي كلمة unit")
        unit_tables = [table for table in table_names if 'unit' in table.lower()]
        print('\nجداول الوحدات:', unit_tables)
        report_status("فحص جداول الوحدات", "نجاح ✅", f"الجداول: {', '.join(unit_tables) if unit_tables else 'لا يوجد'}")

    report_status("فحص المنتجات والوحدات", "اكتمل ✅", "تم إنهاء جميع خطوات الفحص بنجاح")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        report_status("فحص المنتجات والوحدات", "فشل ❌", str(exc))
        raise
