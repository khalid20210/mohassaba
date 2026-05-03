"""
blueprints/recipes/routes.py — إدارة الوصفات (للمطاعم والمطابخ)
CRUD كامل: إضافة + تعديل + حذف + حساب تكلفة المكونات تلقائياً
"""
import json
from datetime import datetime

from flask import (
    Blueprint, flash, g, jsonify, redirect,
    render_template, request, session, url_for
)

from modules.extensions import get_db
from modules.middleware import onboarding_required, require_perm, write_audit_log

bp = Blueprint("recipes", __name__, url_prefix="/recipes")

# التصنيفات المتاحة
_CATEGORIES = [
    ("appetizer",  "مقبلات"),
    ("main",       "الطبق الرئيسي"),
    ("dessert",    "حلويات"),
    ("beverage",   "مشروبات"),
    ("sauce",      "صلصات"),
    ("bread",      "خبز ومعجنات"),
    ("salad",      "سلطات"),
    ("soup",       "شوربات"),
    ("other",      "أخرى"),
]

_DIFFICULTY = [
    ("easy",   "سهلة"),
    ("medium", "متوسطة"),
    ("hard",   "صعبة"),
]


@bp.route("/")
@require_perm("pos")
def list_recipes():
    """قائمة الوصفات"""
    db     = get_db()
    biz_id = session["business_id"]

    category = request.args.get("category", "")
    q        = request.args.get("q", "").strip()[:80]
    page     = max(1, min(int(request.args.get("page", 1)), 9999))
    per_page = 20

    conditions = ["r.business_id = ?"]
    params     = [biz_id]

    if category:
        valid_cats = {c for c, _ in _CATEGORIES}
        if category in valid_cats:
            conditions.append("r.category = ?")
            params.append(category)

    if q:
        conditions.append("r.recipe_name LIKE ?")
        params.append(f"%{q}%")

    where = "WHERE " + " AND ".join(conditions)

    total = db.execute(
        f"SELECT COUNT(*) FROM recipes r {where}", params
    ).fetchone()[0]

    recipes = db.execute(
        f"""SELECT r.id, r.recipe_name, r.category, r.cost_per_unit,
                   r.selling_price, r.preparation_time, r.cooking_time,
                   r.difficulty_level, r.yield_quantity, r.yield_unit,
                   r.is_active, r.created_at,
                   p.name AS product_name
            FROM recipes r
            LEFT JOIN products p ON p.id = r.product_id
            {where}
            ORDER BY r.recipe_name ASC
            LIMIT ? OFFSET ?""",
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "recipes/list.html",
        recipes=[dict(r) for r in recipes],
        total=total,
        page=page,
        total_pages=total_pages,
        categories=_CATEGORIES,
        difficulty=_DIFFICULTY,
        filter_category=category,
        filter_q=q,
    )


@bp.route("/new", methods=["GET", "POST"])
@require_perm("pos")
def add_recipe():
    """إضافة وصفة جديدة"""
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "POST":
        name       = request.form.get("recipe_name", "").strip()[:200]
        category   = request.form.get("category", "other")
        difficulty = request.form.get("difficulty_level", "medium")
        prep_time  = request.form.get("preparation_time", 0)
        cook_time  = request.form.get("cooking_time", 0)
        yield_qty  = request.form.get("yield_quantity", 1)
        yield_unit = request.form.get("yield_unit", "حصة")[:50]
        sell_price = request.form.get("selling_price", 0)
        product_id = request.form.get("product_id") or None
        description = request.form.get("description", "").strip()[:1000]

        if not name:
            flash("اسم الوصفة مطلوب", "error")
            return redirect(url_for("recipes.add_recipe"))

        # التحقق من صحة التصنيف والصعوبة
        valid_cats = {c for c, _ in _CATEGORIES}
        valid_diff = {d for d, _ in _DIFFICULTY}
        if category not in valid_cats:
            category = "other"
        if difficulty not in valid_diff:
            difficulty = "medium"

        # المكونات من JSON
        ingredients_json = request.form.get("ingredients_json", "[]")
        try:
            ingredients = json.loads(ingredients_json)
            if not isinstance(ingredients, list):
                ingredients = []
        except (json.JSONDecodeError, ValueError):
            ingredients = []

        # حساب التكلفة تلقائياً من المكونات
        cost_per_unit = _calculate_cost(db, biz_id, ingredients, float(yield_qty or 1))

        try:
            prep_time  = max(0, int(prep_time))
            cook_time  = max(0, int(cook_time))
            yield_qty  = max(0.1, float(yield_qty))
            sell_price = max(0, float(sell_price))
        except (ValueError, TypeError):
            flash("قيم غير صحيحة في النموذج", "error")
            return redirect(url_for("recipes.add_recipe"))

        db.execute(
            """INSERT INTO recipes
               (business_id, recipe_name, product_id, category, ingredients,
                preparation_time, cooking_time, difficulty_level,
                yield_quantity, yield_unit, cost_per_unit, selling_price,
                description, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (biz_id, name, product_id, category,
             json.dumps(ingredients, ensure_ascii=False),
             prep_time, cook_time, difficulty,
             yield_qty, yield_unit, cost_per_unit, sell_price,
             description)
        )
        db.commit()

        write_audit_log(
            db, biz_id,
            action="recipe_added",
            entity_type="recipe",
            new_value=json.dumps({"name": name, "category": category}),
        )
        flash(f"تمت إضافة الوصفة '{name}' بنجاح", "success")
        return redirect(url_for("recipes.list_recipes"))

    # GET: جلب المنتجات كمكونات محتملة
    products = db.execute(
        "SELECT id, name, purchase_price FROM products WHERE business_id=? ORDER BY name",
        (biz_id,)
    ).fetchall()

    return render_template(
        "recipes/form.html",
        products=[dict(p) for p in products],
        categories=_CATEGORIES,
        difficulty=_DIFFICULTY,
        recipe=None,
    )


@bp.route("/<int:recipe_id>/edit", methods=["GET", "POST"])
@require_perm("pos")
def edit_recipe(recipe_id: int):
    """تعديل وصفة"""
    db     = get_db()
    biz_id = session["business_id"]

    recipe = db.execute(
        "SELECT * FROM recipes WHERE id=? AND business_id=?", (recipe_id, biz_id)
    ).fetchone()
    if not recipe:
        flash("الوصفة غير موجودة", "error")
        return redirect(url_for("recipes.list_recipes"))

    if request.method == "POST":
        name       = request.form.get("recipe_name", "").strip()[:200]
        category   = request.form.get("category", "other")
        difficulty = request.form.get("difficulty_level", "medium")
        prep_time  = request.form.get("preparation_time", 0)
        cook_time  = request.form.get("cooking_time", 0)
        yield_qty  = request.form.get("yield_quantity", 1)
        yield_unit = request.form.get("yield_unit", "حصة")[:50]
        sell_price = request.form.get("selling_price", 0)
        product_id = request.form.get("product_id") or None
        description = request.form.get("description", "").strip()[:1000]

        if not name:
            flash("اسم الوصفة مطلوب", "error")
            return redirect(url_for("recipes.edit_recipe", recipe_id=recipe_id))

        valid_cats = {c for c, _ in _CATEGORIES}
        valid_diff = {d for d, _ in _DIFFICULTY}
        if category not in valid_cats:
            category = "other"
        if difficulty not in valid_diff:
            difficulty = "medium"

        ingredients_json = request.form.get("ingredients_json", "[]")
        try:
            ingredients = json.loads(ingredients_json)
            if not isinstance(ingredients, list):
                ingredients = []
        except (json.JSONDecodeError, ValueError):
            ingredients = []

        try:
            prep_time  = max(0, int(prep_time))
            cook_time  = max(0, int(cook_time))
            yield_qty  = max(0.1, float(yield_qty))
            sell_price = max(0, float(sell_price))
        except (ValueError, TypeError):
            flash("قيم غير صحيحة", "error")
            return redirect(url_for("recipes.edit_recipe", recipe_id=recipe_id))

        cost_per_unit = _calculate_cost(db, biz_id, ingredients, yield_qty)

        db.execute(
            """UPDATE recipes SET
               recipe_name=?, product_id=?, category=?, ingredients=?,
               preparation_time=?, cooking_time=?, difficulty_level=?,
               yield_quantity=?, yield_unit=?, cost_per_unit=?, selling_price=?,
               description=?
               WHERE id=? AND business_id=?""",
            (name, product_id, category,
             json.dumps(ingredients, ensure_ascii=False),
             prep_time, cook_time, difficulty,
             yield_qty, yield_unit, cost_per_unit, sell_price,
             description, recipe_id, biz_id)
        )
        db.commit()

        write_audit_log(
            db, biz_id,
            action="recipe_updated",
            entity_type="recipe",
            entity_id=recipe_id,
            new_value=json.dumps({"name": name}),
        )
        flash("تم تحديث الوصفة بنجاح", "success")
        return redirect(url_for("recipes.list_recipes"))

    products = db.execute(
        "SELECT id, name, purchase_price FROM products WHERE business_id=? ORDER BY name",
        (biz_id,)
    ).fetchall()

    return render_template(
        "recipes/form.html",
        products=[dict(p) for p in products],
        categories=_CATEGORIES,
        difficulty=_DIFFICULTY,
        recipe=dict(recipe),
    )


@bp.route("/<int:recipe_id>/toggle", methods=["POST"])
@require_perm("pos")
def toggle_recipe(recipe_id: int):
    """تفعيل / إيقاف وصفة"""
    db     = get_db()
    biz_id = session["business_id"]

    recipe = db.execute(
        "SELECT id, is_active FROM recipes WHERE id=? AND business_id=?",
        (recipe_id, biz_id)
    ).fetchone()
    if not recipe:
        return jsonify({"success": False, "error": "الوصفة غير موجودة"}), 404

    new_state = 0 if recipe["is_active"] else 1
    db.execute(
        "UPDATE recipes SET is_active=? WHERE id=? AND business_id=?",
        (new_state, recipe_id, biz_id)
    )
    db.commit()
    return jsonify({"success": True, "is_active": new_state})


@bp.route("/<int:recipe_id>/delete", methods=["POST"])
@require_perm("pos")
def delete_recipe(recipe_id: int):
    """حذف وصفة مع تسجيل في سلة المهملات"""
    db     = get_db()
    biz_id = session["business_id"]

    recipe = db.execute(
        "SELECT * FROM recipes WHERE id=? AND business_id=?", (recipe_id, biz_id)
    ).fetchone()
    if not recipe:
        flash("الوصفة غير موجودة", "error")
        return redirect(url_for("recipes.list_recipes"))

    # حفظ snapshot في سلة المهملات
    try:
        db.execute(
            """INSERT INTO recycle_bin
               (business_id, entity_type, entity_id, entity_label, entity_data, deleted_by)
               VALUES (?, 'recipe', ?, ?, ?, ?)""",
            (biz_id, recipe_id, recipe["recipe_name"],
             json.dumps(dict(recipe), ensure_ascii=False),
             session.get("user_id"))
        )
    except Exception:
        pass  # جدول recycle_bin اختياري

    db.execute(
        "DELETE FROM recipes WHERE id=? AND business_id=?", (recipe_id, biz_id)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="recipe_deleted",
        entity_type="recipe",
        entity_id=recipe_id,
        old_value=json.dumps({"name": recipe["recipe_name"]}),
    )
    flash("تم حذف الوصفة وحفظها في سلة المهملات", "success")
    return redirect(url_for("recipes.list_recipes"))


@bp.route("/api/cost-estimate", methods=["POST"])
@require_perm("pos")
def api_cost_estimate():
    """API: تقدير التكلفة لمجموعة مكونات"""
    db     = get_db()
    biz_id = session["business_id"]

    data = request.get_json(silent=True) or {}
    ingredients = data.get("ingredients", [])
    yield_qty   = max(0.01, float(data.get("yield_quantity", 1)))

    if not isinstance(ingredients, list):
        return jsonify({"success": False, "error": "ingredients يجب أن تكون مصفوفة"}), 400

    cost = _calculate_cost(db, biz_id, ingredients, yield_qty)
    return jsonify({"success": True, "cost_per_unit": round(cost, 4)})


# ── مساعدة حساب التكلفة ──────────────────────────────────────────────────────

def _calculate_cost(db, biz_id: int, ingredients: list, yield_qty: float) -> float:
    """
    يحسب تكلفة الوصفة من مكوناتها.
    كل مكوّن: { "product_id": N, "quantity": Q }
    التكلفة = Σ(سعر_شراء_المنتج × الكمية) ÷ الحجم_الكلي
    """
    total_cost = 0.0
    for item in ingredients:
        try:
            pid = int(item.get("product_id", 0))
            qty = float(item.get("quantity", 0))
            if pid <= 0 or qty <= 0:
                continue
            # RLS: تحقق أن المنتج يعود لهذه المنشأة
            prod = db.execute(
                "SELECT purchase_price FROM products WHERE id=? AND business_id=?",
                (pid, biz_id)
            ).fetchone()
            if prod:
                total_cost += (float(prod["purchase_price"] or 0) * qty)
        except (ValueError, TypeError, KeyError):
            continue

    return round(total_cost / max(0.01, yield_qty), 4)
