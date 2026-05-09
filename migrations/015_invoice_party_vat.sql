-- Migration 015: إضافة عمود الرقم الضريبي للعميل (party_vat) في جدول الفواتير
-- بدلاً من تخزينه داخل حقل الملاحظات

ALTER TABLE invoices ADD COLUMN party_vat TEXT DEFAULT '';
