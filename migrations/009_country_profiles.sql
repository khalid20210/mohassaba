-- ══════════════════════════════════════════════════════════════
-- 009_country_profiles.sql — محرك التوسع الإقليمي
-- كل دولة = سطر واحد يضبط العملة + الضريبة + النظام الضريبي
-- إضافة دولة جديدة = INSERT فقط، لا تعديل في الكود
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS country_configs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code     TEXT NOT NULL UNIQUE,          -- SA | EG | AE | KW | ...
    country_name_ar  TEXT NOT NULL,
    country_name_en  TEXT NOT NULL,
    currency_code    TEXT NOT NULL DEFAULT 'SAR',   -- ISO 4217
    currency_symbol  TEXT NOT NULL DEFAULT 'ر.س',
    currency_name_ar TEXT NOT NULL DEFAULT 'ريال سعودي',
    default_tax_rate REAL NOT NULL DEFAULT 0,       -- نسبة الضريبة الافتراضية
    tax_system       TEXT NOT NULL DEFAULT 'none',  -- zatca | vat | sales_tax | none
    tax_label_ar     TEXT NOT NULL DEFAULT 'ضريبة', -- "ضريبة القيمة المضافة" / "ضريبة المبيعات"
    tax_label_en     TEXT NOT NULL DEFAULT 'Tax',
    tax_number_label TEXT NOT NULL DEFAULT 'الرقم الضريبي',
    invoice_prefix   TEXT NOT NULL DEFAULT 'INV',
    date_format      TEXT NOT NULL DEFAULT 'YYYY-MM-DD',
    phone_prefix     TEXT NOT NULL DEFAULT '+966',
    is_active        INTEGER NOT NULL DEFAULT 1,
    requires_zatca   INTEGER NOT NULL DEFAULT 0,    -- هل يلزم إصدار ZATCA؟
    extra_config     TEXT    DEFAULT '{}'           -- JSON للإعدادات الخاصة بكل دولة
);

-- ── بيانات افتراضية: دول الخليج والعالم العربي الرئيسية ──────────────────────

INSERT OR IGNORE INTO country_configs
    (country_code, country_name_ar, country_name_en,
     currency_code, currency_symbol, currency_name_ar,
     default_tax_rate, tax_system, tax_label_ar, tax_label_en, tax_number_label,
     invoice_prefix, phone_prefix, requires_zatca)
VALUES
-- السعودية
('SA', 'المملكة العربية السعودية', 'Saudi Arabia',
 'SAR', 'ر.س', 'ريال سعودي',
 15, 'zatca', 'ضريبة القيمة المضافة', 'VAT', 'الرقم الضريبي',
 'INV', '+966', 1),

-- الإمارات
('AE', 'الإمارات العربية المتحدة', 'United Arab Emirates',
 'AED', 'د.إ', 'درهم إماراتي',
 5, 'vat', 'ضريبة القيمة المضافة', 'VAT', 'رقم تسجيل ضريبة القيمة المضافة',
 'INV', '+971', 0),

-- الكويت
('KW', 'الكويت', 'Kuwait',
 'KWD', 'د.ك', 'دينار كويتي',
 0, 'none', 'بدون ضريبة', 'No Tax', 'الرقم التجاري',
 'INV', '+965', 0),

-- البحرين
('BH', 'البحرين', 'Bahrain',
 'BHD', 'د.ب', 'دينار بحريني',
 10, 'vat', 'ضريبة القيمة المضافة', 'VAT', 'الرقم الضريبي',
 'INV', '+973', 0),

-- قطر
('QA', 'قطر', 'Qatar',
 'QAR', 'ر.ق', 'ريال قطري',
 0, 'none', 'بدون ضريبة', 'No Tax', 'الرقم التجاري',
 'INV', '+974', 0),

-- عُمان
('OM', 'سلطنة عُمان', 'Oman',
 'OMR', 'ر.ع', 'ريال عُماني',
 5, 'vat', 'ضريبة القيمة المضافة', 'VAT', 'الرقم الضريبي',
 'INV', '+968', 0),

-- مصر
('EG', 'مصر', 'Egypt',
 'EGP', 'ج.م', 'جنيه مصري',
 14, 'vat', 'ضريبة القيمة المضافة', 'VAT', 'الرقم الضريبي',
 'INV', '+20', 0),

-- الأردن
('JO', 'الأردن', 'Jordan',
 'JOD', 'د.أ', 'دينار أردني',
 16, 'sales_tax', 'ضريبة المبيعات', 'Sales Tax', 'الرقم الضريبي',
 'INV', '+962', 0),

-- المغرب
('MA', 'المغرب', 'Morocco',
 'MAD', 'د.م', 'درهم مغربي',
 20, 'vat', 'ضريبة القيمة المضافة', 'TVA', 'الرقم الجبائي',
 'INV', '+212', 0),

-- تونس
('TN', 'تونس', 'Tunisia',
 'TND', 'د.ت', 'دينار تونسي',
 19, 'vat', 'ضريبة القيمة المضافة', 'TVA', 'معرف الجبائي',
 'INV', '+216', 0),

-- العراق
('IQ', 'العراق', 'Iraq',
 'IQD', 'د.ع', 'دينار عراقي',
 0, 'none', 'بدون ضريبة', 'No Tax', 'الرقم الضريبي',
 'INV', '+964', 0),

-- اليمن
('YE', 'اليمن', 'Yemen',
 'YER', 'ر.ي', 'ريال يمني',
 5, 'sales_tax', 'ضريبة المبيعات', 'Sales Tax', 'الرقم الضريبي',
 'INV', '+967', 0),

-- الولايات المتحدة
('US', 'الولايات المتحدة', 'United States',
 'USD', '$', 'دولار أمريكي',
 0, 'sales_tax', 'ضريبة المبيعات', 'Sales Tax', 'EIN',
 'INV', '+1', 0),

-- المملكة المتحدة
('GB', 'المملكة المتحدة', 'United Kingdom',
 'GBP', '£', 'جنيه إسترليني',
 20, 'vat', 'ضريبة القيمة المضافة', 'VAT', 'VAT Number',
 'INV', '+44', 0);

-- ── ربط المنشأة بالدولة ───────────────────────────────────────────────────────
-- أضف العمود إن لم يكن موجوداً
ALTER TABLE businesses ADD COLUMN country_code TEXT DEFAULT 'SA';

-- Index للأداء
CREATE INDEX IF NOT EXISTS idx_country_configs_code ON country_configs(country_code);
