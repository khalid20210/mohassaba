# خطة تحويل جنان بيز لمنصة آلاف الشركات (السعودية)

## 1) فوري (هذا الأسبوع)
- تشغيل Production فقط عبر `run_production.py` + `waitress`.
- تفعيل HTTPS عبر Nginx أو Cloudflare Tunnel.
- تفعيل نسخ احتياطي يومي لقاعدة البيانات.
- مراقبة الأداء: زمن الاستجابة، أخطاء 5xx، معدل تسجيل الدخول.

## 2) قريب (2-4 أسابيع)
- نقل قاعدة البيانات من SQLite إلى PostgreSQL.
- إضافة Redis للجلسات والكاش (بدل الاعتماد على cookies فقط في الأحمال العالية).
- إضافة Queue للمهام الثقيلة: OCR، ZATCA submission، إرسال الإشعارات.
- إضافة Observability: Sentry + Prometheus/Grafana.

## 3) SaaS جاهز (4-8 أسابيع)
- Subdomains لكل شركة: `company.jenan.biz`.
- عزل بيانات كامل على مستوى قاعدة البيانات + سياسات أمان.
- Billing/Subscriptions وربط الفوترة.
- Rate limiting لكل Tenant.
- DR strategy: نسخ احتياطي واستعادة دورية مجربة.

## 4) متطلبات السعودية
- دعم VAT 15% مع تقارير دقيقة لكل فترة.
- ربط ZATCA (المرحلة المطلوبة حسب نشاط العميل).
- دعم العربية/RTL كامل مع نماذج طباعة متوافقة.
- جاهزية فواتير ضريبية مبسطة/قياسية حسب القطاع.

## أوامر تشغيل إنتاجي

```powershell
pip install waitress
$env:FLASK_ENV="production"
$env:SESSION_COOKIE_SECURE="true"
python run_production.py
```

## ملاحظة مهمة
النسخة الحالية قوية وظيفيا، لكن للوصول إلى آلاف الشركات بثبات عالٍ يجب إتمام انتقال PostgreSQL + Redis + Queue.
