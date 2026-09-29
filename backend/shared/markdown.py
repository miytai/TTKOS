"""Markdown → безопасный HTML (TECHSPEC §4.5, §15.4).

Рендеринг выполняется на backend, результат санитизируется bleach.
На frontend дополнительно применяется DOMPurify (defence in depth).
"""

import re

import bleach
import mistune
from django.conf import settings

ALLOWED_TAGS = [
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "del", "s", "mark", "small",
    "ul", "ol", "li",
    "blockquote", "pre", "code",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "input",  # task-lists (- [x])
    "span", "div",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height", "loading"],
    "code": ["class"],
    "pre": ["class"],
    "span": ["class"],
    "div": ["class"],
    "input": ["type", "checked", "disabled"],
    "th": ["align"],
    "td": ["align"],
    "li": ["class"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _create_renderer() -> mistune.Markdown:
    """Создать markdown-рендерер со всеми требуемыми плагинами (mistune 3)."""
    return mistune.create_markdown(
        plugins=[
            "strikethrough",
            "insert",
            "superscript",
            "subscript",
            "mark",
            "table",
            "task_lists",
            "url",
            "footnotes",
            "def_list",
            "abbr",
            "ruby",
            "spoiler",
            "speedup",
        ],
        escape=True,
        renderer=mistune.HTMLRenderer(escape=True),
    )


renderer = _create_renderer()


def render_markdown(text: str) -> str:
    """Markdown → санитизированный HTML.

    ``escape=True`` в рендерере означает, что пользовательский HTML не
    интерпретируется, а bleach отсекает всё лишнее в итоговом HTML.
    """
    if not text:
        return ""
    html = renderer(text)
    return sanitize_html(html)


def sanitize_html(html: str) -> str:
    """Bleach-санитизация готового HTML (TECHSPEC §15.4)."""
    if not html:
        return ""
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


def markdown_preview(text: str, max_length: int | None = None) -> str:
    """Рендер с ограничением длины (используется в OG-картинках и превью)."""
    source = text or ""
    if max_length:
        source = source[:max_length]
    return render_markdown(source)


def extract_text_preview(text: str, limit: int = 200) -> str:
    """Плоский текст из markdown — для описаний и поисковых сниппетов."""
    plain = bleach.clean(text or "", tags=[], attributes={}, strip=True)
    plain = re_sub_spaces(plain)
    return plain[:limit]


def re_sub_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_markdown_settings() -> dict:
    """Настройки для фронтенда (единый источник правды)."""
    return {
        "max_body_length": getattr(settings, "BODY_MAX_LENGTH", 50_000),
        "allowed_tags": ALLOWED_TAGS,
    }
