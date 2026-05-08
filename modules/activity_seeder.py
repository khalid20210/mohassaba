"""
modules/activity_seeder.py
==========================
Data Seeder للأنشطة الـ 196
- يعمل مرة واحدة فقط عند تشغيل النظام (idempotent)
- يحقن الأنشطة في جدول industry_activities بقاعدة البيانات
- لا يعيد الحقن إذا كانت الأنشطة موجودة مسبقاً
"""
from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger("jenan_biz.activity_seeder")

# خريطة تصنيف الأنشطة إلى category و sub_category
_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # ── تجزئة ─────────────────────────────────────────────────────
    "retail_fnb_":             ("retail", "food_and_beverage"),
    "retail_fashion_":         ("retail", "fashion"),
    "retail_construction_":    ("retail", "construction"),
    "retail_electronics_":     ("retail", "electronics"),
    "retail_health_":          ("retail", "health"),
    "retail_auto_":            ("retail", "automotive"),
    "retail_home_":            ("retail", "home"),
    "retail_specialized_":     ("retail", "specialized"),
    "retail":                  ("retail", "general"),
    # ── جملة ─────────────────────────────────────────────────────
    "wholesale_fnb_":          ("wholesale", "food_and_beverage"),
    "wholesale_fashion_":      ("wholesale", "fashion"),
    "wholesale_construction_": ("wholesale", "construction"),
    "wholesale_electronics_":  ("wholesale", "electronics"),
    "wholesale_health_":       ("wholesale", "health"),
    "wholesale_auto_":         ("wholesale", "automotive"),
    "wholesale_home_":         ("wholesale", "home"),
    "wholesale_specialized_":  ("wholesale", "specialized"),
    "wholesale":               ("wholesale", "general"),
    # ── تقديم طعام ───────────────────────────────────────────────
    "food_":                   ("food", "restaurant"),
    # ── خدمات طبية ───────────────────────────────────────────────
    "medical":                 ("services", "medical"),
    # ── باقي الخدمات ─────────────────────────────────────────────
    "car_rental":              ("services", "automotive"),
    "construction":            ("services", "construction"),
    "services":                ("services", "general"),
}


def _classify(code: str) -> tuple[str, str]:
    """استنتاج category و sub_category من كود النشاط"""
    for prefix, (cat, sub) in _CATEGORY_MAP.items():
        if code.startswith(prefix):
            return cat, sub
    return "other", "general"


def seed_activities(db_path: str) -> int:
    """
    حقن الأنشطة في قاعدة البيانات.
    يعيد عدد السجلات التي تم إضافتها (0 إذا كانت موجودة مسبقاً).
    """
    # استورد قائمة الأنشطة من config
    try:
        from modules.config import INDUSTRY_TYPES
    except ImportError:
        logger.error("لم يتم العثور على INDUSTRY_TYPES في modules.config")
        return 0

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        # إنشاء الجدول إذا لم يكن موجوداً
        conn.execute("""
            CREATE TABLE IF NOT EXISTS industry_activities (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                code         TEXT UNIQUE NOT NULL,
                name_ar      TEXT NOT NULL,
                name_en      TEXT,
                category     TEXT,
                sub_category TEXT,
                is_active    INTEGER DEFAULT 1,
                created_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ia_code ON industry_activities(code)"
        )

        # تحقق: هل هناك أنشطة موجودة مسبقاً؟
        existing = conn.execute(
            "SELECT COUNT(*) FROM industry_activities"
        ).fetchone()[0]

        if existing >= len(INDUSTRY_TYPES):
            logger.debug(
                "activity_seeder: %d activities already seeded — skipping",
                existing,
            )
            return 0

        # حقن الأنشطة
        inserted = 0
        for code, name_ar in INDUSTRY_TYPES:
            cat, sub = _classify(code)
            conn.execute(
                """
                INSERT OR IGNORE INTO industry_activities
                    (code, name_ar, category, sub_category)
                VALUES (?, ?, ?, ?)
                """,
                (code, name_ar, cat, sub),
            )
            inserted += conn.execute("SELECT changes()").fetchone()[0]

        conn.commit()
        logger.info(
            "activity_seeder: seeded %d / %d activities into DB",
            inserted, len(INDUSTRY_TYPES),
        )
        return inserted

    except Exception as exc:
        logger.exception("activity_seeder: failed — %s", exc)
        conn.rollback()
        return 0
    finally:
        conn.close()


def get_activities_from_db(db_path: str) -> list[tuple[str, str]]:
    """
    قراءة الأنشطة من قاعدة البيانات بدلاً من الكود.
    تُعيد قائمة (code, name_ar) مثل INDUSTRY_TYPES.
    """
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT code, name_ar FROM industry_activities "
            "WHERE is_active=1 ORDER BY id"
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        # fallback للكود إذا فشلت قراءة DB
        try:
            from modules.config import INDUSTRY_TYPES
            return INDUSTRY_TYPES
        except ImportError:
            return []
