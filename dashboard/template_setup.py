"""Jinja2 template engine configuration for the dashboard."""
from markupsafe import Markup
from pathlib import Path

from fastapi.templating import Jinja2Templates

from dashboard.i18n import t, get_all_strings, SUPPORTED_LANGS, DEFAULT_LANG

_TEMPLATE_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

# Register globals available in all templates
templates.env.globals["t"] = t
templates.env.globals["SUPPORTED_LANGS"] = SUPPORTED_LANGS
templates.env.globals["DEFAULT_LANG"] = DEFAULT_LANG
templates.env.globals["get_all_strings"] = get_all_strings


# Custom filters
def _format_diff(text: str) -> Markup:
    """Format diff text with colored spans for add/del lines."""
    from markupsafe import escape
    lines = []
    for line in str(text).split("\n"):
        escaped = escape(line)
        if line.startswith("+"):
            lines.append(f'<span class="diff-add">{escaped}</span>')
        elif line.startswith("-"):
            lines.append(f'<span class="diff-del">{escaped}</span>')
        else:
            lines.append(str(escaped))
    return Markup("\n".join(lines))


templates.env.filters["format_diff"] = _format_diff


_UK_MONTHS = {
    1: "січ", 2: "лют", 3: "бер", 4: "кві", 5: "тра", 6: "чер",
    7: "лип", 8: "сер", 9: "вер", 10: "жов", 11: "лис", 12: "гру",
}
_EN_MONTHS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _format_date(dt, lang: str = "uk") -> str:
    """Format datetime as locale-aware short date: '15 бер 2026' / 'Mar 15, 2026'."""
    if not dt:
        return ""
    if lang == "en":
        return f"{_EN_MONTHS[dt.month]} {dt.day}, {dt.year}"
    return f"{dt.day} {_UK_MONTHS[dt.month]} {dt.year}"


templates.env.filters["format_date"] = _format_date
