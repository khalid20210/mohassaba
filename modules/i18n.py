"""
modules/i18n.py — نظام الترجمة الثنائي (عربي / إنجليزي)

الاستخدام في القوالب:
    {{ t('logout') }}
    {{ t('save') }}

الاستخدام في Python:
    from modules.i18n import translate
    translate('logout', lang='en')
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_TRANSLATIONS: dict[str, dict[str, str]] = {}
_TRANSLATIONS_DIR = Path(__file__).parent.parent / "translations"

SUPPORTED_LANGUAGES = ["ar", "en"]
DEFAULT_LANGUAGE    = "ar"


def _load(lang: str) -> dict[str, str]:
    """تحميل ملف الترجمة وتخزينه في الذاكرة."""
    if lang not in _TRANSLATIONS:
        f = _TRANSLATIONS_DIR / f"{lang}.json"
        if f.exists():
            try:
                _TRANSLATIONS[lang] = json.loads(f.read_text("utf-8"))
            except Exception as e:
                logger.warning(f"i18n: failed to load {lang}.json — {e}")
                _TRANSLATIONS[lang] = {}
        else:
            logger.warning(f"i18n: {lang}.json not found in {_TRANSLATIONS_DIR}")
            _TRANSLATIONS[lang] = {}
    return _TRANSLATIONS[lang]


def translate(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """
    إرجاع النص المترجم للمفتاح المطلوب.
    الأولوية: lang → ar → key نفسه
    """
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    result = _load(lang).get(key)
    if result is not None:
        return result
    if lang != DEFAULT_LANGUAGE:
        result = _load(DEFAULT_LANGUAGE).get(key)
        if result is not None:
            return result
    return key  # fallback: أظهر المفتاح نفسه


def reload_translations() -> None:
    """إعادة تحميل ملفات الترجمة (للتطوير أو التحديث الديناميكي)."""
    _TRANSLATIONS.clear()
