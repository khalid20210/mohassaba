# Launch 500 Checklist (Production)

## 1) تجهيز البيئة
1. انسخ `.env.launch500.example` إلى `.env.production`.
2. غيّر `SECRET_KEY`.
3. تأكد من تشغيل Redis على نفس الخادم أو خدمة خارجية.

## 2) التحقق قبل التشغيل
```powershell
.\.venv\Scripts\python.exe preflight_launch500.py
```

## 3) التشغيل
```powershell
powershell -ExecutionPolicy Bypass -File .\start_launch500.ps1
```

## 4) نقاط المراقبة
- GET /healthz
- GET /readyz
- GET /monitoring

## 5) معايير القبول لإطلاق 500 شركة
- readyz = 200 بشكل ثابت
- redis = ok
- queue = ok
- p95 latency < 300ms تحت حمل الاختبار
- error rate < 0.5%

## 6) ملاحظات مهمة
- الإعداد الحالي يرفع صلابة التشغيل لكنه لا يحول قاعدة البيانات إلى PostgreSQL بعد.
- للوصول إلى 500 شركة نشطة بتزامن أعلى بثقة أكبر، أولوية المرحلة القادمة: PostgreSQL migration.
