"""
modules/validators.py — تحقق شامل ومركزي من جميع المدخلات

الاستخدام:
    from modules.validators import validate, V, ValidationError

    data, errors = validate(request.get_json(), {
        "name":      [V.required, V.str_max(100)],
        "price":     [V.required, V.positive_number],
        "email":     [V.optional, V.email],
        "quantity":  [V.required, V.positive_int],
    })
    if errors:
        return jsonify({"success": False, "errors": errors}), 400
"""
import re
import html
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple


class ValidationError(ValueError):
    """تُرفع عند فشل التحقق من مدخل واحد"""
    pass


# ─── القواعد الأساسية ──────────────────────────────────────────────────────────

class V:
    """مجموعة قواعد التحقق الجاهزة"""

    # ── وجود ──────────────────────────────────────────────────────────────────
    @staticmethod
    def required(value: Any, field: str) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValidationError(f"الحقل '{field}' مطلوب")
        return value

    @staticmethod
    def optional(value: Any, field: str) -> Any:
        """يسمح بـ None — يوقف سلسلة التحقق إذا كانت القيمة فارغة"""
        return value  # مُعالج بشكل خاص في validate()

    # ── نصوص ──────────────────────────────────────────────────────────────────
    @staticmethod
    def str_strip(value: Any, field: str) -> str:
        if value is None:
            return value
        return str(value).strip()

    @staticmethod
    def str_max(max_len: int) -> Callable:
        def check(value: Any, field: str) -> str:
            if value is None:
                return value
            v = str(value).strip()
            if len(v) > max_len:
                raise ValidationError(f"'{field}' يتجاوز الحد الأقصى {max_len} حرف")
            return v
        check.__name__ = f"str_max_{max_len}"
        return check

    @staticmethod
    def str_min(min_len: int) -> Callable:
        def check(value: Any, field: str) -> str:
            if value is None:
                return value
            v = str(value).strip()
            if len(v) < min_len:
                raise ValidationError(f"'{field}' يجب أن يكون {min_len} أحرف على الأقل")
            return v
        check.__name__ = f"str_min_{min_len}"
        return check

    @staticmethod
    def no_html(value: Any, field: str) -> str:
        """تنظيف HTML tags — يمنع XSS"""
        if value is None:
            return value
        v = str(value)
        cleaned = html.escape(v.strip())
        if re.search(r"<[^>]+>", v):
            raise ValidationError(f"'{field}' لا يمكن أن يحتوي على HTML")
        return cleaned

    @staticmethod
    def safe_text(value: Any, field: str) -> str:
        """تنظيف شامل: HTML + SQL injection أساسي"""
        if value is None:
            return value
        v = str(value).strip()
        # منع حقن SQL الأساسي
        if re.search(r"(--|;|\b(DROP|DELETE|INSERT|UPDATE|EXEC|UNION)\b)", v, re.I):
            raise ValidationError(f"'{field}' يحتوي على نص غير مسموح")
        return html.escape(v)

    # ── أرقام ──────────────────────────────────────────────────────────────────
    @staticmethod
    def positive_number(value: Any, field: str) -> float:
        try:
            n = float(value)
        except (ValueError, TypeError):
            raise ValidationError(f"'{field}' يجب أن يكون رقماً")
        if n < 0:
            raise ValidationError(f"'{field}' يجب أن يكون صفراً أو أكبر")
        return n

    @staticmethod
    def positive_int(value: Any, field: str) -> int:
        try:
            n = int(value)
        except (ValueError, TypeError):
            raise ValidationError(f"'{field}' يجب أن يكون رقماً صحيحاً")
        if n <= 0:
            raise ValidationError(f"'{field}' يجب أن يكون أكبر من صفر")
        return n

    @staticmethod
    def num_range(min_val: float, max_val: float) -> Callable:
        def check(value: Any, field: str) -> float:
            try:
                n = float(value)
            except (ValueError, TypeError):
                raise ValidationError(f"'{field}' يجب أن يكون رقماً")
            if not (min_val <= n <= max_val):
                raise ValidationError(f"'{field}' يجب أن يكون بين {min_val} و {max_val}")
            return n
        check.__name__ = f"num_range_{min_val}_{max_val}"
        return check

    # ── تواريخ ─────────────────────────────────────────────────────────────────
    @staticmethod
    def date_str(value: Any, field: str) -> str:
        """YYYY-MM-DD"""
        if value is None:
            return value
        v = str(value).strip()
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValidationError(f"'{field}' تنسيق التاريخ غير صحيح (YYYY-MM-DD)")
        return v

    @staticmethod
    def not_future(value: Any, field: str) -> str:
        """تاريخ لا يتجاوز اليوم"""
        v = V.date_str(value, field)
        if v and v > datetime.now().strftime("%Y-%m-%d"):
            raise ValidationError(f"'{field}' لا يمكن أن يكون في المستقبل")
        return v

    # ── تنسيقات محددة ─────────────────────────────────────────────────────────
    @staticmethod
    def email(value: Any, field: str) -> str:
        if value is None:
            return value
        v = str(value).strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$", v):
            raise ValidationError(f"'{field}' بريد إلكتروني غير صالح")
        return v

    @staticmethod
    def saudi_phone(value: Any, field: str) -> str:
        if value is None:
            return value
        v = re.sub(r"\s|-", "", str(value).strip())
        if not re.match(r"^(05\d{8}|\+9665\d{8})$", v):
            raise ValidationError(f"'{field}' رقم الجوال غير صالح (يجب أن يبدأ بـ 05)")
        return v

    @staticmethod
    def vat_number(value: Any, field: str) -> str:
        """رقم ضريبي سعودي — 15 رقم يبدأ بـ 3"""
        if value is None:
            return value
        v = str(value).strip()
        if not re.match(r"^3\d{14}$", v):
            raise ValidationError(f"'{field}' الرقم الضريبي يجب أن يكون 15 رقماً ويبدأ بـ 3")
        return v

    @staticmethod
    def cr_number(value: Any, field: str) -> str:
        """رقم السجل التجاري — 10 أرقام"""
        if value is None:
            return value
        v = str(value).strip()
        if not re.match(r"^\d{10}$", v):
            raise ValidationError(f"'{field}' السجل التجاري يجب أن يكون 10 أرقام")
        return v

    @staticmethod
    def payment_method(value: Any, field: str) -> str:
        allowed = {"cash", "bank", "credit"}
        v = str(value or "").strip().lower()
        if v not in allowed:
            raise ValidationError(f"'{field}' طريقة الدفع غير صالحة")
        return v

    @staticmethod
    def one_of(*choices) -> Callable:
        def check(value: Any, field: str) -> Any:
            if value not in choices:
                raise ValidationError(f"'{field}' يجب أن يكون أحد: {', '.join(str(c) for c in choices)}")
            return value
        check.__name__ = f"one_of_{choices}"
        return check

    # ── قوائم ─────────────────────────────────────────────────────────────────
    @staticmethod
    def non_empty_list(value: Any, field: str) -> list:
        if not isinstance(value, list) or len(value) == 0:
            raise ValidationError(f"'{field}' يجب أن يكون قائمة غير فارغة")
        return value

    @staticmethod
    def list_max(max_items: int) -> Callable:
        def check(value: Any, field: str) -> list:
            if isinstance(value, list) and len(value) > max_items:
                raise ValidationError(f"'{field}' يتجاوز الحد الأقصى {max_items} عنصر")
            return value
        check.__name__ = f"list_max_{max_items}"
        return check


# ─── الدالة الرئيسية ──────────────────────────────────────────────────────────

def validate(
    data: Optional[Dict],
    schema: Dict[str, List[Callable]],
) -> Tuple[Dict, Dict[str, str]]:
    """
    تحقق من البيانات حسب schema محدد.

    المعاملات:
        data:   القاموس المُدخَل (request.json أو request.form)
        schema: {field_name: [rule1, rule2, ...]}

    يُعيد:
        (cleaned_data, errors)
        errors = {} إذا كان كل شيء صحيحاً
    """
    if data is None:
        data = {}

    cleaned = {}
    errors  = {}

    for field, rules in schema.items():
        value = data.get(field)

        # فحص optional أولاً
        is_optional = any(r is V.optional for r in rules)
        if is_optional and (value is None or value == ""):
            cleaned[field] = value
            continue

        try:
            for rule in rules:
                if rule is V.optional:
                    continue
                value = rule(value, field)
            cleaned[field] = value
        except ValidationError as e:
            errors[field] = str(e)
        except (ValueError, TypeError) as e:
            errors[field] = f"قيمة غير صالحة في '{field}'"

    return cleaned, errors


def validate_or_abort(data: Optional[Dict], schema: Dict) -> Dict:
    """
    مثل validate() لكن يُعيد مباشرة jsonify+400 عبر استثناء.
    استخدم مع try/except في الـ route أو مع flask abort.
    """
    from flask import jsonify
    cleaned, errors = validate(data, schema)
    if errors:
        raise _ValidationAbort(errors)
    return cleaned


class _ValidationAbort(Exception):
    """استثناء داخلي يحمل قاموس الأخطاء"""
    def __init__(self, errors: dict):
        self.errors  = errors
        self.message = "بيانات غير صالحة"
        super().__init__(self.message)


# ─── Schemas جاهزة للاستخدام المتكرر ─────────────────────────────────────────

SCHEMA_INVOICE_LINE = {
    "product_id": [V.required, V.positive_int],
    "quantity":   [V.required, V.positive_number],
    "unit_price": [V.required, V.positive_number],
    "tax_rate":   [V.optional, V.num_range(0, 100)],
}

SCHEMA_CONTACT = {
    "name":         [V.required, V.str_max(150), V.safe_text],
    "phone":        [V.optional, V.saudi_phone],
    "email":        [V.optional, V.email],
    "vat_number":   [V.optional, V.vat_number],
    "cr_number":    [V.optional, V.cr_number],
    "contact_type": [V.required, V.one_of("customer", "supplier", "both")],
}

SCHEMA_PRODUCT = {
    "name":           [V.required, V.str_max(200), V.safe_text],
    "barcode":        [V.optional, V.str_max(50)],
    "sale_price":     [V.required, V.positive_number],
    "purchase_price": [V.optional, V.positive_number],
    "tax_rate":       [V.optional, V.num_range(0, 100)],
    "category_name":  [V.optional, V.str_max(100), V.safe_text],
}

SCHEMA_PRICING_UPDATE = {
    "product_id": [V.required, V.positive_int],
    "sale_price": [V.required, V.positive_number],
}

SCHEMA_POS_CHECKOUT = {
    "items":          [V.required, V.non_empty_list, V.list_max(500)],
    "payment_method": [V.required, V.payment_method],
}

SCHEMA_REGISTER = {
    "username":      [V.required, V.str_min(3), V.str_max(50), V.safe_text],
    "password":      [V.required, V.str_min(8), V.str_max(128)],
    "full_name":     [V.required, V.str_max(100), V.safe_text],
    "business_name": [V.required, V.str_max(150), V.safe_text],
}

SCHEMA_EMPLOYEE_CREATE = {
    "full_name":   [V.required, V.str_max(120), V.safe_text],
    "phone":       [V.optional, V.saudi_phone],
    "role_label":  [V.optional, V.str_max(100), V.safe_text],
    "base_salary": [V.optional, V.positive_number],
}

SCHEMA_BLIND_CLOSE = {
    "employee_id":   [V.required, V.positive_int],
    "shift_date":    [V.required, V.date_str],
    "expected_cash": [V.required, V.positive_number],
    "counted_cash":  [V.required, V.positive_number],
    "notes":         [V.optional, V.str_max(250), V.safe_text],
}

SCHEMA_AGENT_CREATE = {
    "full_name":       [V.required, V.str_max(120), V.safe_text],
    "phone":           [V.optional, V.saudi_phone],
    "whatsapp_number": [V.optional, V.saudi_phone],
    "commission_rate": [V.optional, V.num_range(0, 100)],
}
