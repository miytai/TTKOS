"""Валидаторы ForumOS (TECHSPEC §4.1, §15.3, §15.7)."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .utils import USERNAME_RE

PASSWORD_RE = re.compile(r"^(?=.*[a-zA-Zа-яА-ЯёЁ])(?=.*\d).{8,}$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# magic bytes разрешённых форматов (TECHSPEC §15.7)
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # уточняется по байтам 8-12
    b"%PDF": "application/pdf",
}


def validate_email(value: str) -> None:
    """Regex-валидация email (TECHSPEC §4.1)."""
    if not EMAIL_RE.match(value or ""):
        raise ValidationError(_("Некорректный email"), code="invalid_email")


def validate_username(value: str) -> None:
    """Username: 3–32 символа, латиница/цифры/подчёркивание (TECHSPEC §4.2)."""
    if not value or not USERNAME_RE.match(value):
        raise ValidationError(
            _("Username: 3–32 символа, только латиница, цифры и подчёркивание"),
            code="invalid_username",
        )


def validate_password(value: str) -> None:
    """Пароль: минимум 8 символов, хотя бы буква и цифра (TECHSPEC §4.1)."""
    if not value or not PASSWORD_RE.match(value):
        raise ValidationError(
            _("Пароль: минимум 8 символов, хотя бы одна буква и одна цифра"),
            code="weak_password",
        )


def validate_hex_color(value: str) -> None:
    """Accent-цвет раздела: #RGB или #RRGGBB (TECHSPEC §4.3)."""
    if not HEX_COLOR_RE.match(value or ""):
        raise ValidationError(
            _("Цвет должен быть в формате #RGB или #RRGGBB"), code="invalid_color"
        )


def detect_mime_type(fileobj) -> str | None:
    """Определить MIME по magic bytes, а не по заголовку (TECHSPEC §15.7)."""
    try:
        fileobj.seek(0)
        head = fileobj.read(16)
        fileobj.seek(0)
    except (AttributeError, OSError, ValueError):
        return None

    if not head:
        return None

    for signature, mime in MAGIC_BYTES.items():
        if head.startswith(signature):
            if mime == "image/webp":
                if head[8:12] == b"WEBP":
                    return mime
                return None
            return mime
    return None


def validate_upload(fileobj, max_bytes: int, allowed_types: list[str]) -> None:
    """Проверить размер, MIME и magic bytes загружаемого файла."""
    size = getattr(fileobj, "size", None)
    if size is not None and size > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise ValidationError(_(f"Файл больше {limit_mb:.0f} МБ"), code="file_too_large")

    detected = detect_mime_type(fileobj)
    if detected is None:
        raise ValidationError(_("Недопустимый тип файла"), code="invalid_file_type")
    if detected not in allowed_types:
        raise ValidationError(
            _("Недопустимый тип файла: %(types)s") % {"types": ", ".join(allowed_types)},
            code="invalid_file_type",
        )


def validate_upload_file(fileobj, max_bytes: int, allowed_types: list[str]) -> str:
    """DRF-совместимая проверка файла. Возвращает определённый MIME."""
    validate_upload(fileobj, max_bytes, allowed_types)
    return detect_mime_type(fileobj)
