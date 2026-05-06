-- Migration 015: إضافة عمود preferred_language لجدول المستخدمين
-- يخزن تفضيل اللغة لكل مستخدم ('ar' | 'en')

ALTER TABLE users ADD COLUMN preferred_language TEXT DEFAULT 'ar';
