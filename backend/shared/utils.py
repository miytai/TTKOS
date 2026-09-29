"""Утилиты общего назначения."""

import re
import secrets
import unicodedata
from datetime import timedelta

from django.utils.text import slugify as django_slugify

TRANSLIT_MAP = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
    }
)

MENTION_RE = re.compile(r"(?<![\w@])@([a-zA-Z0-9_]{3,32})\b")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


def slugify(value: str, max_length: int = 100) -> str:
    """Транслитерировать и превратить в slug (TECHSPEC §10.2)."""
    normalized = unicodedata.normalize("NFKD", str(value)).translate(TRANSLIT_MAP)
    slug = django_slugify(normalized, allow_unicode=False)
    return slug[:max_length].strip("-") or "item"


def unique_slug(instance, value: str, slug_field: str = "slug",
                max_length: int = 100, suffix_length: int = 6) -> str:
    """Сгенерировать уникальный slug в пределах модели (TECHSPEC §11.5)."""
    base = slugify(value, max_length)
    model = instance.__class__
    for _ in range(5):
        if not model.objects.filter(**{slug_field: base}).exists():
            return base
        base = f"{slugify(value, max_length - suffix_length - 1)}-{secrets.token_hex(3)}"

    # Гарантированный уникальный вариант
    return f"{base[:max_length - 9]}-{secrets.token_hex(4)}"[:max_length]


def extract_mentions(text: str) -> list[str]:
    """Извлечь @упоминания из markdown-текста (TECHSPEC §4.9)."""
    if not text:
        return []
    seen: list[str] = []
    for username in MENTION_RE.findall(text):
        if username not in seen:
            seen.append(username)
    return seen


def random_token(length: int = 32) -> str:
    """Криптографически стойкий URL-safe токен."""
    return secrets.token_urlsafe(length)[:length]


def parse_duration_to_timedelta(**kwargs) -> timedelta:
    """Собрать timedelta из набора единиц (для банов, TTL)."""
    return timedelta(**kwargs)


def strip_html(text: str) -> str:
    """Убрать HTML-теги из готового HTML (для OG-описаний, превью)."""
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def truncate(text: str, limit: int = 160, suffix: str = "…") -> str:
    """Обрезать строку с многоточием."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - len(suffix)].rstrip() + suffix


def client_ip(request) -> str:
    """IP клиента с учётом обратного прокси."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def ensure_queryset_bool(value: str | bool | None) -> bool:
    """Разобрать query-параметр-флаг."""
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def get_request_meta(request) -> dict:
    """Метаданные запроса для audit log (TECHSPEC §15.11)."""
    return {
        "ip": client_ip(request),
        "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:256],
        "path": request.path[:256],
    }


__all__ = [
    "MENTION_RE",
    "USERNAME_RE",
    "client_ip",
    "ensure_queryset_bool",
    "extract_mentions",
    "get_request_meta",
    "parse_duration_to_timedelta",
    "random_token",
    "slugify",
    "strip_html",
    "truncate",
    "unique_slug",
]
