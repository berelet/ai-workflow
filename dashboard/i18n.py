"""Server-side i18n: loads lang JSON files and exposes t() for Jinja2 templates."""
import json
from pathlib import Path

_LANG_DIR = Path(__file__).parent / "static" / "lang"
_CACHE: dict[str, dict[str, str]] = {}
SUPPORTED_LANGS = ("uk", "en")
DEFAULT_LANG = "uk"


def _load(lang: str) -> dict[str, str]:
    if lang not in _CACHE:
        path = _LANG_DIR / f"{lang}.json"
        if path.exists():
            _CACHE[lang] = json.loads(path.read_text("utf-8"))
        else:
            _CACHE[lang] = {}
    return _CACHE[lang]


def t(key: str, lang: str = DEFAULT_LANG, **params: str) -> str:
    """Translate key to given language. Supports {param} interpolation."""
    strings = _load(lang)
    s = strings.get(key, key)
    for k, v in params.items():
        s = s.replace(f"{{{k}}}", str(v))
    return s


def get_all_strings(lang: str = DEFAULT_LANG) -> dict[str, str]:
    """Return full translation dict (for injecting subset into JS)."""
    return _load(lang)


def reload():
    """Clear cache — useful for dev/hot-reload."""
    _CACHE.clear()
