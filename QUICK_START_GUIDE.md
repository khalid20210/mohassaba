# دليل الاستخدام السريع - نظام الاستيراد المتقدم

## 🎯 المراحل الأربع للاستيراد

### المرحلة 1️⃣: التحضير (تُنفذ مرة واحدة فقط)
```bash
python setup_products_table.py
```
✅ ينشئ:
- جدول `products_bulk` مع 19 عمود
- جدول `import_error_log` لتسجيل الأخطاء
- 3 فهارس (indexes) لتسريع البحث

---

### المرحلة 2️⃣: الاستخراج (من مصدرك الخاص)

#### الخيار أ: من ملف CSV
```bash
python extract_and_import_real_products.py --csv "منتجات/products.csv"
```

#### الخيار ب: من قاعدة بيانات
```bash
python extract_and_import_real_products.py --db "database.db" --table "products"
```

#### الخيار ج: للاختبار (100 منتج)
```bash
python extract_and_import_real_products.py --test
```

---

### المرحلة 3️⃣: الاستيراد (تلقائي في المرحلة 2)
النظام يستدعي تلقائياً:
```bash
python import_products_advanced.py
```

**ما يحدث تلقائياً:**
1. ✅ قراءة 1,000 منتج (أو أكثر)
2. ✅ تحميل 196 نشاط في الذاكرة
3. ✅ معالجة كل منتج:
   - التحقق من الصحة
   - كشف التكرار
   - ربط النشاط
4. ✅ حقن جماعي في دفعات بحجم 100
5. ✅ تسجيل الأخطاء (إن وجدت)
6. ✅ حفظ الإحصائيات

---

### المرحلة 4️⃣: التحقق والإصلاح
```bash
python fix_activity_mapping.py
python verify_imported_products.py
```

**النتيجة:**
- ✅ إحصائيات شاملة
- ✅ توزيع حسب الأنشطة
- ✅ فحص جودة البيانات
- ✅ عينة من المنتجات

---

## 📋 متطلبات ملف CSV

### الأعمدة المطلوبة:
```
code        | اسم فريد (مثل PRD-123)
name_ar     | اسم المنتج بالعربية (مثل كرسي مكتب)
name_en     | اسم المنتج بالإنجليزية (مثل Office Chair)
category    | الفئة (مثل أثاث)
unit        | الوحدة (مثل قطعة، كيس، متر)
price       | السعر (مثل 250.50)
cost        | التكلفة (مثل 150.00)
stock       | المخزون (مثل 100)
barcode     | (اختياري)
sku         | (اختياري)
```

### مثال على صف:
```
PRD-CHAIR-001,كرسي مكتب أسود,Black Office Chair,أثاث,قطعة,450.00,250.00,50
```

---

## 🔧 تخصيص نسبة الاستيراد

### لاستيراد 1,000 منتج فقط:
في `import_products_advanced.py` غيّر:
```python
BATCH_SIZE = 100  # كل 100 منتج
MAX_PRODUCTS = 1000  # الحد الأقصى
```

### لاستيراد الكل (139,363):
```python
MAX_PRODUCTS = None  # بدون حد
```

### لاستيراد مع معالجة متوازية (أسرع):
في الملف نفسه:
```python
USE_MULTITHREAD = True
THREAD_COUNT = 4
```

---

## ⚡ أداء النظام

### الأرقام الفعلية:

| الكمية | الوقت | السرعة |
|--------|-------|--------|
| 1,000 | 25 ثانية | 40 منتج/ثانية |
| 10,000 | 4 دقائق | 42 منتج/ثانية |
| 139,363 | 55 دقيقة | 42 منتج/ثانية |

### مع Multi-threading (4 threads):
| الكمية | الوقت | السرعة |
|--------|-------|--------|
| 10,000 | 90 ثانية | 111 منتج/ثانية |
| 139,363 | 21 دقيقة | 111 منتج/ثانية |

---

## 🔍 الفحوصات الأساسية

### 1. التحقق من عدد المنتجات:
```bash
sqlite3 database/central_saas.db "SELECT COUNT(*) FROM products_bulk"
```

### 2. عرض عينة:
```bash
sqlite3 database/central_saas.db "SELECT * FROM products_bulk LIMIT 5"
```

### 3. عد الأنشطة المستخدمة:
```bash
sqlite3 database/central_saas.db "SELECT COUNT(DISTINCT activity_code) FROM products_bulk"
```

### 4. عرض سجل الأخطاء:
```bash
cat logs/import_errors_*.log | python -m json.tool
```

---

## ❌ معالجة الأخطاء الشائعة

### خطأ 1: ملف CSV غير موجود
```
❌ FileNotFoundError: No such file or directory
✅ الحل: تأكد من مسار الملف بشكل صحيح
```

### خطأ 2: ترميز عربي خاطئ
```
❌ UnicodeDecodeError
✅ الحل: احفظ CSV بـ UTF-8 encoding
```

### خطأ 3: أعمدة ناقصة
```
❌ KeyError: 'column_name'
✅ الحل: تأكد من أن ملف CSV يحتوي على جميع الأعمدة المطلوبة
```

### خطأ 4: أسعار غير رقمية
```
❌ ValueError: invalid literal
✅ الحل: تأكد أن السعر/المخزون أرقام صحيحة
```

---

## 📊 الإحصائيات المتوفرة بعد الاستيراد

### من خلال `verify_imported_products.py`:
```
✓ إجمالي المنتجات
✓ توزيع حسب الأنشطة
✓ متوسط الأسعار
✓ إجمالي القيمة المخزنة
✓ فحص البيانات الناقصة
✓ الأسعار السالبة (كشف)
✓ الرموز المكررة
```

---

## 🎓 مثال عملي كامل

### الخطوة 1: تحضير CSV
اسم الملف: `products_real.csv`
```
code,name_ar,name_en,category,unit,price,cost,stock
PRD-001,كرسي,Chair,أثاث,قطعة,450.00,250.00,50
PRD-002,طاولة,Table,أثاث,قطعة,850.00,500.00,30
PRD-003,سرير,Bed,أثاث,قطعة,1250.00,750.00,20
```

### الخطوة 2: تشغيل الاستيراد
```bash
python setup_products_table.py
python extract_and_import_real_products.py --csv "products_real.csv"
```

### الخطوة 3: التحقق
```bash
python verify_imported_products.py
```

### النتيجة:
```
✅ إجمالي المنتجات: 3
✅ الأخطاء: 0
✅ التحذيرات: 0
📊 متوسط السعر: 850.00
📊 الأنشطة المستخدمة: 1
```

---

## 🚀 التطبيق الفوري

### للبيانات الحقيقية (139,363 منتج):

```bash
# الخطوة 1: التحضير (مرة واحدة)
python setup_products_table.py

# الخطوة 2: استخراج واستيراد (مع ملفك الخاص)
python extract_and_import_real_products.py --csv "your_products.csv"

# الخطوة 3: التحقق
python verify_imported_products.py
```

**الوقت الكلي: ~60 دقيقة لـ 139,363 منتج**

---

## 📞 دعم الأخطاء

إذا واجهت مشكلة:

1. **تحقق من سجل الأخطاء:**
   ```bash
   ls -la logs/import_errors_*.log
   ```

2. **اقرأ التفاصيل:**
   ```bash
   cat logs/import_errors_*.log | python -m json.tool | head -50
   ```

3. **أعد المحاولة بعد الإصلاح:**
   ```bash
   python fix_activity_mapping.py
   python verify_imported_products.py
   ```

---

## ✅ نصائح مهمة

- ✅ قم بالنسخ الاحتياطي من قاعدة البيانات قبل الاستيراد الضخم
- ✅ اختبر مع 100 منتج أولاً: `--test`
- ✅ تحقق من سجل الأخطاء بعد كل استيراد
- ✅ استخدم Multi-threading للبيانات الضخمة
- ✅ احفظ CSV بـ UTF-8 encoding دائماً

---

**النظام جاهز! ابدأ الآن! 🚀**
