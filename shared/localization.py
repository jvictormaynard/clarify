"""Small UI catalog shared by clients and authentication email templates."""

import json
import locale
from functools import lru_cache
from pathlib import Path


def language(value):
    primary = str(value or "").lower().replace("_", "-").split("-", 1)[0]
    return primary if primary in {"pt", "en", "es"} else "en"


def device_language():
    # Windows' UI language can differ from the regional number/date locale.
    import sys

    if sys.platform == "win32":
        import ctypes

        identifier = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if identifier in locale.windows_locale:
            return language(locale.windows_locale[identifier])
    return language(locale.getlocale()[0])


@lru_cache(maxsize=1)
def catalog():
    return json.loads(
        Path(__file__).with_name("ui_strings.json").read_text(encoding="utf-8")
    )


def translate(source, lang=None, **values):
    text = catalog().get(source, {}).get(language(lang or device_language()), source)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text
