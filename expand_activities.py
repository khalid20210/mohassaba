"""
expand_activities.py
===================
توسيع قائمة الأنشطة من 57 إلى 196 نشاط شامل
يحقن الأنشطة في قاعدة البيانات المركزية والمحلية

الأنشطة الإضافية تغطي:
  • تخصصات تجارية متقدمة
  • خدمات احترافية
  • صناعات متخصصة
  • مهن حرة
"""

import sqlite3
from datetime import datetime

# إعداد الترميز
import sys
import io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# قاموس الأنشطة الـ 196
ACTIVITIES_196 = {
    # ─── من الأنشطة الموجودة (57) ────────────────────────────────
    "food_restaurant": {"name_ar": "مطعم", "category": "food", "sub_category": "مطاعم"},
    "food_cafe": {"name_ar": "كافيه", "category": "food", "sub_category": "مقاهي"},
    "food_coffeeshop": {"name_ar": "مقهى", "category": "food", "sub_category": "مقاهي"},
    "food_hookah": {"name_ar": "معسلات", "category": "food", "sub_category": "معسلات"},
    "retail_fnb_supermarket": {"name_ar": "سوبر ماركت", "category": "retail", "sub_category": "غذائي"},
    "retail_fnb_grocery": {"name_ar": "بقالة / تموينات", "category": "retail", "sub_category": "غذائي"},
    "retail_fnb_roaster": {"name_ar": "محمصة", "category": "retail", "sub_category": "غذائي"},
    "retail_fnb_bakery": {"name_ar": "مخبز", "category": "retail", "sub_category": "غذائي"},
    "retail_fnb_butcher": {"name_ar": "ملحمة / جزارة", "category": "retail", "sub_category": "غذائي"},
    "retail_fnb_produce": {"name_ar": "خضار وفواكه", "category": "retail", "sub_category": "غذائي"},
    "retail_fnb_dates": {"name_ar": "تجار التمور", "category": "retail", "sub_category": "غذائي"},
    "retail_fnb_beverages": {"name_ar": "مياه ومشروبات", "category": "retail", "sub_category": "غذائي"},
    "retail_fashion_clothing_m": {"name_ar": "ملابس رجالي", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_clothing_f": {"name_ar": "ملابس نسائي", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_clothing_k": {"name_ar": "ملابس أطفال", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_shoes": {"name_ar": "أحذية", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_bags": {"name_ar": "حقائب وإكسسوارات", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_watches": {"name_ar": "ساعات ومجوهرات", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_optics": {"name_ar": "نظارات وبصريات", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_fabric": {"name_ar": "أقمشة ومنسوجات", "category": "retail", "sub_category": "أزياء"},
    "retail_fashion_tailoring": {"name_ar": "مستلزمات خياطة", "category": "retail", "sub_category": "أزياء"},
    "retail_construction_materials": {"name_ar": "مواد بناء", "category": "retail", "sub_category": "بناء"},
    "retail_construction_plumbing": {"name_ar": "سباكة وصحيات", "category": "retail", "sub_category": "بناء"},
    "retail_construction_electrical": {"name_ar": "كهرباء وإنارة", "category": "retail", "sub_category": "بناء"},
    "retail_construction_paints": {"name_ar": "دهانات", "category": "retail", "sub_category": "بناء"},
    "retail_construction_flooring": {"name_ar": "أرضيات وسيراميك", "category": "retail", "sub_category": "بناء"},
    "retail_construction_hardware": {"name_ar": "عدد وأدوات", "category": "retail", "sub_category": "بناء"},
    "retail_electronics_mobile": {"name_ar": "جوالات وإكسسوارات", "category": "retail", "sub_category": "إلكترونيات"},
    "retail_electronics_computers": {"name_ar": "كمبيوتر ولابتوب", "category": "retail", "sub_category": "إلكترونيات"},
    "retail_electronics_appliances": {"name_ar": "أجهزة منزلية", "category": "retail", "sub_category": "إلكترونيات"},
    "retail_electronics_entertainment": {"name_ar": "إلكترونيات ترفيهية", "category": "retail", "sub_category": "إلكترونيات"},
    "retail_electronics_security": {"name_ar": "كاميرات وأمن", "category": "retail", "sub_category": "إلكترونيات"},
    "retail_health_pharmacy": {"name_ar": "صيدلية", "category": "retail", "sub_category": "صحي"},
    "retail_health_perfume": {"name_ar": "عطور وبخور", "category": "retail", "sub_category": "صحي"},
    "retail_health_cosmetics": {"name_ar": "مستحضرات تجميل", "category": "retail", "sub_category": "صحي"},
    "retail_health_medical": {"name_ar": "مستلزمات طبية", "category": "retail", "sub_category": "صحي"},
    "retail_health_supplements": {"name_ar": "مكملات غذائية", "category": "retail", "sub_category": "صحي"},
    "retail_auto_parts": {"name_ar": "قطع غيار سيارات", "category": "retail", "sub_category": "سيارات"},
    "retail_auto_tires": {"name_ar": "إطارات وبطاريات", "category": "retail", "sub_category": "سيارات"},
    "retail_auto_accessories": {"name_ar": "إكسسوارات سيارات", "category": "retail", "sub_category": "سيارات"},
    "retail_auto_workshop": {"name_ar": "ورشة صيانة سيارات", "category": "retail", "sub_category": "سيارات"},
    "retail_home_furniture": {"name_ar": "أثاث ومفروشات", "category": "retail", "sub_category": "منزل"},
    "retail_home_carpet": {"name_ar": "سجاد وموكيت", "category": "retail", "sub_category": "منزل"},
    "retail_home_kitchenware": {"name_ar": "أواني منزلية", "category": "retail", "sub_category": "منزل"},
    "retail_home_stationery": {"name_ar": "مكتبات وقرطاسية", "category": "retail", "sub_category": "منزل"},
    "retail_home_office": {"name_ar": "تجهيزات مكاتب", "category": "retail", "sub_category": "منزل"},
    "retail_specialized_tobacco": {"name_ar": "معسلات ومستلزمات تدخين", "category": "retail", "sub_category": "متخصص"},
    "retail_specialized_flowers": {"name_ar": "زهور وهدايا", "category": "retail", "sub_category": "متخصص"},
    "retail_specialized_toys": {"name_ar": "ألعاب وهدايا", "category": "retail", "sub_category": "متخصص"},
    "retail_specialized_pets": {"name_ar": "مستلزمات حيوانات أليفة", "category": "retail", "sub_category": "متخصص"},
    "retail_specialized_sports": {"name_ar": "معدات رياضية", "category": "retail", "sub_category": "متخصص"},
    "retail_specialized_camping": {"name_ar": "لوازم رحلات وصيد", "category": "retail", "sub_category": "متخصص"},
    "wholesale": {"name_ar": "تجارة جملة", "category": "wholesale", "sub_category": "عام"},
    "construction": {"name_ar": "مقاولات وتشغيل", "category": "services", "sub_category": "بناء"},
    "car_rental": {"name_ar": "تأجير سيارات", "category": "services", "sub_category": "تأجير"},
    "medical": {"name_ar": "عيادة / مستشفى", "category": "services", "sub_category": "طبي"},
    "services": {"name_ar": "خدمات عامة", "category": "services", "sub_category": "عام"},
    
    # ─── أنشطة إضافية (139 نشاط جديد) ────────────────────────────
    
    # خدمات صحية وطبية (58-75 = 18)
    "medical_dentistry": {"name_ar": "عيادة أسنان", "category": "services", "sub_category": "طبي"},
    "medical_optics": {"name_ar": "عيادة عيون", "category": "services", "sub_category": "طبي"},
    "medical_dermatology": {"name_ar": "عيادة جلدية", "category": "services", "sub_category": "طبي"},
    "medical_orthopedics": {"name_ar": "عيادة عظام", "category": "services", "sub_category": "طبي"},
    "medical_cardiology": {"name_ar": "عيادة قلب", "category": "services", "sub_category": "طبي"},
    "medical_pediatrics": {"name_ar": "عيادة أطفال", "category": "services", "sub_category": "طبي"},
    "medical_lab": {"name_ar": "مختبر طبي", "category": "services", "sub_category": "طبي"},
    "medical_radiology": {"name_ar": "قسم الأشعات", "category": "services", "sub_category": "طبي"},
    "medical_psychology": {"name_ar": "عيادة نفسية", "category": "services", "sub_category": "طبي"},
    "medical_physiotherapy": {"name_ar": "عيادة علاج طبيعي", "category": "services", "sub_category": "طبي"},
    "wellness_gym": {"name_ar": "صالة رياضية", "category": "services", "sub_category": "صحي"},
    "wellness_spa": {"name_ar": "منتجع صحي", "category": "services", "sub_category": "صحي"},
    "wellness_massage": {"name_ar": "مركز مساج", "category": "services", "sub_category": "صحي"},
    "wellness_yoga": {"name_ar": "استوديو يوجا", "category": "services", "sub_category": "صحي"},
    "wellness_nutrition": {"name_ar": "عيادة تغذية", "category": "services", "sub_category": "صحي"},
    "wellness_dental": {"name_ar": "تقويم أسنان", "category": "services", "sub_category": "صحي"},
    "salon_hairdresser": {"name_ar": "صالون حلاقة", "category": "services", "sub_category": "جمال"},
    "salon_beauty": {"name_ar": "صالون تجميل", "category": "services", "sub_category": "جمال"},
    
    # خدمات تعليمية (76-98 = 23)
    "education_primary_school": {"name_ar": "مدرسة ابتدائية", "category": "education", "sub_category": "تعليم"},
    "education_secondary_school": {"name_ar": "مدرسة ثانوية", "category": "education", "sub_category": "تعليم"},
    "education_university": {"name_ar": "جامعة", "category": "education", "sub_category": "تعليم"},
    "education_kindergarten": {"name_ar": "روضة أطفال", "category": "education", "sub_category": "تعليم"},
    "education_driving": {"name_ar": "مدرسة قيادة", "category": "education", "sub_category": "تدريب"},
    "education_english": {"name_ar": "معهد لغة إنجليزية", "category": "education", "sub_category": "لغات"},
    "education_arabic": {"name_ar": "معهد لغة عربية", "category": "education", "sub_category": "لغات"},
    "education_french": {"name_ar": "معهد لغة فرنسية", "category": "education", "sub_category": "لغات"},
    "education_it": {"name_ar": "معهد تكنولوجيا المعلومات", "category": "education", "sub_category": "تقني"},
    "education_accounting": {"name_ar": "معهد محاسبة", "category": "education", "sub_category": "تقني"},
    "education_vocational": {"name_ar": "معهد مهني", "category": "education", "sub_category": "تقني"},
    "education_music": {"name_ar": "أكاديمية موسيقى", "category": "education", "sub_category": "فنون"},
    "education_art": {"name_ar": "أكاديمية فنون", "category": "education", "sub_category": "فنون"},
    "education_dance": {"name_ar": "استوديو رقص", "category": "education", "sub_category": "فنون"},
    "education_tutoring": {"name_ar": "معهد دروس خصوصية", "category": "education", "sub_category": "تعليم"},
    "education_martial_arts": {"name_ar": "مدرسة فنون قتالية", "category": "education", "sub_category": "رياضة"},
    "education_swimming": {"name_ar": "مدرسة السباحة", "category": "education", "sub_category": "رياضة"},
    "education_tennis": {"name_ar": "أكاديمية التنس", "category": "education", "sub_category": "رياضة"},
    "education_soccer": {"name_ar": "أكاديمية كرة قدم", "category": "education", "sub_category": "رياضة"},
    "education_coding": {"name_ar": "معهد برمجة", "category": "education", "sub_category": "تقني"},
    "education_photography": {"name_ar": "أكاديمية تصوير", "category": "education", "sub_category": "فنون"},
    "education_culinary": {"name_ar": "مدرسة الطهي", "category": "education", "sub_category": "فنون"},
    
    # خدمات تجميل وعناية شخصية (99-120 = 22)
    "beauty_skincare": {"name_ar": "مركز العناية بالبشرة", "category": "services", "sub_category": "جمال"},
    "beauty_nails": {"name_ar": "صالون أظافر", "category": "services", "sub_category": "جمال"},
    "beauty_hair": {"name_ar": "صالون شعر", "category": "services", "sub_category": "جمال"},
    "beauty_makeup": {"name_ar": "متجر مستحضرات تجميل", "category": "services", "sub_category": "جمال"},
    "beauty_threading": {"name_ar": "متخصص النمص والحلاوة", "category": "services", "sub_category": "جمال"},
    "beauty_lashes": {"name_ar": "متخصص الرموش", "category": "services", "sub_category": "جمال"},
    "beauty_tattoo": {"name_ar": "متخصص الوشم", "category": "services", "sub_category": "جمال"},
    "beauty_piercing": {"name_ar": "متخصص الثقب", "category": "services", "sub_category": "جمال"},
    "barber_shop": {"name_ar": "حلاقة رجالية", "category": "services", "sub_category": "جمال"},
    "unisex_salon": {"name_ar": "صالون مختلط", "category": "services", "sub_category": "جمال"},
    "spa_center": {"name_ar": "مركز سبا", "category": "services", "sub_category": "جمال"},
    "sauna_center": {"name_ar": "مركز حمام بخار", "category": "services", "sub_category": "جمال"},
    "henna_center": {"name_ar": "متخصص الحناء", "category": "services", "sub_category": "جمال"},
    "waxing_center": {"name_ar": "مركز إزالة الشعر", "category": "services", "sub_category": "جمال"},
    "perfume_shop": {"name_ar": "متجر عطور", "category": "retail", "sub_category": "جمال"},
    "oud_shop": {"name_ar": "متجر العود", "category": "retail", "sub_category": "جمال"},
    "incense_shop": {"name_ar": "متجر البخور", "category": "retail", "sub_category": "جمال"},
    "laundry_service": {"name_ar": "خدمة غسيل ملابس", "category": "services", "sub_category": "خدمات"},
    "tailoring_service": {"name_ar": "خدمة الخياطة", "category": "services", "sub_category": "خدمات"},
    "alterations_service": {"name_ar": "خدمة تعديل الملابس", "category": "services", "sub_category": "خدمات"},
    "dry_cleaning": {"name_ar": "تنظيف جاف", "category": "services", "sub_category": "خدمات"},
    "ironing_service": {"name_ar": "خدمة الكي", "category": "services", "sub_category": "خدمات"},
    
    # خدمات سيارات ونقل (121-145 = 25)
    "automotive_repair": {"name_ar": "ورشة إصلاح سيارات", "category": "services", "sub_category": "سيارات"},
    "automotive_painting": {"name_ar": "ورشة تصبيغ السيارات", "category": "services", "sub_category": "سيارات"},
    "automotive_detailing": {"name_ar": "خدمة تفصيل السيارات", "category": "services", "sub_category": "سيارات"},
    "automotive_wash": {"name_ar": "محطة غسيل سيارات", "category": "services", "sub_category": "سيارات"},
    "automotive_maintenance": {"name_ar": "خدمة صيانة دورية", "category": "services", "sub_category": "سيارات"},
    "automotive_tires": {"name_ar": "محل إطارات", "category": "retail", "sub_category": "سيارات"},
    "automotive_battery": {"name_ar": "محل بطاريات", "category": "retail", "sub_category": "سيارات"},
    "automotive_oil": {"name_ar": "محل زيوت محركات", "category": "retail", "sub_category": "سيارات"},
    "automotive_upholstery": {"name_ar": "خدمة تنجيد السيارات", "category": "services", "sub_category": "سيارات"},
    "automotive_windshield": {"name_ar": "محل زجاج سيارات", "category": "services", "sub_category": "سيارات"},
    "automotive_electrical": {"name_ar": "كهرباء سيارات", "category": "services", "sub_category": "سيارات"},
    "taxi_service": {"name_ar": "خدمة تاكسي", "category": "services", "sub_category": "نقل"},
    "rideshare_service": {"name_ar": "خدمة مشاركة الركوب", "category": "services", "sub_category": "نقل"},
    "delivery_service": {"name_ar": "خدمة التوصيل", "category": "services", "sub_category": "نقل"},
    "courier_service": {"name_ar": "خدمة الرسائل السريعة", "category": "services", "sub_category": "نقل"},
    "moving_service": {"name_ar": "خدمة النقل والتخزين", "category": "services", "sub_category": "نقل"},
    "logistics_service": {"name_ar": "شركة لوجستيات", "category": "services", "sub_category": "نقل"},
    "bus_service": {"name_ar": "خدمة النقل العام", "category": "services", "sub_category": "نقل"},
    "car_rental_premium": {"name_ar": "تأجير سيارات فاخرة", "category": "services", "sub_category": "تأجير"},
    "truck_rental": {"name_ar": "تأجير شاحنات", "category": "services", "sub_category": "تأجير"},
    "equipment_rental": {"name_ar": "تأجير معدات بناء", "category": "services", "sub_category": "تأجير"},
    "scooter_rental": {"name_ar": "تأجير دراجات نارية", "category": "services", "sub_category": "تأجير"},
    "bicycle_rental": {"name_ar": "تأجير دراجات هوائية", "category": "services", "sub_category": "تأجير"},
    "boat_rental": {"name_ar": "تأجير قوارب", "category": "services", "sub_category": "تأجير"},
    "wedding_cars": {"name_ar": "خدمة سيارات الأفراح", "category": "services", "sub_category": "تأجير"},
    
    # خدمات سكنية والعقارات (146-165 = 20)
    "real_estate_agency": {"name_ar": "وكالة عقارات", "category": "services", "sub_category": "عقارات"},
    "real_estate_sales": {"name_ar": "بيع العقارات", "category": "services", "sub_category": "عقارات"},
    "real_estate_rental": {"name_ar": "تأجير العقارات", "category": "services", "sub_category": "عقارات"},
    "interior_design": {"name_ar": "خدمة التصميم الداخلي", "category": "services", "sub_category": "بناء"},
    "architecture_design": {"name_ar": "خدمة التصميم المعماري", "category": "services", "sub_category": "بناء"},
    "construction_company": {"name_ar": "شركة مقاولات", "category": "services", "sub_category": "بناء"},
    "plumbing_service": {"name_ar": "خدمة السباكة", "category": "services", "sub_category": "بناء"},
    "electrical_service": {"name_ar": "خدمة الكهرباء", "category": "services", "sub_category": "بناء"},
    "painting_service": {"name_ar": "خدمة الدهان", "category": "services", "sub_category": "بناء"},
    "carpentry_service": {"name_ar": "خدمة النجارة", "category": "services", "sub_category": "بناء"},
    "masonry_service": {"name_ar": "خدمة البناء", "category": "services", "sub_category": "بناء"},
    "tiling_service": {"name_ar": "خدمة الرخام والسيراميك", "category": "services", "sub_category": "بناء"},
    "glazing_service": {"name_ar": "خدمة تركيب الزجاج", "category": "services", "sub_category": "بناء"},
    "hvac_service": {"name_ar": "خدمة التكييف والتهوية", "category": "services", "sub_category": "بناء"},
    "waterproofing_service": {"name_ar": "خدمة العزل المائي", "category": "services", "sub_category": "بناء"},
    "pest_control": {"name_ar": "خدمة مكافحة الآفات", "category": "services", "sub_category": "خدمات"},
    "cleaning_service": {"name_ar": "خدمة التنظيف", "category": "services", "sub_category": "خدمات"},
    "disinfection_service": {"name_ar": "خدمة التطهير", "category": "services", "sub_category": "خدمات"},
    "security_service": {"name_ar": "خدمة الأمن والحراسة", "category": "services", "sub_category": "أمن"},
    "surveillance_service": {"name_ar": "خدمة المراقبة", "category": "services", "sub_category": "أمن"},
    
    # خدمات غذائية وضيافة (166-185 = 20)
    "catering_service": {"name_ar": "خدمة الطعام والشراب", "category": "services", "sub_category": "غذائي"},
    "pastry_shop": {"name_ar": "محل الحلويات", "category": "retail", "sub_category": "غذائي"},
    "ice_cream_shop": {"name_ar": "محل آيس كريم", "category": "retail", "sub_category": "غذائي"},
    "juice_bar": {"name_ar": "محل عصائر", "category": "retail", "sub_category": "غذائي"},
    "smoothie_bar": {"name_ar": "محل سموثي", "category": "retail", "sub_category": "غذائي"},
    "fast_food": {"name_ar": "مطعم وجبات سريعة", "category": "food", "sub_category": "غذائي"},
    "pizza_restaurant": {"name_ar": "مطعم بيتزا", "category": "food", "sub_category": "إيطالي"},
    "pasta_restaurant": {"name_ar": "مطعم معكرونة", "category": "food", "sub_category": "إيطالي"},
    "seafood_restaurant": {"name_ar": "مطعم مأكولات بحرية", "category": "food", "sub_category": "متخصص"},
    "grilled_restaurant": {"name_ar": "مطعم شواء", "category": "food", "sub_category": "عام"},
    "buffet_restaurant": {"name_ar": "مطعم بوفيه", "category": "food", "sub_category": "عام"},
    "chinese_restaurant": {"name_ar": "مطعم صيني", "category": "food", "sub_category": "عالمي"},
    "japanese_restaurant": {"name_ar": "مطعم ياباني", "category": "food", "sub_category": "عالمي"},
    "indian_restaurant": {"name_ar": "مطعم هندي", "category": "food", "sub_category": "عالمي"},
    "thai_restaurant": {"name_ar": "مطعم تايلاندي", "category": "food", "sub_category": "عالمي"},
    "mexican_restaurant": {"name_ar": "مطعم مكسيكي", "category": "food", "sub_category": "عالمي"},
    "german_restaurant": {"name_ar": "مطعم ألماني", "category": "food", "sub_category": "عالمي"},
    "french_restaurant": {"name_ar": "مطعم فرنسي", "category": "food", "sub_category": "عالمي"},
    "syrian_restaurant": {"name_ar": "مطعم سوري", "category": "food", "sub_category": "عربي"},
    "lebanese_restaurant": {"name_ar": "مطعم لبناني", "category": "food", "sub_category": "عربي"},
    
    # خدمات ترفيهية ورياضية (186-196 = 11)
    "cinema": {"name_ar": "دار السينما", "category": "entertainment", "sub_category": "ترفيه"},
    "theater": {"name_ar": "دار المسرح", "category": "entertainment", "sub_category": "ترفيه"},
    "bowling": {"name_ar": "مركز البولينج", "category": "entertainment", "sub_category": "ترفيه"},
    "arcade": {"name_ar": "قاعة ألعاب", "category": "entertainment", "sub_category": "ترفيه"},
    "karaoke": {"name_ar": "محل كاراوكي", "category": "entertainment", "sub_category": "ترفيه"},
    "nightclub": {"name_ar": "ملهى ليلي", "category": "entertainment", "sub_category": "ترفيه"},
    "sports_bar": {"name_ar": "حانة رياضية", "category": "food", "sub_category": "ترفيه"},
    "park": {"name_ar": "حديقة ترفيهية", "category": "entertainment", "sub_category": "ترفيه"},
    "amusement_park": {"name_ar": "مدينة ملاهي", "category": "entertainment", "sub_category": "ترفيه"},
    "zoo": {"name_ar": "حديقة حيوانات", "category": "entertainment", "sub_category": "ترفيه"},
    "aquarium": {"name_ar": "حوض سمك عملاق", "category": "entertainment", "sub_category": "ترفيه"},
    
    # نشاط إضافي (196)
    "library": {"name_ar": "مكتبة عامة", "category": "services", "sub_category": "ثقافة"},
}


def expand_activities():
    """حقن الأنشطة الـ 196 في قاعدة البيانات"""
    print("=" * 80)
    print("  توسيع الأنشطة من 57 إلى 196 نشاط")
    print("=" * 80 + "\n")
    
    # قاعدة البيانات المركزية
    central_db = "database/central_saas.db"
    
    # قواعد البيانات المحلية
    local_dbs = [
        "database/local_biz-001_pos-cashier-001.db",
        "database/local_biz-001_agent-mobile-001.db",
        "database/local_biz-001_cashier-branch-002.db",
    ]
    
    # ─── حقن في قاعدة البيانات المركزية ─────────────────────────
    print("[1/2] حقن الأنشطة في قاعدة البيانات المركزية...")
    
    try:
        conn = sqlite3.connect(central_db)
        c = conn.cursor()
        
        count_added = 0
        for code, data in ACTIVITIES_196.items():
            c.execute("""
                INSERT OR REPLACE INTO activities_definitions
                (code, name_ar, name_en, category, sub_category)
                VALUES (?, ?, ?, ?, ?)
            """, (
                code,
                data.get("name_ar", code),
                data.get("name_en", code),
                data.get("category", "other"),
                data.get("sub_category", ""),
            ))
            count_added += 1
        
        conn.commit()
        total = c.execute("SELECT COUNT(*) FROM activities_definitions").fetchone()[0]
        conn.close()
        
        print(f"   ✓ تم حقن {count_added} نشاط")
        print(f"   ✓ إجمالي الأنشطة في المركز: {total}")
        
    except Exception as e:
        print(f"   ❌ خطأ: {e}")
        return False
    
    # ─── حقن في قواعس البيانات المحلية ──────────────────────────
    print("\n[2/2] حقن الأنشطة في قواعد البيانات المحلية...")
    
    for local_db in local_dbs:
        try:
            conn = sqlite3.connect(local_db)
            c = conn.cursor()
            
            for code, data in ACTIVITIES_196.items():
                c.execute("""
                    INSERT OR REPLACE INTO activities_local
                    (code, name_ar, name_en, category, sub_category)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    code,
                    data.get("name_ar", code),
                    data.get("name_en", code),
                    data.get("category", "other"),
                    data.get("sub_category", ""),
                ))
            
            conn.commit()
            total = c.execute("SELECT COUNT(*) FROM activities_local").fetchone()[0]
            conn.close()
            
            print(f"   ✓ {local_db.split('/')[-1]}: {total} نشاط")
            
        except Exception as e:
            print(f"   ❌ خطأ في {local_db}: {e}")
            return False
    
    print("\n" + "=" * 80)
    print("  ملخص النتيجة:")
    print("=" * 80)
    print(f"""
✅ تم توسيع الأنشطة بنجاح!

قبل: 57 نشاط
بعد: 196 نشاط
إضافة: 139 نشاط جديد

توزيع الأنشطة الجديدة:
  ✓ خدمات صحية وطبية — 18 نشاط
  ✓ خدمات تعليمية — 23 نشاط
  ✓ خدمات تجميل وعناية — 22 نشاط
  ✓ خدمات سيارات ونقل — 25 نشاط
  ✓ خدمات سكنية وعقارات — 20 نشاط
  ✓ خدمات غذائية وضيافة — 20 نشاط
  ✓ خدمات ترفيهية ورياضية — 11 نشاط
  ─────────────────────────────────
  المجموع: 139 نشاط جديد

✅ جميع الأنشطة محقونة في:
  ✓ قاعدة البيانات المركزية
  ✓ 3 قواعد بيانات محلية (POS, Agent, Cashier)
""")
    
    return True


if __name__ == "__main__":
    result = expand_activities()
    if result:
        print("\n✅ تم التوسع بنجاح!\n")
    else:
        print("\n❌ فشل التوسع\n")
