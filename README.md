# Jenan Biz Platform

منصة محاسبية متعددة الشركات (SaaS) تبدأ بالسعودية، ثم الخليج، ثم التوسع العالمي.

## الهدف
- خدمة آلاف الشركات والمؤسسات بكفاءة عالية.
- عزل بيانات كل شركة بشكل صارم (multi-tenant isolation).
- جاهزية تشغيل إنتاجية مع مراقبة صحة واستقرار.

## التشغيل المحلي (Development)
1. إنشاء وتفعيل البيئة الافتراضية.
2. تثبيت الحزم:

```powershell
pip install -r requirements.txt
```

3. تشغيل التطبيق:

```powershell
python app.py
```

## التشغيل الإنتاجي (Production)
1. نسخ ملف البيئة:

```powershell
Copy-Item .env.example .env
```

2. عدّل القيم الحرجة في `.env`:
- `FLASK_ENV=production`
- `SECRET_KEY` قيمة قوية
- `SESSION_COOKIE_SECURE=true` عند وجود HTTPS
- `BEHIND_PROXY=true` إذا كان خلف Nginx/Proxy
- `SECURITY_BASELINE_REQUIRED=true` لإيقاف الإقلاع عند وجود إعدادات أمنية ضعيفة
- `CSP_MODE=strict` لتشديد سياسة المحتوى (قد يتطلب إزالة أي inline scripts/styles)

3. تشغيل إنتاجي:

```powershell
python run_production.py
```

## نقاط تشغيل مؤسسية مفعلة
- `GET /healthz` فحص حياة الخدمة
- `GET /readyz` فحص الجاهزية (زمن اتصال DB)
- `X-Request-ID` لكل طلب لتتبع الأعطال
- Rate limiting أساسي لتخفيف ضغط الهجمات/الانفجارات المرورية

## Cybersecurity CI Gates
- `security-gates.yml`: فحص SAST عبر Bandit + فحص CVE للتبعيات عبر pip-audit + فحص أسرار عبر Gitleaks.
- `codeql-analysis.yml`: تحليل CodeQL دوري وعلى كل Push/PR لاكتشاف أنماط ثغرات الكود.
- `.github/dependabot.yml`: تحديثات أسبوعية تلقائية لحزم Python و GitHub Actions.

مخرجات الفحوصات الأمنية تُرفع كـ Artifacts داخل GitHub Actions لتسهيل المراجعة والتدقيق.

## تسجيل اجتماعي حقيقي (OAuth)
لتمكين تسجيل الدخول عبر Google / Apple / Microsoft أضف مفاتيح المزود في ملف `.env`:

```env
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=

APPLE_OAUTH_CLIENT_ID=
APPLE_OAUTH_CLIENT_SECRET=

MICROSOFT_OAUTH_CLIENT_ID=
MICROSOFT_OAUTH_CLIENT_SECRET=
MICROSOFT_OAUTH_TENANT=common
```

ملاحظات:
- `MICROSOFT_OAUTH_TENANT=common` مناسب للتجربة أو SaaS متعدد العملاء.
- Apple يتطلب `client_secret` بصيغة JWT (تولده من Apple Developer).
- بعد ضبط القيم أعد تشغيل التطبيق.

## مسار التوسع الموصى به
1. المرحلة الحالية: SQLite مضبوط ومحصّن للتشغيل المستقر.
2. المرحلة التالية: PostgreSQL + Redis + Queue.
3. المرحلة اللاحقة: فصل الخدمات الثقيلة (OCR/ZATCA) وخطة DR كاملة.

## مراجع إضافية
- SCALING_SA_PLAN.md

## Launch 500 (تشغيل فعلي كبداية)
1. جهّز ملف البيئة:

```powershell
Copy-Item .env.launch500.example .env.production
```

2. شغّل فحص الجاهزية:

```powershell
.\.venv\Scripts\python.exe preflight_launch500.py
```

3. ابدأ التشغيل (API + Worker):

```powershell
powershell -ExecutionPolicy Bypass -File .\start_launch500.ps1
```

4. راقب الخدمة:
- `/healthz`
- `/readyz`
- `/monitoring`
