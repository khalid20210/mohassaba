"""
modules/blueprints/hr/routes.py
الموارد البشرية الشاملة — لجميع الأنشطة (196 نشاط)
-----------------------------------------------------------
الخدمات:
1. إدارة الموظفين
2. الرواتب والأجور (Payroll)
3. الحضور والغياب
4. الإجازات والسلف
5. التقييم والكفاءات
6. مكافآت نهاية الخدمة
7. الأصول الثابتة وإهلاكها
8. الموازنة التقديرية
"""
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, flash, g, jsonify, url_for
from functools import wraps
import json

bp = Blueprint("hr", __name__, url_prefix="/hr")


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.user or not g.business:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def _db():
    from modules.extensions import get_db
    return get_db()


def _biz():
    return g.business["id"]


# ══════════════════════════════════════════════════════════
# DASHBOARD HR
# ══════════════════════════════════════════════════════════
@bp.route("/")
@_require_auth
def dashboard():
    db = _db()
    biz = _biz()
    now = datetime.now()
    month_start = now.strftime("%Y-%m-01")

    # إحصائيات سريعة
    stats = {}
    try:
        stats["total_employees"] = db.execute(
            "SELECT COUNT(*) FROM employees WHERE business_id=? AND status='active'", (biz,)
        ).fetchone()[0]
    except Exception:
        stats["total_employees"] = 0

    try:
        stats["total_salary"] = db.execute(
            "SELECT COALESCE(SUM(base_salary),0) FROM employees WHERE business_id=? AND status='active'", (biz,)
        ).fetchone()[0]
    except Exception:
        stats["total_salary"] = 0

    try:
        stats["on_leave"] = db.execute(
            """SELECT COUNT(*) FROM hr_leaves
               WHERE business_id=? AND status='approved'
               AND start_date<=? AND end_date>=?""",
            (biz, now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"))
        ).fetchone()[0]
    except Exception:
        stats["on_leave"] = 0

    try:
        stats["pending_salary"] = db.execute(
            """SELECT COUNT(*) FROM hr_payroll
               WHERE business_id=? AND period_month=? AND status='pending'""",
            (biz, now.strftime("%Y-%m"))
        ).fetchone()[0]
    except Exception:
        stats["pending_salary"] = 0

    try:
        stats["total_advances"] = db.execute(
            """SELECT COALESCE(SUM(amount),0) FROM hr_advances
               WHERE business_id=? AND status='active'""", (biz,)
        ).fetchone()[0]
    except Exception:
        stats["total_advances"] = 0

    # آخر الموظفين
    try:
        recent_employees = db.execute(
            """SELECT * FROM employees WHERE business_id=?
               ORDER BY created_at DESC LIMIT 5""", (biz,)
        ).fetchall()
        recent_employees = [dict(r) for r in recent_employees]
    except Exception:
        recent_employees = []

    # رواتب هذا الشهر
    try:
        this_month_payroll = db.execute(
            """SELECT e.full_name, p.net_salary, p.status, p.payment_date
               FROM hr_payroll p
               LEFT JOIN employees e ON e.id=p.employee_id
               WHERE p.business_id=? AND p.period_month=?
               ORDER BY p.created_at DESC LIMIT 10""",
            (biz, now.strftime("%Y-%m"))
        ).fetchall()
        this_month_payroll = [dict(r) for r in this_month_payroll]
    except Exception:
        this_month_payroll = []

    return render_template("hr/dashboard.html",
        stats=stats,
        recent_employees=recent_employees,
        this_month_payroll=this_month_payroll,
        current_month=now.strftime("%Y-%m")
    )


# ══════════════════════════════════════════════════════════
# EMPLOYEES — إدارة الموظفين
# ══════════════════════════════════════════════════════════
@bp.route("/employees")
@_require_auth
def employees():
    db = _db(); biz = _biz()
    q = request.args.get("q", "").strip()
    dept = request.args.get("dept", "").strip()
    status_f = request.args.get("status", "active").strip()

    sql = "SELECT * FROM employees WHERE business_id=?"
    params = [biz]
    if q:
        sql += " AND (full_name LIKE ? OR national_id LIKE ? OR phone LIKE ? OR job_title LIKE ?)"
        s = f"%{q}%"; params += [s, s, s, s]
    if dept:
        sql += " AND department=?"; params.append(dept)
    if status_f:
        sql += " AND status=?"; params.append(status_f)
    sql += " ORDER BY created_at DESC"

    try:
        emps = [dict(r) for r in db.execute(sql, params).fetchall()]
    except Exception:
        emps = []

    # الأقسام
    try:
        depts = [r[0] for r in db.execute(
            "SELECT DISTINCT department FROM employees WHERE business_id=? AND department IS NOT NULL", (biz,)
        ).fetchall()]
    except Exception:
        depts = []

    return render_template("hr/employees.html",
        employees=emps, departments=depts,
        search=q, dept_filter=dept, status_filter=status_f
    )


@bp.route("/employees/new", methods=["POST"])
@_require_auth
def add_employee():
    db = _db(); biz = _biz()
    f = request.form
    try:
        db.execute("""
            INSERT INTO employees (business_id, full_name, national_id, phone, email,
              job_title, department, hire_date, base_salary, allowances, status,
              bank_account, bank_name, nationality, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (biz,
            f.get("full_name","").strip(),
            f.get("national_id","").strip(),
            f.get("phone","").strip(),
            f.get("email","").strip(),
            f.get("job_title","").strip(),
            f.get("department","").strip(),
            f.get("hire_date") or None,
            float(f.get("base_salary") or 0),
            float(f.get("allowances") or 0),
            f.get("status","active"),
            f.get("bank_account","").strip(),
            f.get("bank_name","").strip(),
            f.get("nationality","سعودي").strip(),
            datetime.now().isoformat()
        ))
        flash("تم إضافة الموظف بنجاح ✓", "success")
    except Exception as e:
        flash(f"خطأ في إضافة الموظف: {e}", "error")
    return redirect(url_for("hr.employees"))


@bp.route("/employees/<int:emp_id>")
@_require_auth
def employee_detail(emp_id):
    db = _db(); biz = _biz()
    try:
        emp = dict(db.execute(
            "SELECT * FROM employees WHERE id=? AND business_id=?", (emp_id, biz)
        ).fetchone())
    except Exception:
        flash("الموظف غير موجود", "error")
        return redirect(url_for("hr.employees"))

    # سجل الرواتب
    try:
        payroll_history = [dict(r) for r in db.execute(
            "SELECT * FROM hr_payroll WHERE employee_id=? AND business_id=? ORDER BY period_month DESC LIMIT 24",
            (emp_id, biz)
        ).fetchall()]
    except Exception:
        payroll_history = []

    # الإجازات
    try:
        leaves = [dict(r) for r in db.execute(
            "SELECT * FROM hr_leaves WHERE employee_id=? AND business_id=? ORDER BY created_at DESC LIMIT 10",
            (emp_id, biz)
        ).fetchall()]
    except Exception:
        leaves = []

    # السلف
    try:
        advances = [dict(r) for r in db.execute(
            "SELECT * FROM hr_advances WHERE employee_id=? AND business_id=? ORDER BY created_at DESC LIMIT 10",
            (emp_id, biz)
        ).fetchall()]
    except Exception:
        advances = []

    return render_template("hr/employee_detail.html",
        employee=emp,
        payroll_history=payroll_history,
        leaves=leaves,
        advances=advances
    )


@bp.route("/employees/<int:emp_id>/edit", methods=["POST"])
@_require_auth
def edit_employee(emp_id):
    db = _db(); biz = _biz()
    f = request.form
    try:
        db.execute("""
            UPDATE employees SET
              full_name=?, national_id=?, phone=?, email=?,
              job_title=?, department=?, base_salary=?, allowances=?,
              status=?, bank_account=?, bank_name=?, nationality=?
            WHERE id=? AND business_id=?
        """, (
            f.get("full_name","").strip(),
            f.get("national_id","").strip(),
            f.get("phone","").strip(),
            f.get("email","").strip(),
            f.get("job_title","").strip(),
            f.get("department","").strip(),
            float(f.get("base_salary") or 0),
            float(f.get("allowances") or 0),
            f.get("status","active"),
            f.get("bank_account","").strip(),
            f.get("bank_name","").strip(),
            f.get("nationality","").strip(),
            emp_id, biz
        ))
        flash("تم تعديل بيانات الموظف ✓", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.employee_detail", emp_id=emp_id))


# ══════════════════════════════════════════════════════════
# PAYROLL — الرواتب والأجور
# ══════════════════════════════════════════════════════════
@bp.route("/payroll")
@_require_auth
def payroll():
    db = _db(); biz = _biz()
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))

    try:
        records = [dict(r) for r in db.execute("""
            SELECT p.*, e.full_name, e.job_title, e.department
            FROM hr_payroll p
            LEFT JOIN employees e ON e.id=p.employee_id
            WHERE p.business_id=? AND p.period_month=?
            ORDER BY e.full_name
        """, (biz, month)).fetchall()]
    except Exception:
        records = []

    try:
        total_net = db.execute(
            "SELECT COALESCE(SUM(net_salary),0) FROM hr_payroll WHERE business_id=? AND period_month=?",
            (biz, month)
        ).fetchone()[0]
    except Exception:
        total_net = 0

    # موظفون بدون راتب هذا الشهر
    try:
        without_payroll = [dict(r) for r in db.execute("""
            SELECT * FROM employees WHERE business_id=? AND status='active'
            AND id NOT IN (
                SELECT employee_id FROM hr_payroll
                WHERE business_id=? AND period_month=?
            )
        """, (biz, biz, month)).fetchall()]
    except Exception:
        without_payroll = []

    return render_template("hr/payroll.html",
        records=records, month=month,
        total_net=total_net,
        without_payroll=without_payroll
    )


@bp.route("/payroll/run", methods=["POST"])
@_require_auth
def run_payroll():
    """تشغيل الرواتب لجميع الموظفين النشطين"""
    db = _db(); biz = _biz()
    month = request.form.get("month", datetime.now().strftime("%Y-%m"))

    try:
        employees = db.execute(
            "SELECT * FROM employees WHERE business_id=? AND status='active'", (biz,)
        ).fetchall()

        added = 0
        for emp in employees:
            # تحقق من عدم وجود راتب لهذا الشهر مسبقاً
            exists = db.execute(
                "SELECT id FROM hr_payroll WHERE employee_id=? AND period_month=? AND business_id=?",
                (emp["id"], month, biz)
            ).fetchone()
            if exists:
                continue

            base = float(emp["base_salary"] or 0)
            allowances = float(emp["allowances"] or 0)
            # استقطاع السلف
            advance_deduction = db.execute(
                """SELECT COALESCE(SUM(monthly_deduction),0) FROM hr_advances
                   WHERE employee_id=? AND business_id=? AND status='active'""",
                (emp["id"], biz)
            ).fetchone()[0] or 0

            gross = base + allowances
            social_insurance = round(gross * 0.10, 2)  # 10% تأمينات
            net = round(gross - social_insurance - advance_deduction, 2)

            db.execute("""
                INSERT INTO hr_payroll
                (business_id, employee_id, period_month, base_salary, allowances,
                 advance_deduction, social_insurance, gross_salary, net_salary,
                 status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,'pending',?)
            """, (biz, emp["id"], month, base, allowances,
                  advance_deduction, social_insurance, gross, net,
                  datetime.now().isoformat()))
            added += 1

        flash(f"✓ تم إعداد رواتب {added} موظف لشهر {month}", "success")
    except Exception as e:
        flash(f"خطأ في تشغيل الرواتب: {e}", "error")
    return redirect(url_for("hr.payroll", month=month))


@bp.route("/payroll/<int:payroll_id>/pay", methods=["POST"])
@_require_auth
def pay_salary(payroll_id):
    db = _db(); biz = _biz()
    try:
        db.execute("""
            UPDATE hr_payroll SET status='paid', payment_date=?
            WHERE id=? AND business_id=?
        """, (datetime.now().strftime("%Y-%m-%d"), payroll_id, biz))
        flash("✓ تم تسجيل صرف الراتب", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    back = request.form.get("back_to", url_for("hr.payroll"))
    return redirect(back)


# ══════════════════════════════════════════════════════════
# LEAVES — الإجازات
# ══════════════════════════════════════════════════════════
@bp.route("/leaves")
@_require_auth
def leaves():
    db = _db(); biz = _biz()
    try:
        records = [dict(r) for r in db.execute("""
            SELECT l.*, e.full_name, e.department
            FROM hr_leaves l
            LEFT JOIN employees e ON e.id=l.employee_id
            WHERE l.business_id=?
            ORDER BY l.created_at DESC LIMIT 100
        """, (biz,)).fetchall()]
    except Exception:
        records = []

    try:
        employees = [dict(r) for r in db.execute(
            "SELECT id, full_name FROM employees WHERE business_id=? AND status='active'", (biz,)
        ).fetchall()]
    except Exception:
        employees = []

    return render_template("hr/leaves.html", leaves=records, employees=employees)


@bp.route("/leaves/new", methods=["POST"])
@_require_auth
def add_leave():
    db = _db(); biz = _biz()
    f = request.form
    try:
        db.execute("""
            INSERT INTO hr_leaves
            (business_id, employee_id, leave_type, start_date, end_date, reason, status, created_at)
            VALUES (?,?,?,?,?,?,'pending',?)
        """, (biz,
            int(f.get("employee_id")),
            f.get("leave_type","سنوية"),
            f.get("start_date"),
            f.get("end_date"),
            f.get("reason","").strip(),
            datetime.now().isoformat()
        ))
        flash("✓ تم تقديم طلب الإجازة", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.leaves"))


@bp.route("/leaves/<int:leave_id>/approve", methods=["POST"])
@_require_auth
def approve_leave(leave_id):
    db = _db(); biz = _biz()
    action = request.form.get("action", "approve")
    status = "approved" if action == "approve" else "rejected"
    try:
        db.execute(
            "UPDATE hr_leaves SET status=? WHERE id=? AND business_id=?",
            (status, leave_id, biz)
        )
        flash(f"✓ تم {'الموافقة' if status=='approved' else 'رفض'} الإجازة", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.leaves"))


# ══════════════════════════════════════════════════════════
# ADVANCES — السلف
# ══════════════════════════════════════════════════════════
@bp.route("/advances")
@_require_auth
def advances():
    db = _db(); biz = _biz()
    try:
        records = [dict(r) for r in db.execute("""
            SELECT a.*, e.full_name, e.department
            FROM hr_advances a
            LEFT JOIN employees e ON e.id=a.employee_id
            WHERE a.business_id=?
            ORDER BY a.created_at DESC LIMIT 100
        """, (biz,)).fetchall()]
    except Exception:
        records = []

    try:
        employees = [dict(r) for r in db.execute(
            "SELECT id, full_name FROM employees WHERE business_id=? AND status='active'", (biz,)
        ).fetchall()]
    except Exception:
        employees = []

    total_active = sum(r["amount"] for r in records if r.get("status") == "active")
    return render_template("hr/advances.html",
        advances=records, employees=employees, total_active=total_active)


@bp.route("/advances/new", methods=["POST"])
@_require_auth
def add_advance():
    db = _db(); biz = _biz()
    f = request.form
    try:
        amount = float(f.get("amount") or 0)
        months = int(f.get("months") or 1)
        monthly = round(amount / months, 2) if months > 0 else amount
        db.execute("""
            INSERT INTO hr_advances
            (business_id, employee_id, amount, monthly_deduction,
             reason, status, advance_date, created_at)
            VALUES (?,?,?,?,?,'active',?,?)
        """, (biz,
            int(f.get("employee_id")),
            amount, monthly,
            f.get("reason","").strip(),
            f.get("advance_date") or date.today().isoformat(),
            datetime.now().isoformat()
        ))
        flash("✓ تم تسجيل السلفة", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.advances"))


@bp.route("/advances/<int:adv_id>/settle", methods=["POST"])
@_require_auth
def settle_advance(adv_id):
    db = _db(); biz = _biz()
    try:
        db.execute(
            "UPDATE hr_advances SET status='settled' WHERE id=? AND business_id=?",
            (adv_id, biz)
        )
        flash("✓ تم تسوية السلفة", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.advances"))


# ══════════════════════════════════════════════════════════
# ASSETS — الأصول الثابتة
# ══════════════════════════════════════════════════════════
@bp.route("/assets")
@_require_auth
def assets():
    db = _db(); biz = _biz()
    try:
        records = [dict(r) for r in db.execute(
            "SELECT * FROM hr_assets WHERE business_id=? ORDER BY created_at DESC",
            (biz,)
        ).fetchall()]
    except Exception:
        records = []

    total_value = sum(r.get("current_value", 0) or 0 for r in records)
    total_depreciation = sum(r.get("accumulated_depreciation", 0) or 0 for r in records)

    return render_template("hr/assets.html",
        assets=records,
        total_value=total_value,
        total_depreciation=total_depreciation
    )


@bp.route("/assets/new", methods=["POST"])
@_require_auth
def add_asset():
    db = _db(); biz = _biz()
    f = request.form
    try:
        cost = float(f.get("cost") or 0)
        useful_life = int(f.get("useful_life") or 5)
        annual_dep = round(cost / useful_life, 2) if useful_life > 0 else 0
        db.execute("""
            INSERT INTO hr_assets
            (business_id, asset_name, asset_type, serial_number,
             purchase_date, cost, useful_life_years, annual_depreciation,
             accumulated_depreciation, current_value, location, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?)
        """, (biz,
            f.get("asset_name","").strip(),
            f.get("asset_type","أثاث ومعدات"),
            f.get("serial_number","").strip(),
            f.get("purchase_date") or date.today().isoformat(),
            cost, useful_life, annual_dep, cost,
            f.get("location","").strip(),
            f.get("status","نشط"),
            datetime.now().isoformat()
        ))
        flash("✓ تم إضافة الأصل الثابت", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.assets"))


@bp.route("/assets/<int:asset_id>/depreciate", methods=["POST"])
@_require_auth
def depreciate_asset(asset_id):
    """تسجيل الإهلاك السنوي"""
    db = _db(); biz = _biz()
    try:
        asset = dict(db.execute(
            "SELECT * FROM hr_assets WHERE id=? AND business_id=?", (asset_id, biz)
        ).fetchone())
        new_acc = (asset.get("accumulated_depreciation") or 0) + (asset.get("annual_depreciation") or 0)
        new_val = max(0, (asset.get("cost") or 0) - new_acc)
        db.execute("""
            UPDATE hr_assets SET accumulated_depreciation=?, current_value=?
            WHERE id=? AND business_id=?
        """, (new_acc, new_val, asset_id, biz))
        flash(f"✓ تم تسجيل الإهلاك — القيمة الجديدة: {new_val:,.2f}", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.assets"))


# ══════════════════════════════════════════════════════════
# BUDGET — الموازنة التقديرية
# ══════════════════════════════════════════════════════════
@bp.route("/budget")
@_require_auth
def budget():
    db = _db(); biz = _biz()
    year = int(request.args.get("year", datetime.now().year))

    try:
        records = [dict(r) for r in db.execute(
            "SELECT * FROM hr_budget WHERE business_id=? AND year=? ORDER BY category, month",
            (biz, year)
        ).fetchall()]
    except Exception:
        records = []

    # مقارنة الفعلي بالمخطط
    try:
        actual_expenses = db.execute("""
            SELECT COALESCE(SUM(amount),0) FROM expenses
            WHERE business_id=? AND strftime('%Y', date)=?
        """, (biz, str(year))).fetchone()[0]
    except Exception:
        actual_expenses = 0

    total_budget = sum(r.get("amount", 0) or 0 for r in records)
    variance = total_budget - actual_expenses

    return render_template("hr/budget.html",
        budget_items=records, year=year,
        total_budget=total_budget,
        actual_expenses=actual_expenses,
        variance=variance
    )


@bp.route("/budget/new", methods=["POST"])
@_require_auth
def add_budget():
    db = _db(); biz = _biz()
    f = request.form
    try:
        db.execute("""
            INSERT INTO hr_budget (business_id, year, month, category, description, amount, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (biz,
            int(f.get("year", datetime.now().year)),
            int(f.get("month", 0)),
            f.get("category","").strip(),
            f.get("description","").strip(),
            float(f.get("amount") or 0),
            datetime.now().isoformat()
        ))
        flash("✓ تم إضافة بند الموازنة", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")
    return redirect(url_for("hr.budget"))


# ══════════════════════════════════════════════════════════
# REPORTS HR — تقارير الموارد البشرية
# ══════════════════════════════════════════════════════════
@bp.route("/reports")
@_require_auth
def reports():
    db = _db(); biz = _biz()
    now = datetime.now()

    stats = {}
    try:
        stats["total"] = db.execute(
            "SELECT COUNT(*) FROM employees WHERE business_id=? AND status='active'", (biz,)
        ).fetchone()[0]
        stats["total_salary"] = db.execute(
            "SELECT COALESCE(SUM(base_salary+COALESCE(allowances,0)),0) FROM employees WHERE business_id=? AND status='active'", (biz,)
        ).fetchone()[0]
        stats["nationalities"] = [dict(r) for r in db.execute(
            "SELECT nationality, COUNT(*) cnt FROM employees WHERE business_id=? AND status='active' GROUP BY nationality ORDER BY cnt DESC",
            (biz,)
        ).fetchall()]
        stats["by_dept"] = [dict(r) for r in db.execute(
            "SELECT department, COUNT(*) cnt, SUM(base_salary) total_salary FROM employees WHERE business_id=? AND status='active' GROUP BY department ORDER BY cnt DESC",
            (biz,)
        ).fetchall()]
        stats["total_advances"] = db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM hr_advances WHERE business_id=? AND status='active'", (biz,)
        ).fetchone()[0]
        stats["total_assets"] = db.execute(
            "SELECT COALESCE(SUM(current_value),0) FROM hr_assets WHERE business_id=?", (biz,)
        ).fetchone()[0]
        stats["total_dep"] = db.execute(
            "SELECT COALESCE(SUM(accumulated_depreciation),0) FROM hr_assets WHERE business_id=?", (biz,)
        ).fetchone()[0]
    except Exception as ex:
        pass

    return render_template("hr/reports.html", stats=stats, now=now)


# ══════════════════════════════════════════════════════════
# DB INIT — تهيئة جداول HR
# ══════════════════════════════════════════════════════════
def init_hr_tables(db):
    """ينشئ جداول HR إن لم تكن موجودة"""
    tables = [
        """CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            national_id TEXT,
            phone TEXT,
            email TEXT,
            job_title TEXT,
            department TEXT,
            hire_date TEXT,
            base_salary REAL DEFAULT 0,
            allowances REAL DEFAULT 0,
            bank_account TEXT,
            bank_name TEXT,
            nationality TEXT DEFAULT 'سعودي',
            status TEXT DEFAULT 'active',
            notes TEXT,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS hr_payroll (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            period_month TEXT NOT NULL,
            base_salary REAL DEFAULT 0,
            allowances REAL DEFAULT 0,
            advance_deduction REAL DEFAULT 0,
            social_insurance REAL DEFAULT 0,
            other_deductions REAL DEFAULT 0,
            bonus REAL DEFAULT 0,
            gross_salary REAL DEFAULT 0,
            net_salary REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            payment_date TEXT,
            notes TEXT,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS hr_leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            leave_type TEXT DEFAULT 'سنوية',
            start_date TEXT,
            end_date TEXT,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS hr_advances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            amount REAL DEFAULT 0,
            monthly_deduction REAL DEFAULT 0,
            reason TEXT,
            advance_date TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS hr_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            asset_name TEXT NOT NULL,
            asset_type TEXT DEFAULT 'أثاث ومعدات',
            serial_number TEXT,
            purchase_date TEXT,
            cost REAL DEFAULT 0,
            useful_life_years INTEGER DEFAULT 5,
            annual_depreciation REAL DEFAULT 0,
            accumulated_depreciation REAL DEFAULT 0,
            current_value REAL DEFAULT 0,
            location TEXT,
            status TEXT DEFAULT 'نشط',
            notes TEXT,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS hr_budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER DEFAULT 0,
            category TEXT NOT NULL,
            description TEXT,
            amount REAL DEFAULT 0,
            created_at TEXT
        )""",
    ]
    for sql in tables:
        try:
            db.execute(sql)
        except Exception:
            pass
