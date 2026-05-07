# محاسبه

تهيئة أولية للنشر مع الحفاظ على التشغيل المحلي الحالي.

## التشغيل المحلي (Development)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

التشغيل المحلي الافتراضي:
- `FLASK_DEBUG=1`
- `FLASK_RUN_HOST=0.0.0.0`
- `FLASK_RUN_PORT=5001`

## التشغيل الإنتاجي (Production)

لا تستخدم Flask development server في الإنتاج. استخدم Gunicorn:

```bash
pip install -r requirements.txt
FLASK_ENV=production FLASK_DEBUG=0 SECRET_KEY="<strong-random-value>" \
gunicorn --bind 0.0.0.0:${PORT:-5001} --workers 1 --threads 4 --timeout 120 app:app
```

> يوجد `Procfile` جاهز بنفس مسار التشغيل للإنتاج.

## النشر السحابي (Render - اختياري)

تمت إضافة `render.yaml` كإعداد نشر minimal:
- تثبيت المتطلبات من `requirements.txt`
- تشغيل Gunicorn بدل Flask dev server
- تمرير `SECRET_KEY` كمتغير سري من منصة الاستضافة

## ملاحظات توسع لاحقة (بدون تنفيذ في هذا PR)

- هذا التعديل لا يغيّر منطق الأعمال ولا قاعدة البيانات الحالية (SQLite).
- الإعداد الحالي يُمهّد للانتقال لاحقًا إلى PostgreSQL وRedis/workers وتوسعة البنية بشكل تدريجي.
