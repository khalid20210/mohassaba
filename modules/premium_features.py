"""
premium_features.py
تعريف الخدمات المميزة القابلة للتفعيل / الشراء
"""

PREMIUM_FEATURES = {
    # ─── المالية المتقدمة ──────────────────────────────────
    'advanced_accounting': {
        'id': 'advanced_accounting',
        'name': 'المحاسبة المتقدمة',
        'category': 'مالية',
        'description': 'تقارير مالية متقدمة، ميزانيات، توقعات، تحليل مقارن',
        'price': 500,  # شهري
        'features': [
            '✓ ميزانيات سنوية وشهرية',
            '✓ تحليل مقارن (قطاعات، أقسام)',
            '✓ توقعات الخزينة',
            '✓ نسب مالية متقدمة',
            '✓ تقارير IFRS',
        ],
        'tier': 'professional',
    },
    
    # ─── الفواتير والضرائب ────────────────────────────────
    'zatca_integration': {
        'id': 'zatca_integration',
        'name': 'تكامل ZATCA (فاتورة إلكترونية)',
        'category': 'ضرائب',
        'description': 'ربط مباشر مع هيئة الزكاة والدخل - فاتورة إلكترونية معتمدة',
        'price': 300,
        'features': [
            '✓ فواتير معتمدة من ZATCA',
            '✓ توقيع رقمي معتمد',
            '✓ أرشفة فوراً للهيئة',
            '✓ تقارير الامتثال التلقائية',
            '✓ دعم E-Invoice v2.1',
        ],
        'tier': 'professional',
    },
    
    # ─── المخزون المتقدم ────────────────────────────────────
    'inventory_analytics': {
        'id': 'inventory_analytics',
        'name': 'تحليلات المخزون المتقدمة',
        'category': 'مخزون',
        'description': 'توقعات الطلب، أمثلية المخزون، تنبيهات ذكية',
        'price': 250,
        'features': [
            '✓ توقعات الطلب (ML)',
            '✓ حساب EOQ تلقائي',
            '✓ تنبيهات انخفاض المخزون',
            '✓ تحليل أبطأ حركة',
            '✓ نماذج تنبؤية',
        ],
        'tier': 'professional',
    },
    
    # ─── الموارد البشرية ─────────────────────────────────────
    'payroll_hr': {
        'id': 'payroll_hr',
        'name': 'الرواتب والموارد البشرية',
        'category': 'موظفين',
        'description': 'حساب الرواتب، الإجازات، الحضور، الأداء',
        'price': 350,
        'features': [
            '✓ حساب رواتب معقدة',
            '✓ خصومات وحوافز مخصصة',
            '✓ إدارة إجازات',
            '✓ تتبع الحضور',
            '✓ تقارير الكفاءة',
        ],
        'tier': 'enterprise',
    },
    
    # ─── المبيعات المتقدمة ────────────────────────────────────
    'crm_sales': {
        'id': 'crm_sales',
        'name': 'نظام CRM وتتبع المبيعات',
        'category': 'مبيعات',
        'description': 'قنوات مبيعات، عملاء متكاملة، خطوط سير العمل',
        'price': 400,
        'features': [
            '✓ إدارة خطوط مبيعات',
            '✓ ملفات عملاء 360 درجة',
            '✓ خطوط سير عمل آلية',
            '✓ توقعات المبيعات',
            '✓ تقارير أداء المندوبين',
        ],
        'tier': 'professional',
    },
    
    # ─── E-Commerce ────────────────────────────────────────
    'ecommerce_api': {
        'id': 'ecommerce_api',
        'name': 'متجر إلكتروني متكامل',
        'category': 'متجر',
        'description': 'متجر أونلاين متكامل مع المحاسبة',
        'price': 600,
        'features': [
            '✓ متجر ويب مستقل',
            '✓ دعم عملات متعددة',
            '✓ طرق دفع متعددة',
            '✓ تكامل لوجستي',
            '✓ إدارة طلبات أونلاين',
        ],
        'tier': 'enterprise',
    },
    
    # ─── التقارير الذكية ────────────────────────────────────
    'advanced_reports': {
        'id': 'advanced_reports',
        'name': 'التقارير والرؤى الذكية',
        'category': 'تحليل',
        'description': 'لوحات معلومات ديناميكية، رؤى ذكية، تنبؤات',
        'price': 200,
        'features': [
            '✓ لوحات معلومات مخصصة',
            '✓ رؤى ذكية (AI)',
            '✓ تنبيهات استثنائية',
            '✓ تصدير متقدم',
            '✓ جدولة التقارير',
        ],
        'tier': 'professional',
    },
    
    # ─── API الخارجية ────────────────────────────────────────
    'api_webhooks': {
        'id': 'api_webhooks',
        'name': 'API متقدمة و Webhooks',
        'category': 'تطوير',
        'description': 'API مفتوحة للتطبيقات الخارجية',
        'price': 150,
        'features': [
            '✓ REST API كامل',
            '✓ Webhooks و الأحداث',
            '✓ OAuth 2.0',
            '✓ حد استخدام عالي',
            '✓ دعم GraphQL',
        ],
        'tier': 'professional',
    },
    
    # ─── النسخ الاحتياطي والكوارث ──────────────────────────
    'backup_dr': {
        'id': 'backup_dr',
        'name': 'النسخ الاحتياطي والاستعادة',
        'category': 'أمان',
        'description': 'نسخ احتياطي يومي، استعادة فورية، كوارث',
        'price': 100,
        'features': [
            '✓ نسخ احتياطي يومي أتوماتيكي',
            '✓ استعادة في أي نقطة زمنية',
            '✓ محيطات متعددة',
            '✓ ضمان 99.9% SLA',
            '✓ تشفير كامل',
        ],
        'tier': 'professional',
    },
}

def get_feature(feature_id):
    """احصل على تفاصيل ميزة معينة"""
    return PREMIUM_FEATURES.get(feature_id)

def list_features(tier=None):
    """اسرد جميع الميزات أو بمستوى معين"""
    if tier:
        return {k: v for k, v in PREMIUM_FEATURES.items() if v.get('tier') == tier}
    return PREMIUM_FEATURES

def get_features_by_category(category):
    """اسرد الميزات حسب الفئة"""
    return {k: v for k, v in PREMIUM_FEATURES.items() if v.get('category') == category}
