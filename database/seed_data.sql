-- ============================================================
-- البيانات الافتراضية - شجرة الحسابات القياسية + إعدادات أساسية
-- ============================================================

-- المنشأة التجريبية
INSERT OR IGNORE INTO businesses (id, name, name_en, currency, country)
VALUES (1, 'المتجر الرئيسي', 'Main Store', 'YER', 'YE');

-- المستودع الافتراضي
INSERT OR IGNORE INTO warehouses (id, business_id, name, is_default, is_active)
VALUES (1, 1, 'المستودع الرئيسي', 1, 1);

-- الأدوار الافتراضية
INSERT OR IGNORE INTO roles (id, business_id, name, permissions, is_system) VALUES
(1, 1, 'مدير', '{"all":true}', 1),
(2, 1, 'محاسب', '{"accounting":true,"reports":true,"sales":true,"purchases":true}', 1),
(3, 1, 'أمين مخزن', '{"warehouse":true,"purchases":true}', 1),
(4, 1, 'كاشير', '{"pos":true,"sales":true}', 1);

-- ============================================================
-- شجرة الحسابات القياسية (دليل الحسابات)
-- ============================================================

-- الأصول
INSERT OR IGNORE INTO accounts (business_id,code,name,name_en,account_type,account_nature,is_header) VALUES
(1,'1','الأصول','Assets','asset','debit',1),
(1,'11','الأصول المتداولة','Current Assets','asset','debit',1),
(1,'1101','الصندوق','Cash','asset','debit',0),
(1,'1102','البنك','Bank','asset','debit',0),
(1,'1103','ذمم مدينة - عملاء','Accounts Receivable','asset','debit',0),
(1,'1104','مخزون البضاعة','Inventory','asset','debit',0),
(1,'1105','مصاريف مدفوعة مسبقاً','Prepaid Expenses','asset','debit',0),
(1,'12','الأصول الثابتة','Fixed Assets','asset','debit',1),
(1,'1201','أثاث ومعدات','Equipment','asset','debit',0),
(1,'1202','مجمع استهلاك','Accumulated Depreciation','asset','credit',0);

-- الخصوم
INSERT OR IGNORE INTO accounts (business_id,code,name,name_en,account_type,account_nature,is_header) VALUES
(1,'2','الخصوم','Liabilities','liability','credit',1),
(1,'21','الخصوم المتداولة','Current Liabilities','liability','credit',1),
(1,'2101','ذمم دائنة - موردون','Accounts Payable','liability','credit',0),
(1,'2102','ضريبة القيمة المضافة','VAT Payable','liability','credit',0),
(1,'2103','مصاريف مستحقة','Accrued Expenses','liability','credit',0);

-- حقوق الملكية
INSERT OR IGNORE INTO accounts (business_id,code,name,name_en,account_type,account_nature,is_header) VALUES
(1,'3','حقوق الملكية','Equity','equity','credit',1),
(1,'3101','رأس المال','Capital','equity','credit',0),
(1,'3102','الأرباح المحتجزة','Retained Earnings','equity','credit',0),
(1,'3103','الأرباح والخسائر','Profit & Loss','equity','credit',0);

-- الإيرادات
INSERT OR IGNORE INTO accounts (business_id,code,name,name_en,account_type,account_nature,is_header) VALUES
(1,'4','الإيرادات','Revenue','revenue','credit',1),
(1,'4101','إيرادات المبيعات','Sales Revenue','revenue','credit',0),
(1,'4102','مردودات المبيعات','Sales Returns','revenue','debit',0),
(1,'4103','خصم المبيعات','Sales Discount','revenue','debit',0);

-- المصاريف
INSERT OR IGNORE INTO accounts (business_id,code,name,name_en,account_type,account_nature,is_header) VALUES
(1,'5','المصاريف','Expenses','expense','debit',1),
(1,'5101','تكلفة البضاعة المباعة','COGS','expense','debit',0),
(1,'5102','مردودات المشتريات','Purchase Returns','expense','credit',0),
(1,'5201','مصاريف إيجار','Rent Expense','expense','debit',0),
(1,'5202','مصاريف رواتب','Salaries Expense','expense','debit',0),
(1,'5203','مصاريف كهرباء وماء','Utilities Expense','expense','debit',0),
(1,'5204','مصاريف نقل وتوصيل','Delivery Expense','expense','debit',0),
(1,'5205','مصاريف صيانة','Maintenance Expense','expense','debit',0),
(1,'5206','مصاريف متنوعة','Miscellaneous Expense','expense','debit',0);

-- ============================================================
-- إعداد الضريبة الافتراضية (بدون ضريبة)
-- ============================================================
INSERT OR IGNORE INTO tax_settings (id, business_id, name, rate, applies_to, is_active)
VALUES (1, 1, 'بدون ضريبة', 0, 'all', 1);

-- ============================================================
-- الإعدادات العامة
-- ============================================================
INSERT OR IGNORE INTO settings (business_id, key, value) VALUES
(1, 'invoice_prefix_sale',     'INV'),
(1, 'invoice_prefix_purchase', 'PUR'),
(1, 'decimal_places',          '2'),
(1, 'low_stock_alert',         '5'),
(1, 'default_warehouse',       '1'),
(1, 'default_sales_account',   '4101'),
(1, 'default_cogs_account',    '5101'),
(1, 'default_inventory_account','1104'),
(1, 'default_receivable_account','1103'),
(1, 'default_payable_account', '2101');

-- ============================================================
-- تصنيفات المنتجات (مستخرجة من ملفات CSV)
-- ============================================================
INSERT OR IGNORE INTO product_categories (business_id, name) VALUES
(1, 'أغذية'),
(1, 'مشروبات غازية'),
(1, 'عصائر'),
(1, 'ألبان وحليب'),
(1, 'شبس'),
(1, 'بسكويتات'),
(1, 'كريمات شعر وللجسم'),
(1, 'شامبوهات'),
(1, 'غسول للجسم'),
(1, 'منظفات ومطهرات'),
(1, 'أكواب ورق وبلاستيك'),
(1, 'غذاء الحيوان الأليف'),
(1, 'ولاعات'),
(1, 'فرشاة أسنان');
