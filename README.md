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

## Windows Installer (تحميل وتثبيت سلس)
يمكنك تحويل النظام إلى برنامج قابل للتثبيت ومشاركته مع أي مستخدم Windows بسهولة.

1. بناء نسخة التثبيت:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\build_windows_release.ps1 -Version 1.0.1
```

إصدار شهادة توقيع ذاتية (داخلية) لاستخدامها مباشرة:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\create_self_signed_code_sign_cert.ps1 -Password "<strong-password>"
```

للتوقيع الرقمي (اختياري واحترافي):

```powershell
$env:JENAN_SIGN_CERT_PATH="C:\certs\JenanBiz.pfx"
$env:JENAN_SIGN_CERT_PASSWORD="<password>"
powershell -ExecutionPolicy Bypass -File .\packaging\windows\build_windows_release.ps1 -Version 1.0.1
```

2. مخرجات البناء:
- نسخة مثبتة: `dist\setup\JenanBiz-Setup-1.0.1.exe`
- بصمة تحقق: `dist\setup\JenanBiz-Setup-1.0.1.sha256.txt`
- نسخة تشغيل مباشرة: `dist\installer\JenanBiz.exe`
- نسخة محمولة مضغوطة: `dist\setup\JenanBiz-Portable-1.0.1.zip`
- بصمة تحقق للنسخة المحمولة: `dist\setup\JenanBiz-Portable-1.0.1.sha256.txt`

3. بعد التثبيت عند العميل:
- تشغيل البرنامج من قائمة Start.
- يفتح تلقائيا على: `http://127.0.0.1:5001`
- بيانات العميل تُحفظ في: `%LOCALAPPDATA%\JenanBiz`

4. التشغيل على الشبكة الداخلية (LAN):
- اضبط متغير البيئة: `JENAN_HOST=0.0.0.0`
- ثم الوصول من جهاز آخر عبر:
  `http://<IP-OF-HOST-PC>:5001`

ملاحظة أمنية:
- لا تفتح المنفذ على الإنترنت العام بدون Reverse Proxy + HTTPS + جدار حماية مناسب.

## تشغيل شبكي لأي جهاز (Docker)
إذا أردت تشغيل النظام كخدمة شبكية يمكن فتحها من أي جهاز عبر المتصفح:

1. بناء وتشغيل الحاوية:

```powershell
docker compose up -d --build
```

2. الوصول من نفس الجهاز:
- `http://127.0.0.1:5001`

3. الوصول من جهاز آخر في نفس الشبكة:
- `http://<IP-OF-HOST-PC>:5001`

4. إيقاف الخدمة:

```powershell
docker compose down
```

تخزين البيانات:
- يتم حفظ قاعدة البيانات والملفات داخل `docker-data/` لضمان الاستمرارية بعد إعادة التشغيل.

## Release احترافي على GitHub
يمكنك نشر نسخة رسمية موقعة ومؤرشفة بهذه الخطوات:

1. أضف الشهادات السريّة في GitHub Secrets:
- `JENAN_SIGN_CERT_BASE64`
- `JENAN_SIGN_CERT_PASSWORD`

2. أنشئ وسم إصدار:

```powershell
git tag v1.0.1
git push origin v1.0.1
```

3. سيقوم GitHub Actions تلقائيًا ببناء:
- المثبت `JenanBiz-Setup-1.0.1.exe`
- النسخة المحمولة `JenanBiz-Portable-1.0.1.zip`
- ملفات SHA256

4. إذا لم تضع شهادة توقيع، سيبقى البناء صحيحًا لكن بدون توقيع رقمي.
