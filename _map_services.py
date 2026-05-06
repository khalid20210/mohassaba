#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""خريطة كاملة للخدمات المشتركة والمخصصة"""

import sqlite3, os

conn = sqlite3.connect("database/accounting_dev.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# جداول قاعدة البيانات
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]

print("=" * 80)
print("🏗️ جداول قاعدة البيانات — الخدمات المحاسبية")
print("=" * 80)

# تصنيف الجداول
shared_tables = []
specialized_tables = []

for t in tables:
    if any(k in t for k in ['invoice', 'product', 'business', 'user', 'account',
                              'journal', 'contact', 'warehouse', 'employee', 'payroll',
                              'purchase', 'payment', 'setting', 'audit', 'tax']):
        shared_tables.append(t)
    elif any(k in t for k in ['recipe', 'menu', 'table', 'shift', 'pos', 'patient',
                               'rental', 'lease', 'construction', 'medical', 'bed']):
        specialized_tables.append(t)
    else:
        shared_tables.append(t)

print("\n📦 الخدمات المشتركة (لجميع الأنشطة):")
print("-" * 40)
for t in sorted(shared_tables):
    print(f"  ✓ {t}")

print("\n🏥 الخدمات المخصصة (لأنشطة محددة):")
print("-" * 40)
for t in sorted(specialized_tables):
    print(f"  ★ {t}")

# Blueprints المتاحة
print("\n" + "=" * 80)
print("📁 Blueprints المتاحة (modules/blueprints/):")
print("=" * 80)

bp_path = "modules/blueprints"
blueprints = sorted(os.listdir(bp_path))

bp_info = {
    "accounting":    ("✅ مشترك", "المحاسبة العامة — دفتر اليومية، الميزانية، الأرباح"),
    "auth":          ("✅ مشترك", "تسجيل الدخول والتسجيل"),
    "contacts":      ("✅ مشترك", "العملاء والموردين"),
    "core":          ("✅ مشترك", "لوحة التحكم والإعدادات العامة"),
    "inventory":     ("✅ مشترك", "المخزون والمستودعات"),
    "invoices":      ("✅ مشترك", "الفواتير (مبيعات + مشتريات)"),
    "owner":         ("✅ مشترك", "لوحة المالك وتقارير الإدارة"),
    "supply":        ("✅ مشترك", "المشتريات وطلبات التوريد"),
    "workforce":     ("✅ مشترك", "الموارد البشرية والرواتب"),
    "barcode":       ("✅ مشترك", "الباركود ومسح المنتجات"),
    "services":      ("✅ مشترك", "الخدمات العامة (API مساعد)"),
    "pos":           ("⭐ مخصص", "نقاط البيع — تجزئة، سوبرماركت، كاشير"),
    "restaurant":    ("⭐ مخصص", "المطاعم — منيو، طاولات، طلبات"),
    "medical":       ("⭐ مخصص", "المجمعات الطبية — مرضى، مواعيد، فواتير طبية"),
    "rental":        ("⭐ مخصص", "تأجير العقارات والسيارات"),
    "construction":  ("⭐ مخصص", "المقاولات — عطاءات، مشاريع، إنجاز"),
    "wholesale":     ("⭐ مخصص", "الجملة — طلبيات كبيرة، عروض أسعار"),
    "recipes":       ("⭐ مخصص", "وصفات المطاعم والمخابز"),
}

for bp in blueprints:
    if bp in bp_info:
        status, desc = bp_info[bp]
        print(f"  {status:12} {bp:15} → {desc}")
    else:
        print(f"  ❓ {'':12} {bp:15}")

conn.close()
