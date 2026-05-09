import modules.i18n as i18n


def setup_function():
    i18n.reload_translations()


def test_translate_returns_known_english_value():
    assert i18n.translate("logout", lang="en") == "Sign Out"


def test_translate_unsupported_language_uses_default():
    assert i18n.translate("logout", lang="fr") == "تسجيل الخروج"


def test_translate_falls_back_to_arabic_when_key_missing_in_english():
    assert i18n.translate("barcode_management", lang="en") == "إدارة الباركود"


def test_translate_returns_key_if_missing_in_all_languages():
    assert i18n.translate("totally_missing_key", lang="en") == "totally_missing_key"


def test_reload_translations_clears_cached_values():
    assert i18n.translate("logout", lang="en") == "Sign Out"
    i18n._TRANSLATIONS["en"]["logout"] = "Mutated"

    assert i18n.translate("logout", lang="en") == "Mutated"

    i18n.reload_translations()
    assert i18n.translate("logout", lang="en") == "Sign Out"
