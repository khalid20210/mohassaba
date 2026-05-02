"""
modules/blueprints/construction/routes.py — قطاع المقاولات
Construction Sector: Projects, Extracts, Equipment
"""

from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps

bp = Blueprint("construction", __name__, url_prefix="/projects")


def require_perm(*perms):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.user or not g.business:
                return redirect("/login")
            user_perms = g.user.get("permissions", {})
            if user_perms.get("all"):
                return f(*args, **kwargs)
            for perm in perms:
                if perm not in user_perms:
                    flash("غير مصرح لك", "error")
                    return redirect("/dashboard")
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# PROJECTS
@bp.route("/")
@require_perm("sales")
def list_projects():
    """قائمة المشاريع"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    status = request.args.get("status", "")
    
    query = "SELECT * FROM projects WHERE business_id = ?"
    params = [business_id]
    
    if status:
        query += " AND project_status = ?"
        params.append(status)
    
    query += " ORDER BY start_date DESC"
    projects = db.execute(query, params).fetchall()
    
    return render_template("construction/projects_list.html", projects=projects)


@bp.route("/new", methods=["POST"])
@require_perm("sales")
def create_project():
    """إنشاء مشروع جديد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        INSERT INTO projects (
            business_id, project_name, project_code, client_id,
            location, start_date, planned_end_date, budget_total,
            project_status, manager_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planning', ?, datetime('now'), datetime('now'))
    """, (
        business_id,
        data.get("name"),
        data.get("code"),
        data.get("client_id"),
        data.get("location"),
        data.get("start_date"),
        data.get("end_date"),
        float(data.get("budget", 0)),
        g.user.get("id"),
    ))
    db.commit()
    
    flash("تم إنشاء المشروع", "success")
    return redirect("/projects")


@bp.route("/<int:project_id>")
@require_perm("sales")
def view_project(project_id):
    """عرض تفاصيل المشروع"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    project = db.execute(
        "SELECT * FROM projects WHERE id = ? AND business_id = ?",
        (project_id, business_id)
    ).fetchone()
    
    if not project:
        return "المشروع غير موجود", 404
    
    # المستخلصات
    extracts = db.execute(
        "SELECT * FROM project_extracts WHERE project_id = ? ORDER BY extract_date DESC",
        (project_id,)
    ).fetchall()
    
    # المعدات
    equipment = db.execute(
        "SELECT * FROM equipment WHERE assigned_project_id = ?",
        (project_id,)
    ).fetchall()
    
    return render_template("construction/project_detail.html", **{
        "project": project,
        "extracts": extracts,
        "equipment": equipment,
    })


# EXTRACTS (المستخلصات)
@bp.route("/<int:project_id>/extracts/new", methods=["POST"])
@require_perm("sales")
def create_extract(project_id):
    """إنشاء مستخلص جديد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    # الحصول على آخر مستخلص
    last_extract = db.execute(
        "SELECT total_invoiced FROM project_extracts WHERE project_id = ? ORDER BY extract_date DESC LIMIT 1",
        (project_id,)
    ).fetchone()
    
    previous_total = last_extract["total_invoiced"] if last_extract else 0
    
    db.execute("""
        INSERT INTO project_extracts (
            business_id, project_id, extract_number, extract_date,
            total_work_value, previous_total, current_percentage,
            total_invoiced, amount_to_invoice, status, created_at
        ) VALUES (?, ?, (SELECT MAX(extract_number)+1 FROM project_extracts WHERE project_id = ?),
                  datetime('now'), ?, ?, ?, ?, ?, 'pending', datetime('now'))
    """, (
        business_id,
        project_id,
        project_id,
        float(data.get("value", 0)),
        previous_total,
        float(data.get("percentage", 0)),
        float(data.get("invoiced", 0)),
        float(data.get("to_invoice", 0)),
    ))
    db.commit()
    
    flash("تم إنشاء المستخلص", "success")
    return redirect(f"/projects/{project_id}")


@bp.route("/extracts/<int:extract_id>/approve", methods=["POST"])
@require_perm("accounting")
def approve_extract(extract_id):
    """الموافقة على المستخلص وإنشاء فاتورة"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    extract = db.execute(
        "SELECT * FROM project_extracts WHERE id = ? AND business_id = ?",
        (extract_id, business_id)
    ).fetchone()
    
    if not extract:
        return jsonify({"error": "Extract not found"}), 404
    
    # تحديث حالة المستخلص
    db.execute(
        "UPDATE project_extracts SET status = 'invoiced' WHERE id = ?",
        (extract_id,)
    )
    
    db.commit()
    flash("تم الموافقة على المستخلص", "success")
    return jsonify({"success": True})


# EQUIPMENT
@bp.route("/equipment")
@require_perm("sales")
def list_equipment():
    """قائمة المعدات"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    status = request.args.get("status", "")
    
    query = "SELECT * FROM equipment WHERE business_id = ?"
    params = [business_id]
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY equipment_name ASC"
    equipment_list = db.execute(query, params).fetchall()
    
    return render_template("construction/equipment_list.html", equipment=equipment_list)


@bp.route("/equipment/new", methods=["POST"])
@require_perm("sales")
def add_equipment():
    """إضافة معدة جديدة"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        INSERT INTO equipment (
            business_id, equipment_name, equipment_type, serial_number,
            purchase_date, purchase_cost, status, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'available', ?, datetime('now'))
    """, (
        business_id,
        data.get("name"),
        data.get("type"),
        data.get("serial"),
        data.get("purchase_date"),
        float(data.get("cost", 0)),
        data.get("notes"),
    ))
    db.commit()
    
    flash("تم إضافة المعدة", "success")
    return redirect("/projects/equipment")


# ─── PROJECT ACTIONS ────────────────────────────────────────
@bp.route("/<int:project_id>/edit", methods=["POST"])
@require_perm("sales")
def edit_project(project_id):
    """تحديث بيانات المشروع"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    db.execute("""
        UPDATE projects SET
            project_name=?, location=?, planned_end_date=?,
            budget_total=?, project_status=?, notes=?, updated_at=datetime('now')
        WHERE id=? AND business_id=?
    """, (
        data.get("name"), data.get("location"), data.get("end_date"),
        float(data.get("budget", 0)), data.get("status", "planning"),
        data.get("notes", ""), project_id, g.business["id"]
    ))
    db.commit()
    flash("تم تحديث المشروع", "success")
    return redirect(f"/projects/{project_id}")


@bp.route("/<int:project_id>/complete", methods=["POST"])
@require_perm("sales")
def complete_project(project_id):
    """إغلاق المشروع كمنجز"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE projects SET project_status='completed', actual_end_date=date('now'), updated_at=datetime('now') WHERE id=? AND business_id=?",
        (project_id, g.business["id"])
    )
    db.commit()
    flash("تم إغلاق المشروع ✅", "success")
    return redirect(f"/projects/{project_id}")


# ─── EQUIPMENT ACTIONS ──────────────────────────────────────
@bp.route("/equipment/<int:eq_id>")
@require_perm("sales")
def view_equipment(eq_id):
    """تفاصيل المعدة"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    eq = db.execute("SELECT * FROM equipment WHERE id=? AND business_id=?", (eq_id, bid)).fetchone()
    if not eq:
        return "المعدة غير موجودة", 404
    return render_template("construction/equipment_detail.html", equipment=eq)


@bp.route("/equipment/<int:eq_id>/update", methods=["POST"])
@require_perm("sales")
def update_equipment(eq_id):
    """تحديث حالة المعدة"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    db.execute("""
        UPDATE equipment SET status=?, assigned_project_id=?, notes=?
        WHERE id=? AND business_id=?
    """, (
        data.get("status", "available"),
        data.get("project_id") or None,
        data.get("notes", ""),
        eq_id, g.business["id"]
    ))
    db.commit()
    flash("تم تحديث المعدة", "success")
    return redirect(f"/projects/equipment/{eq_id}")


# ─── API ────────────────────────────────────────────────────
@bp.route("/api/stats")
@require_perm("sales")
def api_construction_stats():
    """إحصائيات المقاولات"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    projects = db.execute("SELECT project_status, COUNT(*) c FROM projects WHERE business_id=? GROUP BY project_status", (bid,)).fetchall()
    total_budget = db.execute("SELECT COALESCE(SUM(budget_total),0) FROM projects WHERE business_id=? AND project_status NOT IN ('cancelled')", (bid,)).fetchone()[0]
    return jsonify({
        "projects": {r["project_status"]: r["c"] for r in projects},
        "total_budget": total_budget
    })
